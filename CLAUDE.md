# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

ClutterCtrl is a pure-stdlib Python CLI (zero mandatory dependencies) that organizes cluttered folders by moving files into category subfolders (Images, Videos, Audio, Documents, etc.), based on extension. Every run writes a dedicated, human-readable `.log` file that doubles as the undo journal — there is no database; run history and rollback are both derived by parsing these log files. Package name on PyPI: `clutterctrl`. Entry point: `clutterctrl = "clutterctrl.main:main"`.

## Commands

```bash
# Install for development (editable, with dev + watcher extras)
pip install -e .[dev,watcher]

# Run the CLI without installing
python clutterctrl/main.py

# Run the full test suite
pytest -v

# Run a single test file / test
pytest tests/test_organizer.py -v
pytest tests/test_organizer.py::TestClassName::test_name -v

# Build distributables (sdist + wheel)
python -m build
twine check --strict dist/*
```

CI (`.github/workflows/ci.yml`) runs `pip install -e .[dev,watcher]` then `pytest -v` on Python 3.9–3.13 across Ubuntu/Windows/macOS. Release workflow (`.github/workflows/release.yml`) builds, checks with twine, creates a GitHub release, and publishes to PyPI via OIDC trusted publishing on `v*.*.*` tags.

There is no linter/formatter config in the repo (no ruff/black/flake8 config) — don't invent one unless asked.

## Architecture

All source lives in the `clutterctrl/` package (flat, no subpackages):

- **`main.py`** — argparse CLI + a Gemini-CLI-style interactive shell. Owns all `print()`/color output. Subcommands: `clean`, `scan` (dry-run), `watch`, `history`, `undo`, `stats`, `rules`, shared between direct CLI use and the shell via `build_parser()`/`dispatch()`. Also supports legacy flag-based invocation (`--target`, `--clean`, `--dry-run`, etc.) for backwards compatibility, and falls back to `interactive_shell()` when invoked with no args — a boxed 3D gradient banner, a `Commands` reference, and a live boxed input prompt that parses each typed line with the same argparse parser and executes it in a loop. Note the sys.path shim at the top of the file that lets it run both as `python clutterctrl/main.py` (direct script) and `python -m clutterctrl.main`.
- **`config.py`** — loads `categories.json` (extension → category mapping) into module-level globals (`CATEGORY_EXTENSIONS`, `CATEGORY_ORDER`, `MISC_CATEGORY`); `reload_categories()` lets callers hot-reload after editing the JSON. Also resolves standard user folders (Downloads, Desktop, etc.) and reads env vars (`CLUTTERCTRL_LOG_DIR`, `WATCHDOG_DEBOUNCE_SECONDS`, `MAX_LOG_FILES`).
- **`cleaner.py`** — the core engine: `process_directory()` (top-level scan) and `deep_scan_directory()` (recursive, also cleans up empty folders afterward via `cleanup_empty_dirs`/`preview_empty_dirs`). Both accept `dry_run`, `quiet`, and an optional `event_callback(event_dict)` for streaming progress events (this callback hook exists for a UI/websocket consumer even though no such consumer currently ships in this repo — preserve it when refactoring). Category folders (`is_category_folder`) are never descended into or deleted.
- **`history.py`** — the run-log persistence layer. `start_transaction`/`record_move`/`record_removed_dir`/`finish_transaction` write to a run's log file during a run; `parse_log_file`/`get_all_history`/`get_transaction`/`get_stats` re-derive structured data by parsing log files back out; `undo_run` reverses a run's moves in reverse chronological order and appends an `UNDONE` marker to that log file. **The log file IS the source of truth** — there is no separate index/database, so log format changes must stay backward-parseable.
- **`logger.py`** — low-level log file I/O (`start_log` writes the header block, `write_log` appends a line) plus log pruning (`prune_old_logs`, capped by `MAX_LOG_FILES`).
- **`watcher.py`** — background folder watcher built on `watchdog` (optional dependency, extras group `watcher`; degrades gracefully with `HAS_WATCHDOG = False` if not installed). `OrganizeEventHandler` debounces file-system events (`WATCHDOG_DEBOUNCE_SECONDS`) so partial/in-progress downloads (`.tmp`, `.crdownload`, `.part`, etc.) aren't moved prematurely, then reuses the same `history` module to log each auto-sorted file as its own mini-run. `WatcherManager` tracks active per-directory `Observer` instances so multiple watches can run concurrently.
- **`helpers.py`** — small stateless utilities: `get_category`/`get_dest` (extension → category/destination), `make_unique` (collision-safe renaming, e.g. `photo_1.png`), `format_bytes`, `ensure_dir`, drive/quick-location discovery (`get_available_drives`, `get_quick_locations`).
- **`categories.json`** — the actual extension-to-category data (`{"categories": {...}, "misc_category": "Misc"}`), packaged via `[tool.setuptools.package-data]` so it ships with the wheel. Edit this file, not hardcoded category lists in Python, to add/change extension mappings.

### Key invariants to preserve

- Run logs (`clutterctrl/logs/run_*.log`, path overridable via `CLUTTERCTRL_LOG_DIR`) are both the audit trail and the undo mechanism — `history.py` parses them back into transactions, so any change to the line formats written in `logger.py`/`history.py` (`MOVED: ...`, `REMOVED EMPTY FOLDER: ...`, `Status: ...`) must keep `parse_log_file` in sync or history/undo silently breaks.
- Files are never overwritten — `helpers.make_unique` must be called before any move into a destination folder.
- Deep scan and the watcher both use `is_category_folder` (from `cleaner.py`) to avoid ever recursing into or deleting the category folders they themselves create.
- `cleaner.py` functions are dual-purpose: they must work as plain synchronous calls (CLI, tests) and as event-emitting generators-via-callback (`event_callback`) for a potential UI/streaming consumer — don't remove the callback plumbing when touching this code.

## Recent history

The project used to include a web dashboard (Flask-style `test_api.py`/`test_db.py` tests remain as stale `.pyc` files in `tests/__pycache__` from before it was removed) and Flask deployment/security config; that deployment surface has been stripped out ("removed deployment: keep locally") and the project is now CLI-only, released to PyPI as `clutterctrl` v1.0.1 with an automated GitHub Actions release/publish pipeline. `event_callback` hooks throughout `cleaner.py`/`watcher.py` are a holdover from that dashboard and remain as the intended extension point if a UI is reintroduced.

## Known gaps / possible improvements

- `tests/__pycache__` still contains compiled test files (`test_api.cpython-313...pyc`, `test_db.cpython-313...pyc`) for tests that no longer exist in `tests/` — safe to ignore/clean, not indicative of missing source.
- No linter or formatter is configured; code style is manual/ad hoc (e.g. plain string concatenation with `+` rather than f-strings in several places).
- `history.parse_log_file` re-parses free-text log files with string matching on every read — fine at current scale, but a large `logs/` directory makes `history`, `stats`, and `undo` linearly slower since there's no index.
- `main.py`'s legacy flag-based arguments (`--target`, `--clean`, `--dry-run`, `--watch`, `--undo`, `--undo-last`) duplicate the newer subcommands and add branching complexity in `main()` — kept for backwards compatibility, not for new features.
