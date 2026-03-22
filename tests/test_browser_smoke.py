from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.request
from contextlib import contextmanager
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_url(url: str, timeout: float = 8.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5):
                return
        except Exception:
            time.sleep(0.1)
    raise AssertionError(f"Timed out waiting for {url}")


@contextmanager
def run_server(command: list[str], env: dict[str, str]):
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        yield process
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


class BrowserSmokeTests(unittest.TestCase):
    def test_app_and_spark_http_contracts(self) -> None:
        app_port = find_free_port()
        spark_port = find_free_port()
        app_url = f"http://127.0.0.1:{app_port}"
        spark_url = f"http://127.0.0.1:{spark_port}"

        app_env = os.environ.copy()
        app_env["APP_PORT"] = str(app_port)

        spark_env = os.environ.copy()
        spark_env["SPARK_PORT"] = str(spark_port)
        spark_env["APP_ORIGIN"] = app_url
        spark_env["AI_API_KEY"] = ""

        with run_server([sys.executable, "examples/snake/app_server.py"], app_env), run_server(
            [sys.executable, "spark/server.py"], spark_env
        ):
            wait_for_url(f"{app_url}/")
            wait_for_url(f"{spark_url}/api/config")

            with urllib.request.urlopen(f"{app_url}/", timeout=3) as response:
                html = response.read().decode("utf-8")
            self.assertIn('id="spark-dock"', html)
            self.assertIn('id="history-list"', html)
            self.assertIn("Spark", html)

            with urllib.request.urlopen(f"{spark_url}/api/config", timeout=3) as response:
                config = json.loads(response.read().decode("utf-8"))
            self.assertIn("theme", config)
            self.assertIn("gameplay", config)

            with urllib.request.urlopen(f"{spark_url}/api/history", timeout=3) as response:
                history = json.loads(response.read().decode("utf-8"))
            self.assertIsInstance(history, list)

            with urllib.request.urlopen(f"{spark_url}/events", timeout=3) as response:
                self.assertEqual(response.headers.get_content_type(), "text/event-stream")
                first_line = response.readline().decode("utf-8").strip()
            self.assertEqual(first_line, ": connected")

            payload = json.dumps({"message": "test", "conversation": []}).encode("utf-8")
            request = urllib.request.Request(
                f"{spark_url}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                body = response.read().decode("utf-8")

            lines = [json.loads(line) for line in body.splitlines() if line.strip()]
            self.assertTrue(any(line.get("label") == "Missing API Key" for line in lines))
            self.assertTrue(any(line.get("type") == "done" for line in lines))


if __name__ == "__main__":
    unittest.main()
