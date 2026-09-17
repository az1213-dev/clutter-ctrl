"""
ClutterCtrl
~~~~~~~~~~~

A lightweight terminal file organizer with dry-run previews,
per-run audit logs, and 1-click rollback.

Modules:
    config   - environment settings, paths, and category definitions
    helpers  - filesystem utilities (byte formatting, categorization, destination paths)
    cleaner  - core file-organizing logic (standard + deep scans)
    watcher  - background folder watcher using watchdog
    history  - per-run log parsing, undo/rollback and statistics
    logger   - log file creation and stream logger
    main     - CLI entry point and interactive menu
"""

__version__ = "1.0.1"
__app_name__ = "clutterctrl"