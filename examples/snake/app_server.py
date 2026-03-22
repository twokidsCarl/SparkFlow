from __future__ import annotations

import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parent


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(APP_ROOT), **kwargs)


def run() -> None:
    port = int(os.environ.get("APP_PORT", "4173"))
    server = ThreadingHTTPServer(("127.0.0.1", port), AppHandler)
    print(f"Serving app on http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
