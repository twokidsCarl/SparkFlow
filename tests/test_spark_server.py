from __future__ import annotations

import json
import importlib.util
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPARK_SERVER_PATH = ROOT / "spark" / "server.py"
SPEC = importlib.util.spec_from_file_location("spark_server_for_tests", SPARK_SERVER_PATH)
spark_server = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = spark_server
SPEC.loader.exec_module(spark_server)


@contextmanager
def spark_workspace():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "runtime" / "snapshots").mkdir(parents=True, exist_ok=True)
        (root / "src").mkdir(parents=True, exist_ok=True)
        (root / "spark").mkdir(parents=True, exist_ok=True)
        (root / "__pycache__").mkdir(parents=True, exist_ok=True)
        (root / ".git").mkdir(parents=True, exist_ok=True)

        (root / "index.html").write_text("<!doctype html>\n", encoding="utf-8")
        (root / "styles.css").write_text("body { color: red; }\n", encoding="utf-8")
        (root / "README.md").write_text("# Spark\n", encoding="utf-8")
        (root / "src" / "main.js").write_text("console.log('spark');\n", encoding="utf-8")
        (root / "src" / "duplicate.js").write_text("repeat\nrepeat\n", encoding="utf-8")
        (root / "spark" / "ignore.py").write_text("print('blocked')\n", encoding="utf-8")
        (root / "__pycache__" / "ignore.py").write_text("print('blocked')\n", encoding="utf-8")
        (root / ".git" / "config").write_text("[core]\n", encoding="utf-8")
        (root / "runtime" / "ignored.json").write_text("{}\n", encoding="utf-8")

        config_path = root / "runtime" / "live-config.json"
        history_path = root / "runtime" / "history.json"
        snapshot_dir = root / "runtime" / "snapshots"

        with patch.multiple(
            spark_server,
            REPO_ROOT=root,
            WORKSPACE_ROOT=root,
            CONFIG_PATH=config_path,
            HISTORY_PATH=history_path,
            SNAPSHOT_DIR=snapshot_dir,
        ):
            spark_server.save_runtime_config(json.loads(json.dumps(spark_server.DEFAULT_CONFIG)))
            yield root


