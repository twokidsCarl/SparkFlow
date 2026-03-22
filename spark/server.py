from __future__ import annotations

import json
import os
import queue
import re
import textwrap
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = SERVICE_ROOT.parent
WORKSPACE_ROOT = REPO_ROOT / "examples" / "snake"
ENV_PATH = SERVICE_ROOT / ".env"
CONFIG_PATH = WORKSPACE_ROOT / "runtime" / "live-config.json"
HISTORY_PATH = WORKSPACE_ROOT / "runtime" / "history.json"
SNAPSHOT_DIR = WORKSPACE_ROOT / "runtime" / "snapshots"
CONFIG_LOCK = threading.Lock()
EVENT_LISTENERS: set[queue.Queue] = set()
EDITABLE_SUFFIXES = {".html", ".css", ".js", ".json", ".py", ".md"}
BLOCKED_PATH_PARTS = {"__pycache__", ".git", "runtime", "spark"}

DEFAULT_CONFIG = {
    "theme": {
        "bg": "#f5f1e8",
        "panel": "#fffaf0",
        "border": "#2f2a24",
        "grid": "#d9cfbf",
        "cell": "#f8f4ec",
        "snake": "#2f6f49",
        "snakeHead": "#1f4d33",
        "food": "#b4432f",
        "text": "#2f2a24",
        "muted": "#6f6558",
    },
    "gameplay": {
        "tickMs": 140,
    },
    "copy": {
        "helpText": "Arrow keys or WASD to move. Press Space or P to pause.",
    },
}


@dataclass
class ChatResult:
    reply: str
    summary: str
    patch: dict
    source: str
    file_edits: list[dict]


def phase_event(phase: str, label: str, **data: object) -> dict:
    payload = {"type": "phase", "phase": phase, "label": label}
    payload.update(data)
    return payload


class SparkHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.end_headers()

    def do_POST(self) -> None:
        if self.path == "/api/rollback":
            self._handle_rollback()
            return

        if self.path != "/api/chat":
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
            return

        payload = self._read_json_body()
        if payload is None:
            return

        message = str(payload.get("message", "")).strip()
        conversation = payload.get("conversation", []) or []
        task_id = str(payload.get("taskId", "")).strip() or None
        branch_from_entry_id = str(payload.get("branchFromEntryId", "")).strip() or None
        config = load_runtime_config()

        self.send_response(HTTPStatus.OK)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        if not os.environ.get("AI_API_KEY"):
            self._send_event({"type": "status", "label": "Missing API Key"})
            self._send_event(
                {
                    "type": "token",
                    "text": "AI_API_KEY is not set. Add it to spark/.env and restart spark/server.py.",
                }
            )
            self._send_event({"type": "done"})
            return

        self._send_event(phase_event("thinking", "Thinking"))
        self._send_event({"type": "status", "label": "Thinking"})

        try:
            result = build_chat_result(message, conversation, config)
        except Exception:
            self._send_event({"type": "status", "label": "Error"})
            self._send_event(
                {
                    "type": "token",
                    "text": "AI request failed. Check spark/.env, endpoint settings, and Spark logs.",
                }
            )
            self._send_event({"type": "done"})
            return

        result = sanitize_result(message, result)

        self._send_event({"type": "status", "label": "Applying"})

        for token in chunk_text(result.reply):
            self._send_event({"type": "token", "text": token})
            time.sleep(0.02)

        config_changed = False
        next_config = config
        if result.patch:
            next_config = merge_patch(config, result.patch)
            config_changed = True

        changed_files = get_changed_files(result.file_edits)
        progress_events = build_progress_events(result, changed_files, config_changed)

        for progress_event in progress_events:
            self._send_event(progress_event)
            self._send_event({"type": "status", "label": progress_event["label"]})

        if config_changed or changed_files:
            create_history_entry(
                task_id=task_id,
                prompt=message,
                summary=result.summary,
                reply=result.reply,
                source=result.source,
                changed_files=changed_files,
                config_changed=config_changed,
                branch_from_entry_id=branch_from_entry_id,
            )

        if config_changed:
            save_runtime_config(next_config)

        apply_source_edits(result.file_edits)

        if config_changed:
            broadcast_event({"event": "config-updated"})
        if changed_files:
            broadcast_event({"event": "source-changed", "data": {"files": changed_files}})
        if config_changed or changed_files:
            broadcast_event({"event": "history-updated"})

        self._send_event({"type": "patch", "patch": result.patch, "source": result.source})
        if changed_files:
            self._send_event({"type": "source-edits", "files": changed_files})
        self._send_event(phase_event("done", "Done"))
        self._send_event({"type": "done"})

    def do_GET(self) -> None:
        if self.path == "/api/config":
            self._serve_json(load_runtime_config())
            return

        if self.path == "/api/history":
            self._serve_json(load_history())
            return

        if self.path == "/events":
            self._serve_events()
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")

    def _handle_rollback(self) -> None:
        payload = self._read_json_body()
        if payload is None:
            return

        entry_id = str(payload.get("id", "")).strip()
        if not entry_id:
            self.send_error(HTTPStatus.BAD_REQUEST, "Missing history id")
            return

        entry = get_history_entry(entry_id)
        if entry is None:
            self.send_error(HTTPStatus.NOT_FOUND, "History entry not found")
            return

        create_history_entry(
            task_id=f"rollback-{int(time.time() * 1000)}",
            prompt=f"Rollback before {entry_id}",
            summary=f"Rolled back to snapshot {entry_id[-4:]}",
            reply=f"Snapshot before rolling back to {entry_id}",
            source="rollback",
            changed_files=list(get_editable_files().keys()),
            config_changed=True,
            branch_from_entry_id=entry_id,
        )
        restore_snapshot(entry_id)

        broadcast_event({"event": "config-updated"})
        broadcast_event({"event": "source-changed", "data": {"files": entry.get("changed_files", [])}})
        broadcast_event({"event": "history-updated"})
        self._serve_json({"ok": True, "id": entry_id})

    def _serve_events(self) -> None:
        event_queue: queue.Queue = queue.Queue()
        EVENT_LISTENERS.add(event_queue)

        self.send_response(HTTPStatus.OK)
        self._send_cors_headers()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()

            while True:
                try:
                    payload = event_queue.get(timeout=20)
                    event_name = payload.get("event", "message")
                    data = payload.get("data", {})
                    self.wfile.write(f"event: {event_name}\n".encode("utf-8"))
                    self.wfile.write(f"data: {json.dumps(data)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            EVENT_LISTENERS.discard(event_queue)

    def _serve_json(self, payload: dict | list) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict | None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid JSON body")
            return None

    def _send_event(self, payload: dict) -> None:
        self.wfile.write((json.dumps(payload) + "\n").encode("utf-8"))
        self.wfile.flush()

    def _send_cors_headers(self) -> None:
        origin = os.environ.get("APP_ORIGIN", "http://127.0.0.1:4173")
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")


def build_chat_result(message: str, conversation: list[dict], config: dict) -> ChatResult:
    api_key = os.environ.get("AI_API_KEY")
    if not api_key:
        raise RuntimeError("AI_API_KEY is not set")

    endpoint = os.environ.get("AI_API_ENDPOINT", "https://aiberm.com/v1/chat/completions")
    model = os.environ.get("AI_MODEL", "claude-opus-4-6-thinking")

    condensed_history = [
        {"role": item.get("role", "user"), "content": str(item.get("content", ""))}
        for item in conversation[-6:]
        if item.get("content")
    ]
    editable_files = get_editable_files()
    source_snapshot = {
        file_name: path.read_text(encoding="utf-8")
        for file_name, path in editable_files.items()
    }

    prompt = textwrap.dedent(
        f"""
        You are editing a live Snake game's repository files and runtime config.
        Return JSON only with this exact shape:
        {{
          "reply": "short plain-language response",
          "summary": "very short history summary",
          "patch": {{
            "theme": {{
              "bg": "#hex",
              "panel": "#hex",
              "border": "#hex",
              "grid": "#hex",
              "cell": "#hex",
              "snake": "#hex",
              "snakeHead": "#hex",
              "food": "#hex",
              "text": "#hex",
              "muted": "#hex"
            }},
            "gameplay": {{
              "tickMs": 140
            }},
            "copy": {{
              "helpText": "text"
            }}
          }},
          "fileEdits": [
            {{
              "file": "styles.css",
              "action": "replace",
              "find": "exact existing snippet",
              "replace": "replacement snippet"
            }},
            {{
              "file": "styles.css",
              "action": "rewrite",
              "content": "full file content"
            }}
          ]
        }}

        Rules:
        - Only include fields you want to change.
        - Prefer source file edits when the user asks for code or design changes.
        - Keep the UI readable.
        - Prefer small targeted edits, but you may rewrite an entire file when needed.
        - For action="replace", find must match an exact existing snippet from the source snapshot.
        - For action="rewrite", content must be the complete new file content.
        - Only edit files that already exist in the source snapshot.
        - If the request is unsupported, leave patch and fileEdits empty and explain why in reply.
        - You may edit HTML, CSS, JS, Python, JSON, and Markdown files in the repo.
        - Keep the Snake game playable unless the user explicitly asks to change gameplay.
        - Do not propose code blocks or markdown.

        Current config:
        {json.dumps(config, ensure_ascii=False)}

        Source snapshot:
        {json.dumps(source_snapshot, ensure_ascii=False)}

        Recent conversation:
        {json.dumps(condensed_history, ensure_ascii=False)}

        User request:
        {message}
        """
    ).strip()

    body = json.dumps(
        {
            "model": model,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a repository editing assistant. "
                        "Reply with valid JSON only. "
                        "No markdown, no code fences, no commentary outside JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(detail) from error

    parsed = json.loads(extract_chat_content(payload))
    return ChatResult(
        reply=parsed["reply"],
        summary=parsed.get("summary", parsed["reply"]),
        patch=parsed["patch"],
        source="aiberm",
        file_edits=parsed["fileEdits"],
    )


def ensure_config_file() -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        save_runtime_config(DEFAULT_CONFIG)


def ensure_history_store() -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    if not HISTORY_PATH.exists():
        HISTORY_PATH.write_text("[]\n", encoding="utf-8")


def load_runtime_config() -> dict:
    ensure_config_file()
    with CONFIG_LOCK:
        with CONFIG_PATH.open("r", encoding="utf-8") as file:
            return json.load(file)


def save_runtime_config(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_LOCK:
        with CONFIG_PATH.open("w", encoding="utf-8") as file:
            json.dump(config, file, ensure_ascii=False, indent=2)
            file.write("\n")


def load_history() -> list[dict]:
    ensure_history_store()
    with HISTORY_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return data if isinstance(data, list) else []


def save_history(entries: list[dict]) -> None:
    ensure_history_store()
    with HISTORY_PATH.open("w", encoding="utf-8") as file:
        json.dump(entries[:50], file, ensure_ascii=False, indent=2)
        file.write("\n")


def get_history_entry(entry_id: str) -> dict | None:
    for entry in load_history():
        if entry.get("id") == entry_id:
            return entry
    return None


def create_history_entry(
    task_id: str | None,
    prompt: str,
    summary: str,
    reply: str,
    source: str,
    changed_files: list[str],
    config_changed: bool,
    branch_from_entry_id: str | None,
) -> str:
    ensure_history_store()
    entry_id = str(time.time_ns())
    branch_entry = get_history_entry(branch_from_entry_id) if branch_from_entry_id else None
    snapshot = {
        "config": load_runtime_config(),
        "files": {
            path: file_path.read_text(encoding="utf-8")
            for path, file_path in get_editable_files().items()
        },
    }
    (SNAPSHOT_DIR / f"{entry_id}.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    history = load_history()
    history.insert(
        0,
        {
            "id": entry_id,
            "task_id": task_id or f"task-{entry_id}",
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "prompt": prompt,
            "summary": summary,
            "reply": reply,
            "source": source,
            "changed_files": changed_files,
            "config_changed": config_changed,
            "branch_from_entry_id": branch_from_entry_id,
            "branch_from_task_id": branch_entry.get("task_id") if branch_entry else None,
        },
    )
    save_history(history)
    trim_snapshots({entry["id"] for entry in history})
    return entry_id


def restore_snapshot(entry_id: str) -> None:
    snapshot_path = SNAPSHOT_DIR / f"{entry_id}.json"
    if not snapshot_path.exists():
        raise FileNotFoundError(entry_id)

    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    for relative_path, content in snapshot.get("files", {}).items():
        target = WORKSPACE_ROOT / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    config = snapshot.get("config")
    if isinstance(config, dict):
        save_runtime_config(config)


def trim_snapshots(valid_ids: set[str]) -> None:
    ensure_history_store()
    for path in SNAPSHOT_DIR.glob("*.json"):
        if path.stem not in valid_ids:
            path.unlink(missing_ok=True)


def merge_patch(config: dict, patch: dict) -> dict:
    merged = json.loads(json.dumps(config))
    for key in ("theme", "gameplay", "copy"):
        if key in patch and isinstance(patch[key], dict):
            merged.setdefault(key, {})
            merged[key].update(patch[key])
    return merged


def build_progress_events(result: ChatResult, changed_files: list[str], config_changed: bool) -> list[dict]:
    events: list[dict] = []
    config_sections = sorted(
        key for key, value in result.patch.items() if isinstance(value, dict) and value
    )

    events.append(
        phase_event(
            "planning",
            "Planning",
            files=changed_files,
            configSections=config_sections,
        )
    )

    if changed_files:
        events.append(
            phase_event(
                "editing-files",
                "Editing Files",
                files=changed_files,
                count=len(changed_files),
            )
        )

    if config_changed:
        events.append(
            phase_event(
                "updating-config",
                "Updating Config",
                configSections=config_sections,
            )
        )

    if changed_files or config_changed:
        events.append(
            phase_event(
                "reloading-app",
                "Reloading App",
                files=changed_files,
                configSections=config_sections,
            )
        )

    return events


def broadcast_event(payload: dict) -> None:
    for listener in list(EVENT_LISTENERS):
        listener.put(payload)


def get_changed_files(file_edits: list[dict]) -> list[str]:
    changed_files: list[str] = []
    editable_files = get_editable_files()

    for edit in file_edits:
        file_name = edit.get("file")
        action = edit.get("action", "replace")
        find_text = edit.get("find")
        replace_text = edit.get("replace")
        content = edit.get("content")

        if file_name not in editable_files:
            continue

        source = editable_files[file_name].read_text(encoding="utf-8")
        if action == "rewrite":
            if not isinstance(content, str) or content == source:
                continue
        else:
            if not isinstance(find_text, str) or not isinstance(replace_text, str):
                continue
            if source.count(find_text) != 1:
                continue
            if source.replace(find_text, replace_text, 1) == source:
                continue

        if file_name not in changed_files:
            changed_files.append(file_name)

    return changed_files


def apply_source_edits(file_edits: list[dict]) -> list[str]:
    changed_files: list[str] = []
    editable_files = get_editable_files()

    for edit in file_edits:
        file_name = edit.get("file")
        action = edit.get("action", "replace")
        find_text = edit.get("find")
        replace_text = edit.get("replace")
        content = edit.get("content")

        if file_name not in editable_files:
            continue

        path = editable_files[file_name]
        source = path.read_text(encoding="utf-8")
        if action == "rewrite":
            if not isinstance(content, str) or content == source:
                continue
            updated = content
        else:
            if not isinstance(find_text, str) or not isinstance(replace_text, str):
                continue
            if source.count(find_text) != 1:
                continue
            updated = source.replace(find_text, replace_text, 1)

        if updated == source:
            continue

        path.write_text(updated, encoding="utf-8")
        if file_name not in changed_files:
            changed_files.append(file_name)

    return changed_files


def get_editable_files() -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in WORKSPACE_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path == CONFIG_PATH:
            continue
        if any(part in BLOCKED_PATH_PARTS for part in path.parts):
            continue
        if path.suffix not in EDITABLE_SUFFIXES:
            continue
        files[path.relative_to(WORKSPACE_ROOT).as_posix()] = path
    return files


def sanitize_result(message: str, result: ChatResult) -> ChatResult:
    sanitized_patch = json.loads(json.dumps(result.patch))
    if not allows_gameplay_change(message.lower()):
        sanitized_patch.pop("gameplay", None)
    return ChatResult(
        reply=result.reply,
        summary=result.summary,
        patch=sanitized_patch,
        source=result.source,
        file_edits=result.file_edits,
    )


def allows_gameplay_change(message: str) -> bool:
    keywords = (
        "speed",
        "faster",
        "slower",
        "gameplay",
        "difficulty",
        "tick",
        "move faster",
        "move slower",
        "速度",
        "更快",
        "更慢",
        "难度",
    )
    return any(keyword in message for keyword in keywords)


def load_env_file() -> None:
    if not ENV_PATH.exists():
        return
    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        os.environ.setdefault(key, value)


def extract_chat_content(payload: dict) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError(f"Unexpected response shape: {json.dumps(payload)[:500]}")
    message = choices[0].get("message", {})
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
        combined = "".join(text_parts).strip()
        if combined:
            return combined
    raise RuntimeError(f"Unexpected message content: {json.dumps(message)[:500]}")


def chunk_text(text: str) -> list[str]:
    if not text:
        return [""]
    return re.findall(r"\S+\s*", text) or [text]


def run() -> None:
    load_env_file()
    port = int(os.environ.get("SPARK_PORT", "5050"))
    server = ThreadingHTTPServer(("127.0.0.1", port), SparkHandler)
    print(f"Serving Spark on http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
