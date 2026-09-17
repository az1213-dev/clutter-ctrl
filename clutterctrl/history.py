import os
import uuid
from datetime import datetime
from shutil import move
from typing import Optional, List, Dict, Any

from . import config
from . import helpers
from .logger import LOG_DIR, start_log, write_log

HISTORY_DIR = LOG_DIR


def get_log_path(run_id: str) -> str:
    """Find the path to the unique log file corresponding to a run_id."""
    if not run_id:
        return ""

    safe_run_id = os.path.basename(run_id)
    if safe_run_id.endswith(".log"):
        base_name = safe_run_id
    else:
        base_name = f"{safe_run_id}.log" if safe_run_id.startswith("run_") else f"run_{safe_run_id}.log"

    direct_path = os.path.join(LOG_DIR, base_name)
    if os.path.isfile(direct_path):
        return direct_path

    # Search headers in all .log files in LOG_DIR
    if os.path.isdir(LOG_DIR):
        for fname in os.listdir(LOG_DIR):
            if fname.endswith(".log"):
                candidate = os.path.join(LOG_DIR, fname)
                try:
                    with open(candidate, "r", encoding="utf-8", errors="replace") as f:
                        for _ in range(10):
                            line = f.readline()
                            if not line:
                                break
                            if line.startswith("Run ID:") and safe_run_id in line:
                                return candidate
                except OSError:
                    continue

    return direct_path


def start_transaction(target_dir: str = "", deep: bool = False, mode: str = "clean", run_id: Optional[str] = None) -> str:
    """
    Start a new run by creating a unique dedicated log file for this run.
    Returns the unique run_id.
    """
    if not run_id:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        run_id = f"run_{timestamp}_{uuid.uuid4().hex[:6]}"

    start_log(target_dir=target_dir, deep=deep, mode=mode, run_id=run_id)
    return run_id


def record_move(run_id: str, src_path: str, dest_path: str, category: Optional[str] = None, file_size: int = 0, log_path: Optional[str] = None):
    """Append a moved file record to the run's unique log file."""
    path = log_path or get_log_path(run_id)
    if not path or not os.path.exists(path):
        return

    if not category:
        _, ext = os.path.splitext(src_path)
        category = helpers.get_category(ext)

    entry = f"MOVED: {src_path} -> {dest_path} | Category: {category} | Size: {file_size}"
    write_log(path, entry)


def record_removed_dir(run_id: str, dirpath: str, log_path: Optional[str] = None):
    """Append a removed empty folder to the run's unique log file."""
    path = log_path or get_log_path(run_id)
    if not path or not os.path.exists(path):
        return

    entry = f"REMOVED EMPTY FOLDER: {dirpath}"
    write_log(path, entry)