class SparkServerTests(unittest.TestCase):
    def test_build_progress_events_covers_planning_editing_config_and_reload(self) -> None:
        result = spark_server.ChatResult(
            reply="done",
            summary="updated theme",
            patch={
                "theme": {"bg": "#101010"},
                "copy": {"helpText": "Updated"},
            },
            source="test",
            file_edits=[{"file": "styles.css", "action": "replace"}],
        )

        events = spark_server.build_progress_events(result, ["styles.css", "src/main.js"], True)

        self.assertEqual(
            [event["phase"] for event in events],
            ["planning", "editing-files", "updating-config", "reloading-app"],
        )
        self.assertEqual(events[0]["configSections"], ["copy", "theme"])
        self.assertEqual(events[1]["files"], ["styles.css", "src/main.js"])

    def test_create_history_entry_tracks_branch_and_restore_snapshot(self) -> None:
        with spark_workspace() as root:
            entry_a = spark_server.create_history_entry(
                task_id="task-a",
                prompt="make it darker",
                summary="darkened theme",
                reply="Updated theme colors.",
                source="test",
                changed_files=["styles.css"],
                config_changed=False,
                branch_from_entry_id=None,
            )

            (root / "styles.css").write_text("body { color: blue; }\n", encoding="utf-8")

            spark_server.create_history_entry(
                task_id="task-b",
                prompt="branch from old version",
                summary="new branch",
                reply="Created a branch.",
                source="test",
                changed_files=["styles.css"],
                config_changed=False,
                branch_from_entry_id=entry_a,
            )

            history = spark_server.load_history()
            self.assertEqual(history[0]["branch_from_task_id"], "task-a")
            self.assertTrue((root / "runtime" / "snapshots" / f"{entry_a}.json").exists())

            spark_server.restore_snapshot(entry_a)
            restored = (root / "styles.css").read_text(encoding="utf-8")
            self.assertEqual(restored, "body { color: red; }\n")

    def test_get_editable_files_excludes_runtime_and_blocked_paths(self) -> None:
        with spark_workspace():
            editable_files = spark_server.get_editable_files()

        self.assertEqual(
            set(editable_files),
            {"README.md", "index.html", "src/duplicate.js", "src/main.js", "styles.css"},
        )

    def test_get_changed_files_ignores_invalid_and_duplicate_edits(self) -> None:
        with spark_workspace():
            changed_files = spark_server.get_changed_files(
                [
                    {
                        "file": "styles.css",
                        "action": "replace",
                        "find": "body { color: red; }\n",
                        "replace": "body { color: blue; }\n",
                    },
                    {
                        "file": "src/duplicate.js",
                        "action": "replace",
                        "find": "repeat\n",
                        "replace": "once\n",
                    },
                    {
                        "file": "README.md",
                        "action": "rewrite",
                        "content": "# Spark\nUpdated\n",
                    },
                    {
                        "file": "missing.js",
                        "action": "rewrite",
                        "content": "console.log('nope');\n",
                    },
                    {
                        "file": "styles.css",
                        "action": "replace",
                        "find": "body { color: red; }\n",
                        "replace": "body { color: blue; }\n",
                    },
                ]
            )

        self.assertEqual(changed_files, ["styles.css", "README.md"])

    def test_apply_source_edits_updates_only_valid_edits(self) -> None:
        with spark_workspace() as root:
            changed_files = spark_server.apply_source_edits(
                [
                    {
                        "file": "styles.css",
                        "action": "replace",
                        "find": "body { color: red; }\n",
                        "replace": "body { color: blue; }\n",
                    },
                    {
                        "file": "README.md",
                        "action": "rewrite",
                        "content": "# Spark\nUpdated\n",
                    },
                    {
                        "file": "src/main.js",
                        "action": "replace",
                        "find": "missing snippet",
                        "replace": "console.log('changed');\n",
                    },
                ]
            )

            self.assertEqual(changed_files, ["styles.css", "README.md"])
            self.assertEqual((root / "styles.css").read_text(encoding="utf-8"), "body { color: blue; }\n")
            self.assertEqual((root / "README.md").read_text(encoding="utf-8"), "# Spark\nUpdated\n")
            self.assertEqual((root / "src" / "main.js").read_text(encoding="utf-8"), "console.log('spark');\n")

    def test_merge_patch_updates_supported_sections_only(self) -> None:
        merged = spark_server.merge_patch(
            spark_server.DEFAULT_CONFIG,
            {
                "theme": {"bg": "#101010"},
                "copy": {"helpText": "Updated"},
                "unsupported": {"ignored": True},
            },
        )

        self.assertEqual(merged["theme"]["bg"], "#101010")
        self.assertEqual(merged["copy"]["helpText"], "Updated")
        self.assertNotIn("unsupported", merged)
        self.assertEqual(spark_server.DEFAULT_CONFIG["theme"]["bg"], "#f5f1e8")

    def test_sanitize_result_strips_gameplay_patch_without_gameplay_request(self) -> None:
        result = spark_server.ChatResult(
            reply="Updated visuals.",
            summary="updated visuals",
            patch={"theme": {"bg": "#111111"}, "gameplay": {"tickMs": 90}},
            source="test",
            file_edits=[],
        )

        sanitized = spark_server.sanitize_result("make the board darker", result)

        self.assertEqual(sanitized.patch, {"theme": {"bg": "#111111"}})

    def test_sanitize_result_keeps_gameplay_patch_for_speed_request(self) -> None:
        result = spark_server.ChatResult(
            reply="Made it faster.",
            summary="faster snake",
            patch={"gameplay": {"tickMs": 90}},
            source="test",
            file_edits=[],
        )

        sanitized = spark_server.sanitize_result("make the snake move faster", result)

        self.assertEqual(sanitized.patch, {"gameplay": {"tickMs": 90}})

    def test_extract_chat_content_supports_string_and_text_parts(self) -> None:
        string_payload = {"choices": [{"message": {"content": '{"reply":"ok","patch":{},"fileEdits":[]}'}}]}
        list_payload = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": '{"reply":"ok"'},
                            {"type": "image", "image_url": "ignored"},
                            {"type": "text", "text": ',"patch":{},"fileEdits":[]}'},
                        ]
                    }
                }
            ]
        }

        self.assertEqual(
            spark_server.extract_chat_content(string_payload),
            '{"reply":"ok","patch":{},"fileEdits":[]}',
        )
        self.assertEqual(
            spark_server.extract_chat_content(list_payload),
            '{"reply":"ok","patch":{},"fileEdits":[]}',
        )

    def test_save_history_caps_entries_at_fifty(self) -> None:
        with spark_workspace():
            spark_server.save_history([{"id": str(index)} for index in range(60)])
            history = spark_server.load_history()

        self.assertEqual(len(history), 50)
        self.assertEqual(history[0]["id"], "0")
        self.assertEqual(history[-1]["id"], "49")


if __name__ == "__main__":
    unittest.main()
