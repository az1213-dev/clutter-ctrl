import sys
import os
import re
import shlex
import shutil
import argparse
import time
from typing import Optional, List, Dict, Any

__version__ = "1.0.1"

# Support both direct script execution (python clutterctrl/main.py) and module execution (python -m clutterctrl.main)
if __package__ is None or __package__ == "":
    _pkg_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _pkg_root not in sys.path:
        sys.path.insert(0, _pkg_root)
    __package__ = "clutterctrl"

from . import config
from .config import DOWNLOADS_DIR, reload_categories, CATEGORY_ORDER, CATEGORY_EXTENSIONS
from .cleaner import process_directory, deep_scan_directory
from .helpers import get_available_drives, format_bytes
from . import history
from .watcher import watcher_manager


# --- Terminal Colors & VT100 Setup ---
class Colors:
    CYAN = "\033[96m"
    BLUE = "\033[94m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    MAGENTA = "\033[95m"
    WHITE = "\033[97m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"
    # Gemini-CLI-style accent used for borders / prompts (soft periwinkle-blue)
    ACCENT = "\033[38;2;138;180;248m"


# Gradient stops lifted from the Gemini CLI banner: blue -> violet -> coral.
GRADIENT_STOPS = [
    (66, 133, 244),   # blue
    (161, 102, 224),  # violet
    (234, 97, 110),   # coral/pink
]

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def visible_len(text: str) -> int:
    """Length of a string on-screen, ignoring ANSI escape sequences."""
    return len(_ANSI_RE.sub("", text))


def _lerp_color(t: float, stops=GRADIENT_STOPS):
    n = len(stops) - 1
    seg = min(int(t * n), n - 1)
    local_t = (t * n) - seg
    c0, c1 = stops[seg], stops[seg + 1]
    return tuple(int(c0[i] + (c1[i] - c0[i]) * local_t) for i in range(3))


def _darken(rgb, factor: float = 0.38):
    return tuple(int(v * factor) for v in rgb)


def gradient_line(line: str, width: Optional[int] = None) -> str:
    """Colorize a single line of text with a left-to-right truecolor gradient."""
    width = width or max(len(line) - 1, 1)
    out = []
    for i, ch in enumerate(line):
        if ch == " ":
            out.append(ch)
            continue
        r, g, b = _lerp_color(i / width)
        out.append(f"\033[38;2;{r};{g};{b}m{ch}")
    out.append(Colors.RESET)
    return "".join(out)


def clear_screen():
    """Clear the terminal for an app-like, redrawn interface (like Gemini CLI)."""
    if os.getenv("CLUTTERCTRL_NO_CLEAR"):
        return
    print("\033[2J\033[H", end="")


# --- Block-letter font used for the CLUTTERCTRL logo (5 wide x 6 tall) ---
_GLYPHS: Dict[str, List[str]] = {
    "C": ["█████", "██   ", "██   ", "██   ", "██   ", "█████"],
    "L": ["██   ", "██   ", "██   ", "██   ", "██   ", "█████"],
    "U": ["██ ██", "██ ██", "██ ██", "██ ██", "██ ██", "█████"],
    "T": ["█████", " ██  ", " ██  ", " ██  ", " ██  ", " ██  "],
    "E": ["█████", "██   ", "████ ", "██   ", "██   ", "█████"],
    "R": ["████ ", "██ ██", "████ ", "██ ██", "██ ██", "██ ██"],
    # Right-pointing chevron used as the clutterctrl logomark, Gemini-CLI style.
    ">": ["██   ", " ██  ", "  ██ ", "  ██ ", " ██  ", "██   "],
    # Separator between the logomark and the wordmark. Narrower than a letter
    # cell so it does not cost 5 scaled pixels of width.
    " ": ["  ", "  ", "  ", "  ", "  ", "  "],
}


def _render_glyph_rows(word: str, gap: int = 1, xscale: int = 1) -> List[str]:
    """Render `word` in the block font, each glyph pixel `xscale` terminal cells wide.

    Terminal cells are about twice as tall as they are wide, so xscale > 1 is what
    keeps the letterforms from looking vertically stretched.
    """
    rows = [""] * 6
    letters = list(word)
    for idx, ch in enumerate(letters):
        glyph = _GLYPHS[ch]
        for r in range(6):
            rows[r] += "".join(px * xscale for px in glyph[r])
            if idx != len(letters) - 1:
                rows[r] += " " * gap
    return rows


def _composite_glyph_grid(rows: List[str], shadow_dx: int = 1, shadow_dy: int = 1):
    """Stamp a shadow copy offset down-right, then the front face on top, for a 3D look."""
    height = len(rows)
    width = len(rows[0])
    total_h = height + shadow_dy
    total_w = width + shadow_dx
    grid: List[List[Optional[str]]] = [[None] * total_w for _ in range(total_h)]

    for r in range(height):
        for c in range(width):
            if rows[r][c] != " ":
                grid[r + shadow_dy][c + shadow_dx] = "shadow"

    for r in range(height):
        for c in range(width):
            if rows[r][c] != " ":
                grid[r][c] = "front"

    return grid, total_w, total_h


BANNER_WORD = "> CLUTTERCTRL"
BANNER_PIXEL_WIDTH = 4


def print_banner(compact: bool = False):
    """Print the CLUTTERCTRL 3D gradient logo, Gemini-CLI style."""
    term_width = shutil.get_terminal_size((80, 24)).columns

    # Widest pixel scale that still fits the terminal; +xscale covers the shadow offset.
    for xscale in range(BANNER_PIXEL_WIDTH, 0, -1):
        rows = _render_glyph_rows(BANNER_WORD, xscale=xscale)
        if len(rows[0]) + xscale <= term_width:
            break

    banner_width = len(rows[0])

    if compact or banner_width + xscale > term_width:
        # Narrow terminal fallback: single gradient line of plain text.
        print(gradient_line("CLUTTERCTRL"))
        print()
        return

    grid, total_w, total_h = _composite_glyph_grid(rows, shadow_dx=xscale, shadow_dy=1)
    denom = max(banner_width - 1, 1)

    print()
    for r in range(total_h):
        parts = []
        for col in range(total_w):
            cell = grid[r][col]
            if cell is None:
                parts.append(f"{Colors.RESET} ")
                continue
            src_col = col - (xscale if cell == "shadow" else 0)
            rgb = _lerp_color(min(max(src_col, 0), denom) / denom)
            if cell == "shadow":
                rgb = _darken(rgb)
            rr, gg, bb = rgb
            # Background fill rather than a "█" glyph: block characters leave
            # hairline gaps in fonts whose glyph does not fill the whole cell.
            parts.append(f"\033[48;2;{rr};{gg};{bb}m ")
        parts.append(Colors.RESET)
        print("".join(parts))
    print()


COMMANDS: List[tuple] = [
    ("clean [path] [--deep]", "Organize a folder (default: Downloads)"),
    ("scan [path] [--deep]", "Preview changes without moving anything"),
    ("watch [path] [--deep]", "Live-watch a folder and auto-sort new files"),
    ("history [--limit N]", "Show past organization runs"),
    ("undo [#]", "Roll back a run — bare 'undo' reverts the latest"),
    ("stats", "Show lifetime organization statistics"),
    ("rules", "Show category extension rules"),
    ("help", "Show this command list"),
    ("exit", "Quit clutterctrl"),
]


def print_commands():
    """The single reference section shown in the interactive shell."""
    c = Colors
    print(f"{c.BOLD}Commands{c.RESET}")
    for name, desc in COMMANDS:
        print(f"  {c.ACCENT}{name.ljust(24)}{c.RESET} {c.DIM}{desc}{c.RESET}")
    print()


def print_hint_row():
    c = Colors
    term_width = shutil.get_terminal_size((80, 24)).columns
    print(f"{c.DIM}{'─' * term_width}{c.RESET}")
    left = f"{c.DIM}Type a command and press Enter{c.RESET}"
    right = f"{c.DIM}clutterctrl v{__version__}{c.RESET}"
    gap = max(term_width - visible_len(left) - visible_len(right), 1)
    print(f"{left}{' ' * gap}{right}")


def print_input_box(prompt: str = "› ") -> str:
    """A Gemini-CLI-style bordered input line."""
    c = Colors
    term_width = shutil.get_terminal_size((80, 24)).columns
    inner_width = max(term_width - 4, 10)
    top = f"{c.ACCENT}╭{'─' * (inner_width + 2)}╮{c.RESET}"
    bottom = f"{c.ACCENT}╰{'─' * (inner_width + 2)}╯{c.RESET}"

    print(top)
    sys.stdout.write(f"{c.ACCENT}│{c.RESET} {c.ACCENT}{prompt}{c.RESET}")
    sys.stdout.flush()
    try:
        line = input()
    except (EOFError, KeyboardInterrupt):
        print()
        line = "exit"
    print(bottom)
    return line.strip()


def print_status_bar(context: str = ""):
    """Footer status line, similar to Gemini CLI's bottom status bar."""
    c = Colors
    cwd = os.getcwd()
    term_width = shutil.get_terminal_size((80, 24)).columns
    left = f"{c.ACCENT}clutterctrl v{__version__}{c.RESET}"
    right = f"{c.DIM}{context or cwd}{c.RESET}"
    gap = max(term_width - visible_len(left) - visible_len(right) - 1, 1)
    print(f"{left}{' ' * gap}{right}")


def init_terminal():
    """Enable Windows 10+ ANSI color escape sequences and UTF-8 encoding."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            h_stdout = kernel32.GetStdHandle(-11)
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(h_stdout, ctypes.byref(mode)):
                # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
                kernel32.SetConsoleMode(h_stdout, mode.value | 0x0004)
        except Exception:
            pass


init_terminal()


def confirm(message: str) -> bool:
    c = Colors
    ans = input(f"{c.YELLOW}{message} (y/n): {c.RESET}").strip().lower()
    return ans in ("y", "yes")


def print_table(headers: List[str], rows: List[List[str]], col_align: Optional[List[str]] = None):
    """Render a clean formatted ASCII terminal table."""
    c = Colors
    if not rows:
        print(f"  {c.DIM}(No records found){c.RESET}")
        return

    # Calculate column widths
    widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(str(val)))

    # Print Header
    header_str = " | ".join(f"{c.BOLD}{h.ljust(widths[i])}{c.RESET}" for i, h in enumerate(headers))
    sep_str = "-+-".join("-" * widths[i] for i in range(len(headers)))
    print(f"  {header_str}")
    print(f"  {c.DIM}{sep_str}{c.RESET}")

    # Print Rows
    for row in rows:
        row_str = " | ".join(str(val).ljust(widths[i]) for i, val in enumerate(row))
        print(f"  {row_str}")


def cmd_stats():
    """Display overall run log and lifetime organization statistics."""
    c = Colors
    stats = history.get_stats()
    print(f"\n{c.BOLD}[*] System & Run History Statistics{c.RESET}")
    print(f"{c.DIM}Logs location: {stats['log_dir']} ({stats['total_log_files']} run log file(s)){c.RESET}\n")

    print(f"  * {c.BOLD}Total Runs Recorded:{c.RESET}       {c.CYAN}{stats['total_runs']}{c.RESET}")
    print(f"  * {c.BOLD}Active Files Organized:{c.RESET}    {c.GREEN}{stats['total_files_organized']}{c.RESET}")
    print(f"  * {c.BOLD}Active Data Organized:{c.RESET}     {c.GREEN}{stats['total_bytes_formatted']}{c.RESET}")
    print(f"  * {c.BOLD}Lifetime Files Moved:{c.RESET}      {c.WHITE}{stats['lifetime_files_moved']}{c.RESET}")
    print(f"  * {c.BOLD}Reverted (Undone) Runs:{c.RESET}    {c.YELLOW}{stats['total_undone_runs']}{c.RESET}\n")

    if stats["categories"]:
        print(f"{c.BOLD}Category Distribution:{c.RESET}")
        max_cnt = max((cat["count"] for cat in stats["categories"].values()), default=1) or 1
        for cat_name, cat_data in stats["categories"].items():
            bar_len = int((cat_data["count"] / max_cnt) * 24)
            bar = "#" * bar_len + "-" * (24 - bar_len)
            print(f"  {cat_name.ljust(18)} {c.CYAN}[{bar}]{c.RESET} {cat_data['count']:>4} files ({cat_data['bytes_formatted']})")
    print("")


def cmd_history(limit: int = 20):
    """Display recent run history from individual run log files."""
    c = Colors
    runs = history.get_all_history(limit=limit)
    print(f"\n{c.BOLD}[*] Recent Organization Runs (Dedicated Log Files){c.RESET}\n")

    headers = ["#", "Run ID", "Date / Time", "Status", "Mode", "Files", "Size", "Target Folder"]
    rows = []
    for i, r in enumerate(runs, start=1):
        status_color = c.YELLOW if r["undone"] else c.GREEN
        status_text = f"{status_color}[UNDONE]{c.RESET}" if r["undone"] else f"{status_color}[ACTIVE]{c.RESET}"
        dt = r["timestamp"].replace("T", " ")[:19]
        deep_suffix = " (Deep)" if r["deep"] else ""
        target_str = r["target_dir"] + deep_suffix
        if len(target_str) > 35:
            target_str = "..." + target_str[-32:]

        rows.append([
            str(i),
            r["run_id"],
            dt,
            status_text,
            r["mode"],
            str(r["total_files"]),
            r["total_bytes_formatted"],
            target_str
        ])

    print_table(headers, rows)
    print(f"\n{c.DIM}Roll back with the # column: {c.RESET}{c.ACCENT}undo 1{c.RESET}{c.DIM} reverts the most recent run.{c.RESET}\n")


def cmd_undo(run_id_or_index: Optional[str] = None):
    """Undo / Rollback a specific run or the latest active run."""
    c = Colors
    if not run_id_or_index:
        active_runs = [r for r in history.get_all_history(limit=10) if not r["undone"]]
        if not active_runs:
            print(f"{c.YELLOW}No active runs found in logs to undo.{c.RESET}")
            return
        target_run = active_runs[0]
    else:
        # Check if user passed an index number like '1' or '2'
        if run_id_or_index.isdigit():
            idx = int(run_id_or_index) - 1
            # Fetch through the requested row so any '#' shown by `history` resolves,
            # however large a --limit that listing used.
            all_runs = history.get_all_history(limit=max(idx + 1, 1))
            if 0 <= idx < len(all_runs):
                target_run = all_runs[idx]
            else:
                print(f"{c.RED}No run #{run_id_or_index} in history. Run 'history' to see the list.{c.RESET}")
                return
        else:
            target_run = history.get_transaction(run_id_or_index)
            if not target_run:
                print(f"{c.RED}Run ID '{run_id_or_index}' not found in logs.{c.RESET}")
                return

    run_id = target_run["run_id"]
    if target_run.get("undone"):
        print(f"{c.YELLOW}Run '{run_id}' has already been undone.{c.RESET}")
        return

    print(f"\n{c.BOLD}[<] Rollback Run:{c.RESET} {c.CYAN}{run_id}{c.RESET}")
    print(f"  Target Directory: {target_run['target_dir']}")
    print(f"  Files to restore: {target_run['total_files']} files ({target_run.get('total_bytes_formatted', '')})")
    print(f"  Log File:         {target_run.get('log_path', '')}")

    if confirm("Are you sure you want to revert this operation?"):
        print(f"{c.DIM}Reverting files back to source locations...{c.RESET}")
        result = history.undo_run(run_id)
        if result["success"]:
            print(f"{c.GREEN}[OK] {result['message']}{c.RESET}\n")
        else:
            print(f"{c.RED}[ERR] {result['message']}{c.RESET}\n")
            for err in result.get("errors", []):
                print(f"  {c.RED}- {err}{c.RESET}")


def cmd_scan(target_dir: str, deep: bool = False):
    """Run a dry run scan and print a visual preview table."""
    c = Colors
    target = os.path.abspath(target_dir)
    if not os.path.isdir(target):
        print(f"{c.RED}Error: Directory not found: {target}{c.RESET}")
        return

    print(f"\n{c.BOLD}[?] Dry Run Scan Preview:{c.RESET} {c.CYAN}{target}{c.RESET} {'(Deep Scan)' if deep else ''}\n")

    fn = deep_scan_directory if deep else process_directory
    res = fn(target, dry_run=True, quiet=True)

    files = res.get("files", [])
    if not files:
        print(f"{c.GREEN}No unorganized files found. Everything is already clean!{c.RESET}\n")
        return

    headers = ["#", "File Name", "Category", "Size", "Destination Subfolder"]
    rows = []
    for i, f in enumerate(files[:50], start=1):
        rows.append([
            str(i),
            f["name"] if len(f["name"]) <= 30 else f["name"][:27] + "...",
            f["category"],
            f["size_formatted"],
            os.path.basename(f["dest_dir"])
        ])

    print_table(headers, rows)
    if len(files) > 50:
        print(f"\n  {c.DIM}... and {len(files) - 50} more file(s){c.RESET}")

    print(f"\n{c.BOLD}Summary:{c.RESET} {c.CYAN}{res['total_files']} files{c.RESET} ({res['total_bytes_formatted']}) would be organized.")
    for cat, cnt in res["counts"].items():
        if cnt > 0:
            print(f"  * {cat.ljust(15)}: {cnt}")
    print(f"\n{c.DIM}To execute this cleanup: clutterctrl clean \"{target}\"{' --deep' if deep else ''}{c.RESET}\n")


def cmd_clean(target_dir: str, deep: bool = False, quiet: bool = False):
    """Execute live file organization and record into dedicated run log file."""
    c = Colors
    target = os.path.abspath(target_dir)
    if not os.path.isdir(target):
        print(f"{c.RED}Error: Directory not found: {target}{c.RESET}")
        return

    print(f"\n{c.BOLD}[+] ClutterCtrl Organizing:{c.RESET} {c.CYAN}{target}{c.RESET} {'(Deep Scan)' if deep else ''}\n")

    fn = deep_scan_directory if deep else process_directory
    res = fn(target, dry_run=False, quiet=quiet)

    print(f"\n{c.GREEN}[OK] Organization Complete!{c.RESET}")
    print(f"  * Total Files Moved: {c.BOLD}{res['total_files']}{c.RESET} ({res['total_bytes_formatted']})")
    print(f"  * Run ID:            {c.CYAN}{res['run_id']}{c.RESET}")
    print(f"  * Log File:          {res.get('log_path', '')}")
    if res.get("removed_dirs"):
        print(f"  * Empty Folders Removed: {len(res['removed_dirs'])}")
    print(f"\n{c.DIM}To roll this back, just run {c.RESET}{c.ACCENT}undo{c.RESET}{c.DIM} — it reverts the latest run.{c.RESET}\n")


def cmd_watch(target_dir: str, deep: bool = False):
    """Start background folder watcher in the terminal."""
    c = Colors
    target = os.path.abspath(target_dir)
    if not os.path.isdir(target):
        print(f"{c.RED}Error: Directory not found: {target}{c.RESET}")
        return

    print(f"\n{c.BOLD}[*] Active Folder Watcher Started{c.RESET}")
    print(f"  Monitoring Directory: {c.CYAN}{target}{c.RESET}")
    print(f"  Recursive (Deep):     {c.WHITE}{deep}{c.RESET}")
    print(f"  Audit Logging:        {c.GREEN}Dedicated Run Logs{c.RESET}")
    print(f"  {c.DIM}Press Ctrl+C to stop watcher.{c.RESET}\n")

    def on_event(event):
        if event["type"] == "watchdog_organized":
            f = event["file"]
            print(f"{c.GREEN}[AUTO-SORTED]{c.RESET} {c.WHITE}{f['name']}{c.RESET} -> {c.CYAN}{f['category']}{c.RESET} ({f['size_formatted']})")
        elif event["type"] == "watchdog_error":
            print(f"{c.RED}[ERROR]{c.RESET} {event['file']}: {event['error']}")

    success, msg = watcher_manager.start(target, deep=deep, event_callback=on_event)
    if not success:
        print(f"{c.RED}Error: {msg}{c.RESET}")
        return

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n{c.YELLOW}Stopping watcher...{c.RESET}")
        watcher_manager.stop(target)
        print(f"{c.GREEN}Watcher stopped safely.{c.RESET}\n")


def cmd_rules():
    """Display current category extension rules."""
    c = Colors
    categories, misc = config.load_categories()
    print(f"\n{c.BOLD}[*] Category Extension Mappings{c.RESET} {c.DIM}({config.CATEGORIES_FILE}){c.RESET}\n")

    headers = ["Category", "Total Extensions", "Sample Extensions"]
    rows = []
    for cat_name, exts in categories.items():
        sample = ", ".join(exts[:8])
        if len(exts) > 8:
            sample += f" ... (+{len(exts) - 8} more)"
        rows.append([cat_name, str(len(exts)), sample])
    rows.append([misc, "-", "Any unrecognized extensions"])

    print_table(headers, rows)
    print("")


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser shared by direct CLI invocation and the interactive shell."""
    parser = argparse.ArgumentParser(
        prog="clutterctrl",
        description="ClutterCtrl: Lightweight File Organizer with Per-Run Audit Logs & Rollback"
    )

    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # clean subcommand
    clean_p = subparsers.add_parser("clean", help="Organize files in target directory")
    clean_p.add_argument("target", nargs="?", default=DOWNLOADS_DIR, help="Target folder (default: Downloads)")
    clean_p.add_argument("--deep", "-d", action="store_true", help="Recursive deep scan")
    clean_p.add_argument("--quiet", "-q", action="store_true", help="Summary output only")

    # scan / dry-run subcommand
    scan_p = subparsers.add_parser("scan", help="Preview organization without moving files")
    scan_p.add_argument("target", nargs="?", default=DOWNLOADS_DIR, help="Target folder (default: Downloads)")
    scan_p.add_argument("--deep", "-d", action="store_true", help="Recursive deep scan")

    # watch subcommand
    watch_p = subparsers.add_parser("watch", help="Watch folder for new files and auto-sort")
    watch_p.add_argument("target", nargs="?", default=DOWNLOADS_DIR, help="Target folder (default: Downloads)")
    watch_p.add_argument("--deep", "-d", action="store_true", help="Recursive deep scan")

    # history subcommand
    hist_p = subparsers.add_parser("history", help="List past organization runs from log files")
    hist_p.add_argument("--limit", "-n", type=int, default=20, help="Number of runs to display")

    # undo subcommand
    undo_p = subparsers.add_parser("undo", help="Rollback / undo a specific run")
    undo_p.add_argument("run_id", nargs="?", default=None, help="Run # from 'history', or a full Run ID (default: latest active run)")

    # stats subcommand
    subparsers.add_parser("stats", help="Show storage and lifetime organization statistics")

    # rules subcommand
    subparsers.add_parser("rules", help="Show category extension mappings")

    # Legacy / Flag-based arguments for backwards compatibility
    parser.add_argument("--target", "-t", type=str, help="Target directory")
    parser.add_argument("--clean", action="store_true", help="Clean immediately")
    parser.add_argument("--dry-run", action="store_true", help="Dry run preview")
    parser.add_argument("--deep", action="store_true", help="Recursive deep scan")
    parser.add_argument("--watch", "-w", type=str, help="Watch directory")
    parser.add_argument("--undo", type=str, help="Undo run ID")
    parser.add_argument("--undo-last", action="store_true", help="Undo last run")

    return parser


def dispatch(args: argparse.Namespace):
    """Run whichever subcommand / legacy flag combination `args` selects."""
    c = Colors
    if args.command == "clean":
        cmd_clean(args.target, deep=args.deep, quiet=args.quiet)
    elif args.command == "scan":
        cmd_scan(args.target, deep=args.deep)
    elif args.command == "watch":
        cmd_watch(args.target, deep=args.deep)
    elif args.command == "history":
        cmd_history(limit=args.limit)
    elif args.command == "undo":
        cmd_undo(args.run_id)
    elif args.command == "stats":
        cmd_stats()
    elif args.command == "rules":
        cmd_rules()
    elif args.watch:
        cmd_watch(args.watch, deep=args.deep)
    elif args.undo:
        cmd_undo(args.undo)
    elif args.undo_last:
        cmd_undo(None)
    elif args.target:
        if args.clean:
            cmd_clean(args.target, deep=args.deep)
        else:
            cmd_scan(args.target, deep=args.deep)
    else:
        print(f"{c.YELLOW}Unknown command. Type 'help' to see available commands.{c.RESET}")


def interactive_shell():
    """Gemini-CLI-style interactive shell: banner, a Commands reference, then a live input loop."""
    c = Colors
    clear_screen()
    print_banner()
    print_commands()
    print_hint_row()
    print()

    parser = build_parser()

    while True:
        line = print_input_box()
        if not line:
            print()
            continue

        lowered = line.lower()
        if lowered in ("exit", "quit", "q"):
            print(f"\n{c.CYAN}Clutter controlled. Goodbye!{c.RESET}\n")
            break
        if lowered in ("help", "?"):
            print()
            print_commands()
            continue

        try:
            args = parser.parse_args(shlex.split(line))
        except SystemExit:
            print()
            continue
        except ValueError as e:
            print(f"{c.RED}Error parsing command: {e}{c.RESET}\n")
            continue

        print()
        dispatch(args)
        print_status_bar()
        print()


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command is None and not any([args.watch, args.undo, args.undo_last, args.target]):
        interactive_shell()
    else:
        dispatch(args)


if __name__ == "__main__":
    main()
