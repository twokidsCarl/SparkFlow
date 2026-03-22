# SparkFlow

SparkFlow is a local AI editing workspace for small apps and prototypes.

It runs as two separate local services:

- the app you are editing
- the SparkFlow service that handles chat-driven edits, runtime config updates, history snapshots, branching, and rollback

This repository currently ships with one example app, a browser-based Snake game in [`examples/snake/`](examples/snake).

## What It Does

- Applies AI-generated source edits to an existing local app
- Streams progress and assistant output back to the browser
- Persists change history with snapshots
- Supports rollback to earlier states
- Keeps app runtime config separate from source files

## Repository Layout

```text
.
├── examples/
│   └── snake/
│       ├── app-config.json
│       ├── app_server.py
│       ├── index.html
│       ├── runtime/
│       │   ├── history.json
│       │   ├── live-config.json
│       │   └── snapshots/
│       ├── src/
│       │   ├── liveConfig.js
│       │   ├── main.js
│       │   └── snakeLogic.js
│       └── styles.css
├── server.py
├── spark/
│   ├── .env.example
│   └── server.py
└── tests/
```

## Core Pieces

- [`spark/server.py`](spark/server.py)
  The SparkFlow backend. Exposes chat, config, history, rollback, and event-stream endpoints.
- [`examples/snake/app_server.py`](examples/snake/app_server.py)
  Static file server for the example app.
- [`examples/snake/src/main.js`](examples/snake/src/main.js)
  Game loop, Spark dock UI, history rendering, and rollback wiring.
- [`examples/snake/src/liveConfig.js`](examples/snake/src/liveConfig.js)
  Runtime config loading and CSS variable application.
- [`tests/`](tests)
  Unit tests and browser-level smoke tests.

## Requirements

- Python 3.14+
- Network access from the SparkFlow service to the configured AI endpoint
- A valid API key in `spark/.env`

Create `spark/.env` from [`spark/.env.example`](spark/.env.example) and fill in your credentials.

## Quick Start

Start the example app:

```bash
cd /Users/carl/Desktop/project/SparkFlow
python3 examples/snake/app_server.py
```

Start SparkFlow in another terminal:

```bash
cd /Users/carl/Desktop/project/SparkFlow
python3 spark/server.py
```

Open:

- App: [http://127.0.0.1:4173/](http://127.0.0.1:4173/)
- API: [http://127.0.0.1:5050/api/config](http://127.0.0.1:5050/api/config)

## API Surface

SparkFlow currently exposes:

- `GET /api/config`
- `GET /api/history`
- `GET /events`
- `POST /api/chat`
- `POST /api/rollback`

`/api/chat` streams newline-delimited JSON events so the frontend can render incremental assistant output and progress states.

## Configuration

Frontend app connection:

- [`examples/snake/app-config.json`](examples/snake/app-config.json)
  - `sparkBaseUrl`

SparkFlow environment variables:

- `AI_API_ENDPOINT`
- `AI_API_KEY`
- `AI_MODEL`
- `SPARK_PORT`
- `APP_ORIGIN`

## Tests

Run the full test suite:

```bash
cd /Users/carl/Desktop/project/SparkFlow
python3 -m unittest discover -s tests -v
```

Current coverage includes:

- history snapshot and restore behavior
- branch metadata persistence
- source edit validation and application
- config merge and gameplay guardrails
- chat response parsing
- app and SparkFlow HTTP smoke contracts

## Development Notes

- SparkFlow edits only files inside the example workspace that match supported suffixes.
- `runtime/` is treated as managed state, not editable source.
- Gameplay config changes are blocked unless the user explicitly asks for gameplay or speed changes.
- Rollback snapshots are stored in `examples/snake/runtime/snapshots/`.

## Manual Check

- Open the Snake app and confirm the game runs.
- Open the Spark dock and request a visual change.
- Confirm the UI updates and history remains visible after reload.
- Roll back from the history panel and confirm the earlier state returns.

## License

MIT
