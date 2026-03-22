# Spark

`Spark` is a standalone AI editing service for local apps and prototypes.

This repo currently includes one example app:
- `examples/snake/`
  A minimal Snake game wired to Spark for live edits, history, and rollback.

## Architecture

- `spark/server.py`
  Runs the Spark service for chat, code edits, history, and rollback.
- `examples/snake/app_server.py`
  Serves the Snake example as a static app.
- `examples/snake/src/`
  Frontend game logic and UI behavior for the example.
- `examples/snake/runtime/`
  Runtime config, history index, and snapshots for the example.

## Project Layout

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
│   ├── .env
│   └── server.py
└── tests/
```

## Requirements

- Python 3.14+
- Network access from the Spark service
- A valid API key configured in `spark/.env`

## Quick Start

Start the app server:

```bash
cd /Users/carl/Desktop/project/SparkFlow
python3 examples/snake/app_server.py
```

Start Spark in a second terminal:

```bash
cd /Users/carl/Desktop/project/SparkFlow
python3 spark/server.py
```

Open:

- Snake example: [http://127.0.0.1:4173/](http://127.0.0.1:4173/)
- Spark API: `http://127.0.0.1:5050`

## Tests

Run the repo test suite:

```bash
cd /Users/carl/Desktop/project/SparkFlow
python3 -m unittest discover -s tests -v
```

The suite covers:

- Spark backend unit tests for progress events, history snapshots, and branch metadata
- browser-facing smoke tests for the app HTML, Spark API, event stream, and chat streaming contract

## Configuration

Snake example frontend connection target:

- `examples/snake/app-config.json`
  - `sparkBaseUrl`

Spark environment:

- `spark/.env`
  - `AI_API_ENDPOINT`
  - `AI_API_KEY`
  - `AI_MODEL`
  - `SPARK_PORT`
  - `APP_ORIGIN`

## Development Notes

- Spark and the example app are intentionally separated.
- The example app does not edit files directly.
- Spark owns source edits, history, snapshots, and rollback.
- Example rollback snapshots are stored in `examples/snake/runtime/snapshots/`.

## Manual Verification

- Open the Snake example and confirm the game still plays normally.
- Open the floating Spark panel and send a UI change request.
- Confirm the page reloads and chat history remains visible.
- Check that the History timeline shows the new change.
- Click `Rollback` on a timeline item and confirm the previous version returns.

## Release Checklist

- Update `README.md` if the API contract changes.
- Verify `spark/.env.example` matches required runtime configuration.
- Test `examples/snake/app_server.py` and `spark/server.py` independently.
- Confirm cross-origin requests still work between the example app and Spark.
- Confirm at least one edit and one rollback work end-to-end.
- Review any generated snapshots in `examples/snake/runtime/snapshots/`.

## License

MIT