def finish_transaction(run_id: str, counts: Optional[Dict[str, int]] = None, total_bytes: Optional[int] = None, log_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Finalize summary and metrics inside the run's unique log file."""
    path = log_path or get_log_path(run_id)
    if not path or not os.path.exists(path):
        return None

    summary_lines = ["\n--- SUMMARY ---"]
    if counts:
        total_files = sum(counts.values())
        summary_lines.append(f"Total files moved: {total_files}")
        for cat, cnt in counts.items():
            if cnt > 0:
                summary_lines.append(f"{cat}: {cnt}")
    if total_bytes is not None:
        summary_lines.append(f"Total bytes: {total_bytes}")

    summary_lines.append(f"Run completed: {datetime.now().isoformat()}")
    summary_lines.append("Status: COMPLETED\n")
    write_log(path, "\n".join(summary_lines))

    return get_transaction(run_id)


def parse_log_file(filepath: str) -> Optional[Dict[str, Any]]:
    """Parse a single unique run .log file into a structured transaction dict."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return None

    filename = os.path.basename(filepath)
    run_id = os.path.splitext(filename)[0]

    timestamp = None
    target_dir = ""
    deep = False
    mode = "clean"
    status = "COMPLETED"
    undone = False
    undone_at = None
    total_bytes = 0
    moves = []
    removed_dirs = []
    categories = {cat: 0 for cat in config.CATEGORY_ORDER}
    category_bytes = {cat: 0 for cat in config.CATEGORY_ORDER}

    for line in content.splitlines():
        line_str = line.strip()
        if line_str.startswith("Run ID:"):
            run_id = line_str.split("Run ID:", 1)[1].strip()
        elif line_str.startswith("Run started:"):
            timestamp = line_str.split("Run started:", 1)[1].strip()
        elif line_str.startswith("Target:"):
            target_val = line_str.split("Target:", 1)[1].strip()
            if "(deep scan)" in target_val.lower():
                deep = True
                target_dir = target_val.replace("(deep scan)", "").replace("(Deep Scan)", "").strip()
            else:
                target_dir = target_val
        elif line_str.startswith("Deep Scan:"):
            deep = line_str.split("Deep Scan:", 1)[1].strip().lower() in ("true", "1", "yes")
        elif line_str.startswith("Mode:"):
            mode = line_str.split("Mode:", 1)[1].strip()
        elif line_str.startswith("Status:"):
            st_val = line_str.split("Status:", 1)[1].strip()
            if "UNDONE" in st_val.upper():
                undone = True
                status = "UNDONE"
            else:
                status = st_val
        elif line_str.startswith("MOVED:"):
            move_body = line_str.split("MOVED:", 1)[1].strip()
            # Check if extra metadata is present: src -> dest | Category: ... | Size: ...
            file_size = 0
            category = None
            if " | " in move_body:
                parts = move_body.split(" | ")
                path_part = parts[0]
                for p in parts[1:]:
                    if p.startswith("Category:"):
                        category = p.split("Category:", 1)[1].strip()
                    elif p.startswith("Size:"):
                        try:
                            file_size = int(p.split("Size:", 1)[1].strip())
                        except ValueError:
                            pass
            else:
                path_part = move_body

            if "->" in path_part:
                src, dest = path_part.split("->", 1)
                src = src.strip()
                dest = dest.strip()
                if not category:
                    _, ext = os.path.splitext(src)
                    category = helpers.get_category(ext)

                total_bytes += file_size
                categories[category] = categories.get(category, 0) + 1
                category_bytes[category] = category_bytes.get(category, 0) + file_size
                moves.append({
                    "id": len(moves) + 1,
                    "src": src,
                    "dest": dest,
                    "category": category,
                    "size": file_size,
                    "size_formatted": helpers.format_bytes(file_size),
                    "time": timestamp
                })
        elif line_str.startswith("REMOVED EMPTY FOLDER:"):
            folder = line_str.split("REMOVED EMPTY FOLDER:", 1)[1].strip()
            removed_dirs.append(folder)
        elif line_str.startswith("UNDONE:"):
            undone = True
            undone_at = line_str.split("UNDONE:", 1)[1].strip()
            status = "UNDONE"
        elif line_str.startswith("STATUS: UNDONE"):
            undone = True
            status = "UNDONE"
            if "at" in line_str:
                undone_at = line_str.split("at", 1)[1].strip()

    if not timestamp:
        try:
            mtime = os.path.getmtime(filepath)
            timestamp = datetime.fromtimestamp(mtime).isoformat()
        except OSError:
            timestamp = datetime.now().isoformat()

    return {
        "run_id": run_id,
        "timestamp": timestamp,
        "target_dir": target_dir,
        "deep": deep,
        "mode": mode,
        "total_files": len(moves),
        "total_bytes": total_bytes,
        "total_bytes_formatted": helpers.format_bytes(total_bytes),
        "categories": categories,
        "category_bytes": category_bytes,
        "moves": moves,
        "removed_dirs": removed_dirs,
        "undone": undone,
        "undone_at": undone_at,
        "status": status,
        "log_path": filepath
    }


def get_all_history(limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    """Return all past transactions parsed from unique per-run log files, newest first."""
    if not os.path.isdir(LOG_DIR):
        return []

    history_list = []
    for fname in os.listdir(LOG_DIR):
        if fname.endswith(".log"):
            fpath = os.path.join(LOG_DIR, fname)
            record = parse_log_file(fpath)
            if record and (record["total_files"] > 0 or record["moves"] or record["target_dir"]):
                history_list.append(record)

    # Sort newest first
    history_list.sort(key=lambda r: str(r.get("timestamp", "")), reverse=True)
    return history_list[offset: offset + limit]


def get_transaction(run_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve a single transaction record from its unique log file by ID."""
    path = get_log_path(run_id)
    if os.path.isfile(path):
        return parse_log_file(path)
    return None


def undo_run(run_id: str) -> Dict[str, Any]:
    """
    Reverse the moves recorded in a run's unique log file.
    Moves each file from 'dest' back to 'src' in reverse chronological order.
    Appends an UNDONE status marker to the unique log file.
    """
    target_item = get_transaction(run_id)
    if not target_item:
        return {
            "success": False,
            "message": f"Run ID '{run_id}' not found in logs.",
            "restored": 0,
            "total_attempted": 0,
            "errors": []
        }

    if target_item.get("undone"):
        return {
            "success": False,
            "message": f"Run ID '{run_id}' was already undone.",
            "restored": 0,
            "total_attempted": 0,
            "errors": []
        }

    moves_list = target_item.get("moves", [])
    restored = 0
    errors = []

    for m in reversed(moves_list):
        src = m["src"]
        dest = m["dest"]

        if not os.path.exists(dest):
            errors.append(f"File at destination no longer exists: {dest}")
            continue

        try:
            parent_dir = os.path.dirname(src)
            helpers.ensure_dir(parent_dir)

            final_src = src
            if os.path.exists(src) and os.path.abspath(src) != os.path.abspath(dest):
                final_src = os.path.join(parent_dir, helpers.make_unique(parent_dir, os.path.basename(src)))

            move(dest, final_src)
            restored += 1
        except Exception as e:
            errors.append(f"Failed to restore {dest} -> {src}: {e}")

    # Mark the unique log file as undone
    log_path = target_item.get("log_path")
    if log_path and os.path.exists(log_path):
        undo_timestamp = datetime.now().isoformat()
        undo_block = [
            "\n--- UNDO STATUS ---",
            f"UNDONE: {undo_timestamp}",
            f"STATUS: UNDONE at {undo_timestamp}",
            f"Restored: {restored}/{len(moves_list)} files"
        ]
        if errors:
            undo_block.append("Errors encountered during rollback:")
            for err in errors:
                undo_block.append(f"  - {err}")
        write_log(log_path, "\n".join(undo_block))

    is_success = len(errors) == 0
    return {
        "success": is_success,
        "restored": restored,
        "total_attempted": len(moves_list),
        "errors": errors,
        "message": f"Restored {restored}/{len(moves_list)} files successfully." if is_success else f"Restored {restored}/{len(moves_list)} with {len(errors)} error(s)."
    }


def get_stats() -> Dict[str, Any]:
    """Calculate aggregate lifetime statistics from all unique per-run log files."""
    runs = get_all_history(limit=5000)
    total_runs = len(runs)
    active_files = sum(r["total_files"] for r in runs if not r["undone"])
    active_bytes = sum(r["total_bytes"] for r in runs if not r["undone"])
    lifetime_files = sum(r["total_files"] for r in runs)
    lifetime_bytes = sum(r["total_bytes"] for r in runs)
    total_undone = sum(1 for r in runs if r["undone"])

    category_counts = {}
    for r in runs:
        if not r["undone"]:
            run_bytes = r.get("category_bytes", {})
            for cat, cnt in r.get("categories", {}).items():
                if cnt > 0:
                    if cat not in category_counts:
                        category_counts[cat] = {"count": 0, "bytes": 0}
                    category_counts[cat]["count"] += cnt
                    category_counts[cat]["bytes"] += run_bytes.get(cat, 0)

    for cat_data in category_counts.values():
        cat_data["bytes_formatted"] = helpers.format_bytes(cat_data["bytes"])

    return {
        "total_runs": total_runs,
        "total_files_organized": active_files,
        "total_bytes_organized": active_bytes,
        "total_bytes_formatted": helpers.format_bytes(active_bytes),
        "lifetime_files_moved": lifetime_files,
        "lifetime_bytes_moved": lifetime_bytes,
        "total_undone_runs": total_undone,
        "categories": category_counts,
        "log_dir": LOG_DIR,
        "total_log_files": len([f for f in os.listdir(LOG_DIR) if f.endswith(".log")]) if os.path.isdir(LOG_DIR) else 0
    }
