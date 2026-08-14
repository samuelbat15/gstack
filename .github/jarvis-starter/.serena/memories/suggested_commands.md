All commands run from `jarvis-starter/` on Windows (PowerShell or Git Bash — both used interchangeably in this project's history).

- Run CLI: `python jarvis.py --text` (text mode) or `--gui` (Tkinter) or `--voice`.
- Run HTTP backend: `python server.py` (reads `.env`, `JARVIS_HOST`/`JARVIS_PORT`/`JARVIS_API_TOKEN`).
- Install deps: `python -m pip install -r requirements.txt` — use `python -m pip`, not bare `pip`, on this machine: `pip` resolves to a *different* Python install (Python 3.12) than the `python` on PATH (Anaconda 3.11), so bare `pip install` silently installs into the wrong interpreter.
- Full test suite: `python -m pytest -q` (fast, no real network/hardware calls — all external calls mocked at the seam functions, e.g. `voice._get_model`, `tts._get_client`, `vision.capture_photo`/`describe_image`, `gmail_client._get_service`).
- Single file: `python -m pytest tests/test_<name>.py -v`.
- Console Unicode output (emoji, accented chars) needs `PYTHONIOENCODING=utf-8` prefix on Windows or `print()` of non-ASCII text raises `UnicodeEncodeError` (cp1252 console default).