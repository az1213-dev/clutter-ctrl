import os
from os import scandir
from os.path import splitext, join
from shutil import move

from . import config
from .helpers import ensure_dir, make_unique, get_dest, get_category, format_bytes
from . import history
from .logger import write_log

def is_category_folder(name):
    """True if a folder name matches one of our own category folders
    (Images, Videos, Audio, Documents, Misc) - anywhere in the tree.
    Deep scan never descends into or removes these, since they're
    assumed to already be organized."""
    return name in config.CATEGORY_ORDER


def is_inside_category_folder(path, root):
    """True if any folder between root and path is one of our category folders.

    Category folders hold our own output - including the per-extension
    subfolders created with subfolders=True - so nothing under them may be
    descended into, moved again, or deleted as 'empty'.
    """
    try:
        rel = os.path.relpath(path, root)
    except ValueError:
        # Different drives on Windows: definitely not under root.
        return False

    if rel == os.curdir:
        return False

    return any(is_category_folder(part) for part in rel.split(os.sep))


def resolve_subfolders(subfolders):
    """None means 'use the configured default' (categories.json / env var)."""
    if subfolders is None:
        return bool(config.SUBFOLDERS_ENABLED)
    return bool(subfolders)


def process_directory(source_dir, dry_run=False, quiet=False, event_callback=None, subfolders=None):
    """
    Scan source_dir and sort files into category subfolders.

    dry_run=True       -> report what would happen, move nothing.
    quiet=True         -> suppress per-file console lines, only print final summary (Summary Only mode).
    event_callback     -> callable(event_dict) for real-time streaming (WebSockets/UI).
    subfolders         -> True/False to force per-extension subfolders inside each
                          category folder; None uses the configured default.

    Returns a dict with summary metrics and file details.
    """
    use_subfolders = resolve_subfolders(subfolders)
    mode = "Dry Run" if dry_run else "Cleaning"
    if quiet:
        mode = "Summary Only"

    if not quiet and event_callback is None:
        print(mode + ": Scanning " + source_dir)
        if dry_run:
            print("No files will be moved.")
        print("")

    counts = {category: 0 for category in config.CATEGORY_ORDER}
    sizes = {category: 0 for category in config.CATEGORY_ORDER}
    files_list = []

    log_path = None
    run_id = None
    if not dry_run:
        run_id = history.start_transaction(source_dir, deep=False, mode="clean")
        log_path = history.get_log_path(run_id)

    if event_callback:
        event_callback({
            "type": "start",
            "mode": mode,
            "target": source_dir,
            "deep": False,
            "dry_run": dry_run,
            "quiet": quiet,
            "run_id": run_id,
            "message": mode + ": Scanning " + source_dir
        })
        if dry_run and not quiet:
            event_callback({
                "type": "log",
                "text": "No files will be moved.",
                "color": "text-slate-400"
            })

    try:
        with scandir(source_dir) as entries:
            for entry in entries:
                if not entry.is_file():
                    continue

                _, ext = splitext(entry.name)
                if not ext:
                    continue

                try:
                    file_size = entry.stat().st_size
                except OSError:
                    file_size = 0

                category = get_category(ext)
                dest_dir = get_dest(ext, source_dir, subfolders=use_subfolders)
                dest_file_path = join(dest_dir, entry.name)

                counts[category] += 1
                sizes[category] += file_size

                file_info = {
                    "name": entry.name,
                    "src": entry.path,
                    "dest_dir": dest_dir,
                    "dest_path": dest_file_path,
                    "category": category,
                    "subcategory": os.path.basename(dest_dir) if use_subfolders else None,
                    "extension": ext,
                    "size": file_size,
                    "size_formatted": format_bytes(file_size),
                    "status": "pending"
                }

                if dry_run:
                    file_info["status"] = "would_move"
                    files_list.append(file_info)
                    if not quiet and event_callback is None:
                        print("Would move " + entry.name + " -> " + dest_dir)
                    if event_callback:
                        event_callback({
                            "type": "file_preview",
                            "file": file_info,
                            "counts": counts,
                            "sizes": sizes
                        })
                        if not quiet:
                            event_callback({
                                "type": "log",
                                "text": "Would move " + entry.name + " -> " + dest_dir,
                                "color": "text-sky-400"
                            })
                    continue

                ensure_dir(dest_dir)
                unique_name = make_unique(dest_dir, entry.name)
                final_dest_path = join(dest_dir, unique_name)
                file_info["dest_path"] = final_dest_path
                file_info["unique_name"] = unique_name

                try:
                    if not quiet and event_callback is None:
                        print("Moving " + entry.name + " -> " + dest_dir)

                    if event_callback:
                        event_callback({
                            "type": "file_moving",
                            "file": file_info
                        })

                    move(entry.path, final_dest_path)
                    file_info["status"] = "moved"
                    files_list.append(file_info)

                    if run_id:
                        history.record_move(run_id, entry.path, final_dest_path, category=category, file_size=file_size)

                    if event_callback:
                        event_callback({
                            "type": "file_moved",
                            "file": file_info,
                            "counts": counts,
                            "sizes": sizes,
                            "total_processed": len(files_list)
                        })
                        if not quiet:
                            event_callback({
                                "type": "log",
                                "text": "Moving " + entry.name + " -> " + dest_dir,
                                "color": "text-emerald-400"
                            })

                except Exception as e:
                    file_info["status"] = "error"
                    file_info["error"] = str(e)
                    files_list.append(file_info)
                    if not quiet and event_callback is None:
                        print("Error moving file: " + entry.name + " | " + str(e))
                    if log_path:
                        write_log(log_path, "ERROR: " + entry.name + " | " + str(e))
                    if event_callback:
                        event_callback({
                            "type": "error",
                            "file": file_info,
                            "error": str(e)
                        })
                        event_callback({
                            "type": "log",
                            "text": "Error moving file: " + entry.name + " | " + str(e),
                            "color": "text-rose-400"
                        })

    except Exception as e:
        if not quiet and event_callback is None:
            print("Error scanning " + source_dir + " | " + str(e))
        if log_path:
            write_log(log_path, "ERROR scanning " + source_dir + " | " + str(e))
        if event_callback:
            event_callback({"type": "error", "error": str(e)})
            event_callback({
                "type": "log",
                "text": "Error scanning " + source_dir + " | " + str(e),
                "color": "text-rose-400 font-bold"
            })

    total = sum(counts.values())
    total_bytes = sum(sizes.values())

    if run_id:
        history.finish_transaction(run_id, counts, total_bytes=total_bytes)

    if not quiet and event_callback is None:
        print("")
        print(mode + " complete.")
        print("Total files " + ("that would be " if dry_run else "") + "moved: " + str(total))
        for category in config.CATEGORY_ORDER:
            print(category + ": " + str(counts[category]))
        print("")
        if log_path:
            print("Log saved to: " + log_path + "\n")

    summary_result = {
        "success": True,
        "mode": mode,
        "dry_run": dry_run,
        "quiet": quiet,
        "deep": False,
        "subfolders": use_subfolders,
        "target": source_dir,
        "total_files": total,
        "total_bytes": total_bytes,
        "total_bytes_formatted": format_bytes(total_bytes),
        "counts": counts,
        "sizes": sizes,
        "sizes_formatted": {cat: format_bytes(sz) for cat, sz in sizes.items()},
        "files": files_list,
        "removed_dirs": [],
        "run_id": run_id,
        "log_path": log_path
    }

    if event_callback:
        # Emit summary lines to Live Feed
        event_callback({
            "type": "log",
            "text": "\n" + mode + " complete.",
            "color": "text-indigo-300 font-semibold"
        })
        event_callback({
            "type": "log",
            "text": "Total files " + ("that would be " if dry_run else "") + "moved: " + str(total),
            "color": "text-white font-bold"
        })
        for category in config.CATEGORY_ORDER:
            if counts[category] > 0 or not quiet:
                event_callback({
                    "type": "log",
                    "text": category + ": " + str(counts[category]),
                    "color": "text-slate-300"
                })
        if log_path:
            event_callback({
                "type": "log",
                "text": "Log saved to: " + log_path,
                "color": "text-slate-400"
            })

        event_callback({
            "type": "complete",
            "summary": summary_result
        })

    return summary_result


