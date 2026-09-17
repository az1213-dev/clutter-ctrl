<p align="center">
  <img src="assets/terminal-header.svg" alt="ClutterCtrl — take control of your filesystem clutter" width="100%" />
</p>

<p align="left">
  <a href="https://www.python.org"><img src="https://img.shields.io/badge/Python-3.9+-4285F4.svg?style=flat-square&logo=python&logoColor=white" alt="Python 3.9+" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-A166E0.svg?style=flat-square" alt="License: MIT" /></a>
  <a href="https://github.com/az1213-dev/clutter-ctrl/actions"><img src="https://img.shields.io/github/actions/workflow/status/az1213-dev/clutter-ctrl/ci.yml?style=flat-square&label=CI" alt="CI Status" /></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/Dependencies-0%20Mandatory-EA616E.svg?style=flat-square" alt="Zero Mandatory Dependencies" /></a>
</p>

A fast, lightweight terminal file organizer. It cleans up cluttered folders (like your Downloads or Desktop), sorts files into organized directories by type, lets you preview changes before touching anything, and keeps a dedicated log of every run so you can undo changes with a single command.

Written in pure Python with standard library modules, so you can run it immediately without installing any third-party packages.

---

## <img src="https://api.iconify.design/lucide:sparkles.svg?color=%234285F4" width="20" height="20" align="center" /> Features

- **Zero-Dependency CLI**: Runs directly in Windows Command Prompt, PowerShell, macOS Terminal, or Linux using standard Python.
- **Dedicated Run Logs**: Every organization run creates its own log file (`run_YYYY-MM-DD_HH-MM-SS_<id>.log`) recording the exact before and after paths for every file moved.
- **1-Click Undo**: Revert any previous run instantly with `clutterctrl undo` for the latest run, or `clutterctrl undo <#>` using the number shown by `clutterctrl history`.
- **Dry Run Previews**: Check file lists, categories, destination paths, and sizes in a clean table before anything gets moved.
- **Background Folder Watcher**: Optionally watch folders like Downloads to auto-sort new files as they arrive, with built-in debounce so it never touches partial downloads.
- **Standard and Deep Scans**: Choose between organizing top-level files or scanning entire folder trees recursively while cleaning up empty folders.
- **Per-Extension Subfolders**: Add `--subfolders` (`-s`) to split each category one level deeper — `Documents/Spreadsheets`, `Documents/Word`, `Documents/PDFs`, `Images/Photos`, `Images/Raw` — using rules you control in `categories.json`.
- **Safe Renaming**: Never overwrites existing files. If a file with the same name exists, it automatically adds a counter (like `photo_1.png`).
- **Stats & History**: View your past runs and see a visual bar chart of how your storage is organized across categories.

### Supported Categories

**Images** · **Videos** · **Audio** · **Documents** · **Code & Web** · **Projects & Creative** · **Data & Databases** · **Archives** · **Executables** · **Fonts** · **Misc**

---

## <img src="https://api.iconify.design/lucide:terminal.svg?color=%236878EC" width="20" height="20" align="center" /> Quickstart

### 1. Run Directly (No Setup Needed)
You can clone the repo and run ClutterCtrl right away:

```bash
git clone https://github.com/az1213-dev/clutter-ctrl.git
cd clutter-ctrl

# Run in Windows CMD or PowerShell
python clutterctrl/main.py
```

### 2. Install as a Global Command
If you want to use the `clutterctrl` command anywhere in your terminal, install it in editable mode:

```bash
pip install -e .

# Or with pipx
pipx install .
```

Now you can run `clutterctrl` from any directory.

---

## <img src="https://api.iconify.design/lucide:command.svg?color=%238E6CE4" width="20" height="20" align="center" /> CLI Commands

You can run ClutterCtrl with subcommands, or launch the interactive shell by running `clutterctrl` with no arguments:

