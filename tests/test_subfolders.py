import os
import sys
import shutil
import tempfile
import pytest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from clutterctrl import cleaner
from clutterctrl import helpers
from clutterctrl import history
from clutterctrl import main
from clutterctrl import watcher


@pytest.fixture
def temp_dir():
    d = tempfile.mkdtemp(prefix="test_subfolders_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def write(path, text="data"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    return path


def test_get_subcategory_uses_rules():
    assert helpers.get_subcategory(".xlsx") == "Spreadsheets"
    assert helpers.get_subcategory(".csv") == "Spreadsheets"
    assert helpers.get_subcategory(".docx") == "Word"
    assert helpers.get_subcategory(".pptx") == "Presentations"
    assert helpers.get_subcategory(".pdf") == "PDFs"
    assert helpers.get_subcategory(".PNG") == "Photos"


def test_get_subcategory_falls_back_to_extension_name():
    # Unknown extension -> Misc category, folder named after the extension.
    assert helpers.get_category(".xyz") == "Misc"
    assert helpers.get_subcategory(".xyz") == "XYZ"
    assert helpers.extension_folder_name(".gz") == "GZ"
    assert helpers.extension_folder_name(".") == "Other"


def test_get_dest_flat_vs_subfolders(temp_dir):
    flat = helpers.get_dest(".xlsx", temp_dir)
    nested = helpers.get_dest(".xlsx", temp_dir, subfolders=True)
    assert flat == os.path.join(temp_dir, "Documents")
    assert nested == os.path.join(temp_dir, "Documents", "Spreadsheets")


def test_clean_with_subfolders_splits_a_category(temp_dir):
    write(os.path.join(temp_dir, "budget.xlsx"))
    write(os.path.join(temp_dir, "letter.docx"))
    write(os.path.join(temp_dir, "slides.pptx"))
    write(os.path.join(temp_dir, "manual.pdf"))

    res = cleaner.process_directory(temp_dir, dry_run=False, quiet=True, subfolders=True)

    assert res["subfolders"] is True
    assert res["counts"]["Documents"] == 4
    docs = os.path.join(temp_dir, "Documents")
    assert os.path.isfile(os.path.join(docs, "Spreadsheets", "budget.xlsx"))
    assert os.path.isfile(os.path.join(docs, "Word", "letter.docx"))
    assert os.path.isfile(os.path.join(docs, "Presentations", "slides.pptx"))
    assert os.path.isfile(os.path.join(docs, "PDFs", "manual.pdf"))


def test_subfolder_run_is_undoable(temp_dir):
    src = write(os.path.join(temp_dir, "budget.xlsx"))

    res = cleaner.process_directory(temp_dir, dry_run=False, quiet=True, subfolders=True)
    assert not os.path.exists(src)

    undo_res = history.undo_run(res["run_id"])
    assert undo_res["success"] is True
    assert undo_res["restored"] == 1
    assert os.path.isfile(src)


def test_dry_run_with_subfolders_moves_nothing(temp_dir):
    src = write(os.path.join(temp_dir, "budget.xlsx"))

    res = cleaner.process_directory(temp_dir, dry_run=True, quiet=True, subfolders=True)

    assert res["total_files"] == 1
    assert res["files"][0]["subcategory"] == "Spreadsheets"
    assert os.path.isfile(src)
    assert not os.path.isdir(os.path.join(temp_dir, "Documents"))


def test_second_deep_run_leaves_subfolders_alone(temp_dir):
    write(os.path.join(temp_dir, "budget.xlsx"))

    cleaner.deep_scan_directory(temp_dir, dry_run=False, quiet=True, subfolders=True)
    placed = os.path.join(temp_dir, "Documents", "Spreadsheets", "budget.xlsx")
    assert os.path.isfile(placed)

    # Re-running must not re-sort already-organized files or delete their folders.
    second = cleaner.deep_scan_directory(temp_dir, dry_run=False, quiet=True, subfolders=True)
    assert second["total_files"] == 0
    assert os.path.isfile(placed)


def test_empty_folder_inside_category_is_not_deleted(temp_dir):
    keep = os.path.join(temp_dir, "Documents", "My Notes")
    os.makedirs(keep, exist_ok=True)
    stray = os.path.join(temp_dir, "stray")
    os.makedirs(stray, exist_ok=True)

    removed = cleaner.cleanup_empty_dirs(temp_dir)

    assert os.path.isdir(keep), "user folders inside a category folder must survive"
    assert not os.path.isdir(stray)
    assert stray in removed


def test_is_inside_category_folder(temp_dir):
    assert cleaner.is_inside_category_folder(os.path.join(temp_dir, "Documents", "Word"), temp_dir)
    assert cleaner.is_inside_category_folder(os.path.join(temp_dir, "Images"), temp_dir)
    assert not cleaner.is_inside_category_folder(os.path.join(temp_dir, "stray", "deeper"), temp_dir)
    assert not cleaner.is_inside_category_folder(temp_dir, temp_dir)


def test_watcher_ignores_files_already_in_a_subfolder(temp_dir):
    handler = watcher.OrganizeEventHandler(temp_dir, deep=True, subfolders=True)
    try:
        organized = write(os.path.join(temp_dir, "Documents", "Word", "letter.docx"))
        handler._handle_file(organized)
        assert handler._pending_files == {}, "already-organized files must not be re-sorted"

        loose = write(os.path.join(temp_dir, "new.docx"))
        handler._handle_file(loose)
        assert len(handler._pending_files) == 1
    finally:
        handler.stop()


def test_stats_reports_bytes_per_category(temp_dir):
    write(os.path.join(temp_dir, "photo.png"), "x" * 2048)

    res = cleaner.process_directory(temp_dir, dry_run=False, quiet=True)
    run = history.get_transaction(res["run_id"])

    assert run["category_bytes"]["Images"] == 2048
    stats = history.get_stats()
    assert stats["categories"]["Images"]["bytes"] >= 2048
    assert stats["categories"]["Images"]["bytes_formatted"] != "0 B"


def test_cli_subfolder_flags_parse():
    parser = main.build_parser()

    assert parser.parse_args(["clean", "."]).subfolders is None
    assert parser.parse_args(["clean", ".", "-s"]).subfolders is True
    assert parser.parse_args(["scan", ".", "--subfolders"]).subfolders is True
    assert parser.parse_args(["clean", ".", "--no-subfolders"]).subfolders is False
    assert parser.parse_args(["watch", ".", "-s"]).subfolders is True


def test_cli_scan_shows_subfolder_destination(temp_dir, capsys):
    write(os.path.join(temp_dir, "budget.xlsx"))

    main.cmd_scan(temp_dir, subfolders=True)
    out = capsys.readouterr().out

    assert "Documents/Spreadsheets" in out