def cleanup_empty_dirs(source_dir, log_path=None, run_id=None, event_callback=None):
    """
    Walk source_dir bottom-up and remove any subfolder left empty,
    cascading upward. Category folders and source_dir itself are never removed.
    """
    removed = []

    for dirpath, dirnames, filenames in os.walk(source_dir, topdown=False):
        if os.path.abspath(dirpath) == os.path.abspath(source_dir):
            continue

        name = os.path.basename(dirpath)
        if is_category_folder(name) or is_inside_category_folder(dirpath, source_dir):
            continue

        try:
            if not os.listdir(dirpath):
                os.rmdir(dirpath)
                removed.append(dirpath)
                if run_id:
                    history.record_removed_dir(run_id, dirpath)
                if event_callback:
                    event_callback({
                        "type": "folder_removed",
                        "path": dirpath
                    })
                    event_callback({
                        "type": "log",
                        "text": "REMOVED EMPTY FOLDER: " + dirpath,
                        "color": "text-amber-400"
                    })
        except Exception as e:
            if event_callback:
                event_callback({"type": "error", "error": "Error removing folder " + dirpath + ": " + str(e)})
                event_callback({
                    "type": "log",
                    "text": "Error removing folder " + dirpath + ": " + str(e),
                    "color": "text-rose-400"
                })

    return removed


