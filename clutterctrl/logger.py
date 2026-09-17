import os
import uuid
from datetime import datetime

from . import config

LOG_DIR = config.LOG_DIR


def prune_old_logs(max_files=None):
    """Keep only the most recent N log files to manage disk usage."""
    limit = max_files if max_files is not None else getattr(config, "MAX_LOG_FILES", 100)
    if limit <= 0 or not os.path.isdir(LOG_DIR):
        return

    log_files = []
    for fname in os.listdir(LOG_DIR):
        if fname.endswith(".log"):
            fpath = os.path.join(LOG_DIR, fname)
            try:
                log_files.append((fpath, os.path.getmtime(fpath)))
            except OSError:
                pass

    if len(log_files) > limit:
        log_files.sort(key=lambda item: item[1])
        excess = len(log_files) - limit
        for fpath, _ in log_files[:excess]:
            try:
                os.remove(fpath)
            except OSError:
                pass


def start_log(target_dir: str = "", deep: bool = False, mode: str = "clean", run_id: str = None) -> str:
    """
    Create a unique, dedicated timestamped .log file for this specific run.
    Writes run metadata header and returns the log file path.
    """
    os.makedirs(LOG_DIR, exist_ok=True)
    prune_old_logs()

    if not run_id:
        timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        run_id = f"run_{timestamp_str}_{uuid.uuid4().hex[:6]}"

    log_filename = (run_id + ".log") if not run_id.endswith(".log") else run_id
    log_path = os.path.join(LOG_DIR, log_filename)

    with open(log_path, "w", encoding="utf-8") as log_file:
        log_file.write(f"Run ID: {run_id}\n")
        log_file.write(f"Run started: {datetime.now().isoformat()}\n")
        if target_dir:
            log_file.write(f"Target: {target_dir}\n")
        log_file.write(f"Deep Scan: {deep}\n")
        log_file.write(f"Mode: {mode}\n")
        log_file.write("Status: ACTIVE\n\n")
        log_file.write("--- OPERATIONS ---\n")

    return log_path


def write_log(log_path: str, message: str):
    """Append a single line to the run's unique log file."""
    if not log_path:
        return
    try:
        with open(log_path, "a", encoding="utf-8") as log_file:
            log_file.write(f"{message}\n")
    except OSError:
        pass