```bash
# Open the interactive shell
clutterctrl

# Preview what will be moved in Downloads without changing anything
clutterctrl scan "C:\Users\Username\Downloads"

# Preview a folder recursively (Deep Scan)
clutterctrl scan "D:\Projects" --deep

# Clean and organize Downloads right away
clutterctrl clean "C:\Users\Username\Downloads"

# Clean an entire directory tree recursively
clutterctrl clean "D:\MessyFolder" --deep

# Watch a folder in the background and sort files as they arrive
clutterctrl watch "C:\Users\Username\Downloads"

# View past organization runs
clutterctrl history

# Undo the most recent run
clutterctrl undo

# Undo a run by the # shown in history
clutterctrl undo 2

# Undo a specific run by ID
clutterctrl undo run_2026-08-31_13-52-17_aad725

# View storage statistics and category distribution
clutterctrl stats

# View extension mapping rules
clutterctrl rules
```

### Per-Extension Subfolders

By default every file lands in a flat category folder. Add `--subfolders` (or `-s`) to split each
category one level deeper, so a crowded `Documents` folder becomes browsable:

```bash
clutterctrl scan "C:\Users\Username\Downloads" --subfolders
clutterctrl clean "C:\Users\Username\Downloads" --subfolders
clutterctrl watch "C:\Users\Username\Downloads" --subfolders
```

```
Downloads/
├── Documents/
│   ├── PDFs/            manual.pdf
│   ├── Word/            letter.docx
│   ├── Spreadsheets/    budget.xlsx  export.csv
│   ├── Presentations/   slides.pptx
│   └── Text_And_Notes/  notes.txt
├── Images/
│   ├── Photos/          holiday.png
│   └── Raw/             DSC_0001.nef
└── Misc/
    └── XYZ/             unknown.xyz
```

The groupings live in the `subcategories` block of `categories.json`, so you can rename or regroup
them however you like. Any extension without a rule gets a folder named after the extension itself
(`.xyz` → `XYZ`), so nothing is ever left loose. To make subfolders the permanent default, set
`"subfolders_enabled": true` in `categories.json` or export `CLUTTERCTRL_SUBFOLDERS=1`; pass
`--no-subfolders` to force the flat layout for a single run.

Undo works exactly the same either way — run logs record full source and destination paths, so
`clutterctrl undo` restores files from subfolders back to where they started.

### Interactive Shell

Running `clutterctrl` with no arguments opens the shell shown at the top of this page. It accepts the same commands you would type on the command line — `clean`, `scan`, `watch`, `history`, `undo`, `stats`, `rules` — plus `help` to reprint the command list and `exit` to quit.

---

## <img src="https://api.iconify.design/lucide:file-text.svg?color=%23AF65C9" width="20" height="20" align="center" /> Run Logs and Undo

ClutterCtrl creates a dedicated log file for every run inside the repository:
- **Log Path**: `clutterctrl/logs/run_*.log`

### What a Run Log Looks Like
```text
Run ID: run_2026-08-31_13-52-17_aad725
Run started: 2026-08-31T13:52:17.123456
Target: C:\Users\Username\Downloads
Deep Scan: False
Mode: clean
Status: ACTIVE

--- OPERATIONS ---
MOVED: C:\Users\Username\Downloads\photo.png -> C:\Users\Username\Downloads\Images\photo.png | Category: Images | Size: 1048576
MOVED: C:\Users\Username\Downloads\report.pdf -> C:\Users\Username\Downloads\Documents\report.pdf | Category: Documents | Size: 524288

--- SUMMARY ---
Total files moved: 2
Images: 1
Documents: 1
Total bytes: 1572864
Run completed: 2026-08-31T13:52:17.456789
Status: COMPLETED
```

When you undo a run, ClutterCtrl reads the operations in reverse, puts all files back in their original folders, and marks the log as `UNDONE`.

---

## <img src="https://api.iconify.design/lucide:flask-conical.svg?color=%23CC639B" width="20" height="20" align="center" /> Running Tests

You can run the test suite with `pytest`:

```bash
pytest -v
```

---

## <img src="https://api.iconify.design/lucide:scale.svg?color=%23EA616E" width="20" height="20" align="center" /> License

This project is open source and available under the MIT License. See [LICENSE](LICENSE) for details.