def preview_empty_dirs(source_dir):
    """
    Dry-run equivalent of cleanup_empty_dirs: predicts which folders
    would end up empty once matching files are moved out.
    """
    would_remove = []
    removable = set()

    for dirpath, dirnames, filenames in os.walk(source_dir, topdown=False):
        if os.path.abspath(dirpath) == os.path.abspath(source_dir):
            continue

        name = os.path.basename(dirpath)
        if is_category_folder(name) or is_inside_category_folder(dirpath, source_dir):
            continue

        remaining_files = [f for f in filenames if not splitext(f)[1]]
        remaining_subdirs = [
            d for d in dirnames
            if is_category_folder(d) or join(dirpath, d) not in removable
        ]

        if not remaining_files and not remaining_subdirs:
            removable.add(dirpath)
            would_remove.append(dirpath)

    return would_remove


def deep_scan_directory(source_dir, dry_run=False, quiet=False, event_callback=None, subfolders=None):
    """
    Recursively scan every subfolder of source_dir and sort files into
    the top-level category folders.

    subfolders behaves exactly as in process_directory.
    """
    use_subfolders = resolve_subfolders(subfolders)
    mode = "Dry Run (Deep Scan)" if dry_run else "Deep Scan"
    if quiet:
        mode = "Summary Only (Deep Scan)"

    if not quiet and event_callback is None:
        print(mode + ": Scanning " + source_dir)
        if dry_run:
            print("No files will be moved and no folders will be deleted.")
        print("")

    counts = {category: 0 for category in config.CATEGORY_ORDER}
    sizes = {category: 0 for category in config.CATEGORY_ORDER}
    files_list = []

    log_path = None
    run_id = None
    if not dry_run:
        run_id = history.start_transaction(source_dir, deep=True, mode="clean")
        log_path = history.get_log_path(run_id)

    if event_callback:
        event_callback({
            "type": "start",
            "mode": mode,
            "target": source_dir,
            "deep": True,
            "dry_run": dry_run,
            "quiet": quiet,
            "run_id": run_id,
            "message": mode + ": Scanning " + source_dir
        })
        if dry_run and not quiet:
            event_callback({
                "type": "log",
                "text": "No files will be moved and no folders will be deleted.",
                "color": "text-slate-400"
            })

    try:
        for dirpath, dirnames, filenames in os.walk(source_dir, topdown=True):
            dirnames[:] = [d for d in dirnames if not is_category_folder(d)]

            for filename in filenames:
                _, ext = splitext(filename)
                if not ext:
                    continue

                src_path = join(dirpath, filename)
                try:
                    file_size = os.path.getsize(src_path)
                except OSError:
                    file_size = 0

                category = get_category(ext)
                dest_dir = get_dest(ext, source_dir, subfolders=use_subfolders)
                dest_file_path = join(dest_dir, filename)

                counts[category] += 1
                sizes[category] += file_size

                file_info = {
                    "name": filename,
                    "src": src_path,
                    "dest_dir": dest_dir,
                    "dest_path": dest_file_path,
                    "category": category,
                    "subcategory": os.path.basename(dest_dir) if use_subfolders else None,
                    "extension": ext,
                    "size": file_size,
                    "size_formatted": format_bytes(file_size),
                    "status": "pending"
                }

                if dry_run:
                    file_info["status"] = "would_move"
                    files_list.append(file_info)
                    if not quiet and event_callback is None:
                        print("Would move " + src_path + " -> " + dest_dir)
                    if event_callback:
                        event_callback({
                            "type": "file_preview",
                            "file": file_info,
                            "counts": counts,
                            "sizes": sizes
                        })
                        if not quiet:
                            event_callback({
                                "type": "log",
                                "text": "Would move " + src_path + " -> " + dest_dir,
                                "color": "text-sky-400"
                            })
                    continue

                ensure_dir(dest_dir)
                unique_name = make_unique(dest_dir, filename)
                final_dest_path = join(dest_dir, unique_name)
                file_info["dest_path"] = final_dest_path
                file_info["unique_name"] = unique_name

                try:
                    if not quiet and event_callback is None:
                        print("Moving " + src_path + " -> " + dest_dir)

                    if event_callback:
                        event_callback({
                            "type": "file_moving",
                            "file": file_info
                        })

                    move(src_path, final_dest_path)
                    file_info["status"] = "moved"
                    files_list.append(file_info)

                    if run_id:
                        history.record_move(run_id, src_path, final_dest_path, category=category, file_size=file_size)

                    if event_callback:
                        event_callback({
                            "type": "file_moved",
                            "file": file_info,
                            "counts": counts,
                            "sizes": sizes,
                            "total_processed": len(files_list)
                        })
                        if not quiet:
                            event_callback({
                                "type": "log",
                                "text": "Moving " + src_path + " -> " + dest_dir,
                                "color": "text-emerald-400"
                            })

                except Exception as e:
                    file_info["status"] = "error"
                    file_info["error"] = str(e)
                    files_list.append(file_info)
                    if not quiet and event_callback is None:
                        print("Error moving file: " + src_path + " | " + str(e))
                    if log_path:
                        write_log(log_path, "ERROR: " + src_path + " | " + str(e))
                    if event_callback:
                        event_callback({
                            "type": "error",
                            "file": file_info,
                            "error": str(e)
                        })
                        event_callback({
                            "type": "log",
                            "text": "Error moving file: " + src_path + " | " + str(e),
                            "color": "text-rose-400"
                        })

    except Exception as e:
        if not quiet and event_callback is None:
            print("Error scanning " + source_dir + " | " + str(e))
        if log_path:
            write_log(log_path, "ERROR scanning " + source_dir + " | " + str(e))
        if event_callback:
            event_callback({"type": "error", "error": str(e)})
            event_callback({
                "type": "log",
                "text": "Error scanning " + source_dir + " | " + str(e),
                "color": "text-rose-400 font-bold"
            })

    if dry_run:
        removed_dirs = preview_empty_dirs(source_dir)
    else:
        removed_dirs = cleanup_empty_dirs(source_dir, log_path, run_id, event_callback)

    total = sum(counts.values())
    total_bytes = sum(sizes.values())

    if run_id:
        history.finish_transaction(run_id, counts, total_bytes=total_bytes)

    if not quiet and event_callback is None:
        print("")
        print(mode + " complete.")
        print("Total files " + ("that would be " if dry_run else "") + "moved: " + str(total))
        for category in config.CATEGORY_ORDER:
            print(category + ": " + str(counts[category]))
        if removed_dirs:
            verb = "would be removed" if dry_run else "removed"
            print("\nEmpty folders " + verb + ": " + str(len(removed_dirs)))
        print("")
        if log_path:
            print("Log saved to: " + log_path + "\n")

    summary_result = {
        "success": True,
        "mode": mode,
        "dry_run": dry_run,
        "quiet": quiet,
        "deep": True,
        "subfolders": use_subfolders,
        "target": source_dir,
        "total_files": total,
        "total_bytes": total_bytes,
        "total_bytes_formatted": format_bytes(total_bytes),
        "counts": counts,
        "sizes": sizes,
        "sizes_formatted": {cat: format_bytes(sz) for cat, sz in sizes.items()},
        "files": files_list,
        "removed_dirs": removed_dirs,
        "run_id": run_id,
        "log_path": log_path
    }

    if event_callback:
        event_callback({
            "type": "log",
            "text": "\n" + mode + " complete.",
            "color": "text-indigo-300 font-semibold"
        })
        event_callback({
            "type": "log",
            "text": "Total files " + ("that would be " if dry_run else "") + "moved: " + str(total),
            "color": "text-white font-bold"
        })
        for category in config.CATEGORY_ORDER:
            if counts[category] > 0 or not quiet:
                event_callback({
                    "type": "log",
                    "text": category + ": " + str(counts[category]),
                    "color": "text-slate-300"
                })
        if removed_dirs:
            verb = "would be removed" if dry_run else "removed"
            event_callback({
                "type": "log",
                "text": "Empty folders " + verb + ": " + str(len(removed_dirs)),
                "color": "text-amber-300"
            })
            if not quiet:
                for folder in removed_dirs:
                    event_callback({
                        "type": "log",
                        "text": "  " + folder,
                        "color": "text-slate-400"
                    })
        if log_path:
            event_callback({
                "type": "log",
                "text": "Log saved to: " + log_path,
                "color": "text-slate-400"
            })

        event_callback({
            "type": "complete",
            "summary": summary_result
        })

    return summary_result