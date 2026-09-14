import os
import sys
import tempfile
import shutil
import pytest
from unittest.mock import patch

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from clutterctrl import main
from clutterctrl import history


@pytest.fixture
def temp_test_dir():
    d = tempfile.mkdtemp(prefix="test_cli_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_cli_rules(capsys):
    main.cmd_rules()
    captured = capsys.readouterr()
    assert "Images" in captured.out
    assert "Documents" in captured.out


def test_banner_renders(capsys):
    # Every character of BANNER_WORD needs a glyph, or the shell crashes on startup.
    main.print_banner()
    captured = capsys.readouterr()
    assert captured.out.strip()


def test_cli_stats(capsys):
    main.cmd_stats()
    captured = capsys.readouterr()
    assert "System & Run History Statistics" in captured.out
    assert "Total Runs Recorded" in captured.out


def test_cli_scan_and_clean(temp_test_dir, capsys):
    # Create test files
    f1 = os.path.join(temp_test_dir, "test.png")
    f2 = os.path.join(temp_test_dir, "test.docx")
    with open(f1, "w") as f:
        f.write("img")
    with open(f2, "w") as f:
        f.write("doc")

    # Dry run scan
    main.cmd_scan(temp_test_dir, deep=False)
    captured = capsys.readouterr()
    assert "Dry Run Scan Preview" in captured.out
    assert "2 files" in captured.out
    assert os.path.exists(f1)
    assert os.path.exists(f2)

    # Real clean
    main.cmd_clean(temp_test_dir, deep=False)
    captured_clean = capsys.readouterr()
    assert "Organization Complete" in captured_clean.out
    assert "Total Files Moved:" in captured_clean.out
    assert os.path.exists(os.path.join(temp_test_dir, "Images", "test.png"))
    assert os.path.exists(os.path.join(temp_test_dir, "Documents", "test.docx"))


def test_cli_history_and_undo(temp_test_dir, capsys):
    # Create and clean file
    f1 = os.path.join(temp_test_dir, "song.mp3")
    with open(f1, "w") as f:
        f.write("audio")

    main.cmd_clean(temp_test_dir, deep=False)
    capsys.readouterr()

    # History command
    main.cmd_history(limit=5)
    captured_hist = capsys.readouterr()
    assert "Recent Organization Runs" in captured_hist.out

    # Undo with confirmation mocked to 'y'
    with patch("builtins.input", return_value="y"):
        main.cmd_undo("1")
    captured_undo = capsys.readouterr()
    assert "Rollback Run" in captured_undo.out
    assert "[OK]" in captured_undo.out
    assert os.path.exists(f1)
