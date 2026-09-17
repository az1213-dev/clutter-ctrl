import os
import time
import threading
from os.path import splitext, join, isfile, dirname, basename
from shutil import move

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False
    class FileSystemEventHandler:
        pass
    Observer = None

from . import config
from .helpers import ensure_dir, make_unique, get_dest, get_category, format_bytes
from .cleaner import is_category_folder, is_inside_category_folder, resolve_subfolders
from . import history

IGNORE_EXTENSIONS = {".tmp", ".crdownload", ".part", ".download", ".partial", ".swp"}
IGNORE_PREFIXES = {"~$", ".", "#"}


class OrganizeEventHandler(FileSystemEventHandler):
    def __init__(self, watch_dir, deep=False, event_callback=None, debounce_secs=None, subfolders=None):
        super().__init__()
        self.watch_dir = os.path.abspath(os.path.normpath(watch_dir))
        self.deep = deep
        self.subfolders = resolve_subfolders(subfolders)
        self.event_callback = event_callback
        self.debounce_secs = debounce_secs or config.WATCHDOG_DEBOUNCE_SECONDS
        self._lock = threading.Lock()
        self._pending_files = {}
        self._stopped = False

    def stop(self):
        """Immediately cancel all pending debounce timers and block new incoming events."""
        with self._lock:
            self._stopped = True
            for timer in list(self._pending_files.values()):
                try:
                    timer.cancel()
                except Exception:
                    pass
            self._pending_files.clear()

    def on_created(self, event):
        if not self._stopped and not event.is_directory:
            self._handle_file(event.src_path)

    def on_moved(self, event):
        if not self._stopped and not event.is_directory:
            self._handle_file(event.dest_path)

    def on_modified(self, event):
        if not self._stopped and not event.is_directory:
            self._handle_file(event.src_path)

    def _handle_file(self, filepath):
        if self._stopped:
            return

        path = os.path.abspath(filepath)
        filename = basename(path)
        dirpath = dirname(path)

        parent_name = basename(dirpath)
        # Skip anything already living under one of our category folders - both the
        # folder itself and, with subfolders enabled, the extension folders inside it.
        if is_category_folder(parent_name) or is_inside_category_folder(dirpath, self.watch_dir):
            return

        if not self.deep and dirpath != self.watch_dir:
            return

        _, ext = splitext(filename)
        ext_lower = ext.lower()

        if not ext or ext_lower in IGNORE_EXTENSIONS:
            return

        if any(filename.startswith(p) for p in IGNORE_PREFIXES):
            return

        with self._lock:
            if self._stopped:
                return
            timer = self._pending_files.get(path)
            if timer:
                timer.cancel()
            t = threading.Timer(self.debounce_secs, self._process_single_file, args=[path])
            self._pending_files[path] = t
            t.start()

    def _process_single_file(self, filepath):
        with self._lock:
            self._pending_files.pop(filepath, None)
            if self._stopped:
                return

        if not isfile(filepath):
            return

        filename = basename(filepath)
        _, ext = splitext(filename)
        ext_lower = ext.lower()

        if ext_lower in IGNORE_EXTENSIONS:
            return

        category = get_category(ext_lower)
        dest_dir = get_dest(ext_lower, self.watch_dir, subfolders=self.subfolders)
        ensure_dir(dest_dir)

        try:
            file_size = os.path.getsize(filepath)
        except OSError:
            file_size = 0

        unique_name = make_unique(dest_dir, filename)
        final_dest_path = join(dest_dir, unique_name)

        run_id = history.start_transaction(self.watch_dir, deep=self.deep, mode="watchdog")
        try:
            if self._stopped:
                return

            move(filepath, final_dest_path)
            history.record_move(run_id, filepath, final_dest_path, category=category, file_size=file_size)
            history.finish_transaction(run_id, {category: 1}, total_bytes=file_size)

            file_info = {
                "name": filename,
                "src": filepath,
                "dest_path": final_dest_path,
                "category": category,
                "size": file_size,
                "size_formatted": format_bytes(file_size),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }

            if self.event_callback and not self._stopped:
                self.event_callback({
                    "type": "watchdog_organized",
                    "file": file_info,
                    "target_dir": self.watch_dir,
                    "run_id": run_id
                })
        except Exception as e:
            if self.event_callback and not self._stopped:
                self.event_callback({
                    "type": "watchdog_error",
                    "file": filename,
                    "error": str(e),
                    "target_dir": self.watch_dir
                })


class WatcherManager:
    def __init__(self):
        self._active_observers = {}
        self._lock = threading.Lock()

    def start(self, watch_dir, deep=False, event_callback=None, subfolders=None):
        if not HAS_WATCHDOG:
            return False, "Folder watching requires the 'watchdog' package. Install with: pip install watchdog (or pip install -e .[watcher])"

        watch_path = os.path.abspath(os.path.normpath(watch_dir.strip()))
        with self._lock:
            # Check normalized match against active observers
            for active_path in self._active_observers:
                if os.path.normcase(active_path) == os.path.normcase(watch_path):
                    return False, "Already watching: " + str(watch_path)

            if not os.path.isdir(watch_path):
                return False, "Directory does not exist: " + str(watch_path)

            handler = OrganizeEventHandler(watch_path, deep=deep, event_callback=event_callback, subfolders=subfolders)
            observer = Observer()
            observer.schedule(handler, watch_path, recursive=deep)
            observer.start()
            self._active_observers[watch_path] = {
                "observer": observer,
                "handler": handler,
                "deep": deep,
                "subfolders": handler.subfolders,
                "started_at": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            return True, "Started watching " + str(watch_path)

    def stop(self, watch_dir):
        raw_input = watch_dir.strip()
        watch_path = os.path.abspath(os.path.normpath(raw_input))
        with self._lock:
            target_key = None
            for active_path in list(self._active_observers.keys()):
                norm_active = os.path.normcase(os.path.abspath(os.path.normpath(active_path)))
                norm_target = os.path.normcase(watch_path)
                if norm_active == norm_target or active_path == raw_input:
                    target_key = active_path
                    break

            if not target_key:
                return False, "Not currently watching: " + str(watch_dir)

            info = self._active_observers.pop(target_key, None)
            if not info:
                return False, "Not currently watching: " + str(watch_dir)

            if "handler" in info and hasattr(info["handler"], "stop"):
                try:
                    info["handler"].stop()
                except Exception:
                    pass

            try:
                info["observer"].stop()
                info["observer"].join(timeout=2.0)
            except Exception:
                pass
            return True, "Stopped watching " + str(target_key)

    def stop_all(self):
        with self._lock:
            for path, info in list(self._active_observers.items()):
                if "handler" in info and hasattr(info["handler"], "stop"):
                    try:
                        info["handler"].stop()
                    except Exception:
                        pass
                try:
                    info["observer"].stop()
                    info["observer"].join(timeout=2.0)
                except Exception:
                    pass
            self._active_observers.clear()

    def list_active(self):
        with self._lock:
            return [
                {
                    "path": path,
                    "deep": info["deep"],
                    "subfolders": info.get("subfolders", False),
                    "started_at": info["started_at"]
                }
                for path, info in self._active_observers.items()
            ]


watcher_manager = WatcherManager()


