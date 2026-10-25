import argparse
import csv
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    from rich.console import Console, Group
    from rich.panel import Panel
    from rich.table import Table
    from rich.progress import (
        Progress,
        BarColumn,
        TextColumn,
        TimeElapsedColumn,
        SpinnerColumn,
        TaskProgressColumn,
    )
    from rich.live import Live
    from rich.text import Text
    from rich.markup import escape
    from rich import box
    _HAS_RICH = True
    console = Console()
except ImportError:
    _HAS_RICH = False
    console = None
    escape = lambda s: s


APP_NAME = "PyDSPMeters"
ENTRY_POINT = "main.pyw"
DEFAULT_ICON = "icon.ico"
BENIGN_HIDDEN_IMPORTS = {
    "pycparser.lextab",
    "pycparser.yacctab",
}
HIDDEN_IMPORT_RE = re.compile(r'Hidden import "([^"]+)" not found')

DEFAULT_EXCLUDES = [
    # Heavy AI/ML frameworks accidentally pulled in via transitive hooks (e.g. sympy)
    "torch",
    "torchvision",
    "torchaudio",
    "tensorflow",
    "tensorboard",
    "keras",
    "sympy",
    "IPython",
    "jupyter",
    "notebook",
    "matplotlib",
    "PIL",
    "Pillow",
    "cv2",
    "pandas",
    "jinja2",
    "fsspec",
    "cryptography",
    "pydantic",
    "pytest",
    "unittest",
    # Unused Qt modules (PyDSP only uses Core, Gui, Widgets)
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DAnimation",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQml",
    "PySide6.QtNetwork",
    "PySide6.QtSql",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtDesigner",
    "PySide6.QtXml",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtCharts",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSensors",
    "PySide6.QtPositioning",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtSerialPort",
    "PySide6.QtTest",
    # Unused third-party packages (superseded by Rust/NumPy)
    "scipy",
]


class Colors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


def enable_ansi():
    if sys.platform == "win32":
        os.system("")


_running_process = None


class BuildUI:
    def __init__(self, console, app_name=APP_NAME, total_steps=5):
        self.console = console
        self.app_name = app_name
        self.version = "v1.2.14.0"
        self.total_steps = total_steps
        self.current_step = 1
        self.step_title = "Initializing"
        self.sub_status = "Starting build pipeline..."
        self.log_buffer = []
        self.live = None
        self._interactive_paused = False
        self.is_interactive = bool(_HAS_RICH and self.console and self.console.is_terminal)

        if _HAS_RICH and self.console:
            self.progress = Progress(
                SpinnerColumn(),
                TextColumn("[bold cyan]{task.description}"),
                BarColumn(bar_width=None, style="dim white", complete_style="bold cyan", finished_style="bold green"),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                console=self.console,
            )
            self.task_id = self.progress.add_task("Overall Progress", total=100)
        else:
            self.progress = None
            self.task_id = None

    def pause(self):
        if self.live and self.live.is_started:
            self.live.stop()
            self._interactive_paused = True

    def resume(self):
        if self.live and self._interactive_paused:
            self.live.start()
            self._interactive_paused = False

    def render(self):
        term_h = self.console.size.height or 24
        logs_height = max(6, min(term_h - 10, 18))

        status_line = f"[bold white]Phase [{self.current_step}/{self.total_steps}]:[/bold white] [cyan]{escape(self.step_title)}[/cyan]"
        sub_line = f"[dim italic]› {escape(self.sub_status)}[/dim italic]"

        header_group = Group(
            Text.from_markup(f"{status_line}\n{sub_line}"),
            self.progress,
        )

        prog_panel = Panel(
            header_group,
            title=f"[bold cyan]{self.app_name}[/bold cyan] [dim]Distribution Build ({self.version})[/dim]",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(0, 2),
        )

        display_lines = self.log_buffer[-logs_height:] if self.log_buffer else ["[dim]Waiting for build activity...[/dim]"]
        log_text = Text.from_markup("\n".join(display_lines))
        logs_panel = Panel(
            log_text,
            title=f"[bold white]Build Output[/bold white] [dim]({len(self.log_buffer)} lines)[/dim]",
            border_style="blue",
            box=box.ROUNDED,
            height=logs_height + 2,
            padding=(0, 1),
        )

        return Group(prog_panel, logs_panel)

    def log_raw(self, line):
        if self.is_interactive:
            self.log_buffer.append(line)
            if self.live and not self._interactive_paused:
                self.live.update(self.render())
        else:
            if _HAS_RICH and self.console:
                self.console.print(line)
            else:
                print(line)

    def set_step(self, step, total, title, percent=None):
        self.current_step = step
        self.total_steps = total
        self.step_title = title
        self.sub_status = title
        if percent is not None and self.progress:
            self.progress.update(self.task_id, completed=percent)
        self.log_raw(f"[bold cyan]▶ [{step}/{total}][/bold cyan] [bold white]{escape(title)}[/bold white]")

    def set_status(self, status):
        self.sub_status = status
        if self.live and not self._interactive_paused:
            self.live.update(self.render())

    def update_progress(self, percent=None, advance=None):
        if not self.progress:
            return
        if percent is not None:
            self.progress.update(self.task_id, completed=percent)
        elif advance is not None:
            self.progress.advance(self.task_id, advance)
        if self.live and not self._interactive_paused:
            self.live.update(self.render())

    def log_ok(self, message):
        self.log_raw(f"  [bold green]✔[/bold green] {message}")

    def log_warn(self, message):
        self.log_raw(f"  [bold yellow]▲[/bold yellow] [yellow]{message}[/yellow]")

    def log_err(self, message):
        self.log_raw(f"  [bold red]✖[/bold red] [red]{message}[/red]")

    def log_info(self, message):
        self.log_raw(f"  [dim]› {message}[/dim]")

    def handle_cancel(self):
        global _running_process
        if _running_process and _running_process.poll() is None:
            try:
                _running_process.terminate()
                _running_process.wait(timeout=2.0)
            except Exception:
                try:
                    _running_process.kill()
                except Exception:
                    pass

        if self.live and self.live.is_started:
            try:
                self.live.stop()
            except Exception:
                pass

        if _HAS_RICH and self.console:
            self.console.print("\n[bold yellow]▲ Build cancelled by user (Ctrl+C).[/bold yellow]\n")
        else:
            print("\n[WARN] Build cancelled by user (Ctrl+C).\n")


@contextmanager
def live_ui_context(ui):
    if not ui.is_interactive:
        yield ui
        return
    with Live(ui.render(), console=ui.console, refresh_per_second=10) as live:
        ui.live = live
        try:
            yield ui
        finally:
            ui.live = None


_active_ui = None


def get_ui():
    global _active_ui
    if _active_ui is None:
        _active_ui = BuildUI(console)
    return _active_ui


def log_step(step_idx, total_steps, title):
    pct_map = {1: 15, 2: 30, 3: 45, 4: 55, 5: 90}
    get_ui().set_step(step_idx, total_steps, title, percent=pct_map.get(step_idx, 0))


def log_ok(message):
    get_ui().log_ok(message)


def log_warn(message):
    get_ui().log_warn(message)


def log_err(message):
    get_ui().log_err(message)


def log_info(message):
    get_ui().log_info(message)


# Backwards-compatible aliases
print_step = lambda msg: log_step(0, 0, msg)
print_success = log_ok
print_warning = log_warn
print_error = log_err


def path_arg(value):
    if value is None:
        return None
    value = value.strip()
    return value or None


def discover_icons():
    roots = [Path("."), Path("app"), Path("assets"), Path("resources")]
    icons = []
    for root in roots:
        if not root.exists():
            continue
        icons.extend(sorted(root.glob("*.ico")))
    unique = []
    seen = set()
    for icon in icons:
        resolved = icon.resolve()
        if resolved not in seen:
            unique.append(icon)
            seen.add(resolved)
    return unique


def choose_icon(preferred_path=None, assume_yes=False, no_icon=False):
    if no_icon:
        return None

    if preferred_path:
        preferred = Path(preferred_path)
        if preferred.exists():
            return preferred.resolve()
        log_warn(f"Requested icon was not found: {preferred_path}")

    default_icon = Path(DEFAULT_ICON)
    if default_icon.exists():
        return default_icon.resolve()

    icons = discover_icons()
    if not icons:
        return None

    if assume_yes or not sys.stdin.isatty():
        return icons[0].resolve()

    get_ui().pause()
    try:
        if _HAS_RICH and console:
            console.print("  [cyan]Available executable icons:[/cyan]")
            for idx, icon in enumerate(icons, start=1):
                console.print(f"    [dim]{idx}.[/dim] {icon}")
            console.print("    [dim]0.[/dim] Build without an icon")
        else:
            print("Found executable icons:")
            for idx, icon in enumerate(icons, start=1):
                print(f"  {idx}. {icon}")
            print("  0. Build without an icon")

        while True:
            prompt = "Use which icon? [1]: "
            choice = input(prompt).strip()
            if not choice:
                return icons[0].resolve()
            if choice == "0":
                return None
            try:
                index = int(choice)
            except ValueError:
                log_warn("Please enter a number from the list.")
                continue
            if 1 <= index <= len(icons):
                return icons[index - 1].resolve()
            log_warn("That icon number is out of range.")
    finally:
        get_ui().resume()


def check_pyinstaller():
    try:
        result = subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return result.stdout.strip().splitlines()[0] if result.stdout.strip() else "unknown"


def data_separator():
    return ";" if sys.platform == "win32" else ":"


def executable_path(dist_dir, app_name=APP_NAME, onefile=True):
    suffix = ".exe" if sys.platform == "win32" else ""
    if onefile:
        return Path(dist_dir) / f"{app_name}{suffix}"
    return Path(dist_dir) / app_name / f"{app_name}{suffix}"


def locked_output_name(app_name):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{app_name}-{stamp}"


def executable_process_name(app_name):
    stem = Path(app_name).stem
    return f"{stem}.exe" if sys.platform == "win32" else stem


def find_running_target_processes(app_name):
    if sys.platform != "win32":
        return []

    image_name = executable_process_name(app_name)
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return []

    processes = []
    for row in csv.reader(result.stdout.splitlines()):
        if len(row) < 2:
            continue
        name = row[0].strip()
        if name.lower() != image_name.lower():
            continue
        processes.append(
            {
                "image": name,
                "pid": row[1].strip(),
                "session": row[2].strip() if len(row) > 2 else "",
                "memory": row[4].strip() if len(row) > 4 else "",
            }
        )
    return processes


def describe_processes(processes):
    return ", ".join(
        f"{process['image']} pid={process['pid']}"
        for process in processes
    )


def terminate_processes(processes):
    for process in processes:
        subprocess.run(
            ["taskkill", "/PID", process["pid"], "/T", "/F"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )


def wait_for_target_process_exit(app_name):
    image_name = executable_process_name(app_name)
    log_warn(f"Waiting for {image_name} to exit. Press Ctrl+C to abort.")
    while True:
        processes = find_running_target_processes(app_name)
        if not processes:
            log_ok(f"{image_name} is no longer running.")
            return
        time.sleep(1.0)


def timestamped_running_output(args, reason):
    new_name = locked_output_name(args.name)
    log_warn(reason)
    log_warn(f"Using alternate output name: {new_name}")
    return new_name


def handle_running_target(args):
    processes = find_running_target_processes(args.name)
    if not processes:
        return None

    image_name = executable_process_name(args.name)
    reason = f"{image_name} is running ({describe_processes(processes)}). PyInstaller cannot replace it."
    mode = args.running_target

    if mode == "prompt" and not sys.stdin.isatty():
        mode = "timestamp" if args.locked_output == "timestamp" else "fail"

    while processes:
        if mode == "wait":
            wait_for_target_process_exit(args.name)
            return None
        if mode == "terminate":
            log_warn(f"Terminating {describe_processes(processes)}.")
            terminate_processes(processes)
            time.sleep(0.5)
            processes = find_running_target_processes(args.name)
            if not processes:
                log_ok(f"{image_name} was terminated.")
                return None
            raise SystemExit(f"{image_name} is still running after terminate attempt.")
        if mode == "timestamp":
            return timestamped_running_output(args, reason)
        if mode == "fail":
            log_err(reason)
            log_info(f"Close {image_name}, or run with --running-target wait, terminate, or timestamp.")
            raise SystemExit(1)

        get_ui().pause()
        try:
            log_warn(reason)
            prompt_opts = "Choose: [c] closed/check again, [w] wait, [k] terminate, [t] timestamped build, [q] abort: "
            choice = input(prompt_opts).strip().lower() or "c"
        finally:
            get_ui().resume()

        if choice in {"c", "check", "closed"}:
            processes = find_running_target_processes(args.name)
            if not processes:
                log_ok(f"{image_name} is no longer running.")
                return None
            continue
        if choice in {"w", "wait"}:
            mode = "wait"
            continue
        if choice in {"k", "kill", "terminate"}:
            mode = "terminate"
            continue
        if choice in {"t", "timestamp"}:
            mode = "timestamp"
            continue
        if choice in {"q", "quit", "abort"}:
            raise SystemExit(1)
        log_warn("Please choose c, w, k, t, or q.")

    return None


def can_replace_file(path):
    path = Path(path)
    if not path.exists():
        return True

    probe = path.with_name(f".{path.name}.replace-probe")
    try:
        if probe.exists():
            probe.unlink()
        path.rename(probe)
        probe.rename(path)
        return True
    except OSError:
        return False
    finally:
        if probe.exists() and not path.exists():
            try:
                probe.rename(path)
            except OSError:
                pass


def prepare_output_name(args):
    running_output_name = handle_running_target(args)
    if running_output_name:
        return running_output_name

    target = executable_path(args.dist_dir, app_name=args.name, onefile=not args.one_dir)
    if can_replace_file(target):
        return args.name

    message = (
        f"{target} is locked. Close the running app/exe, close any Explorer preview, "
        "or let this build use a timestamped executable name."
    )
    if args.locked_output == "fail":
        log_err(message)
        log_info("Tip: run with --locked-output timestamp to build beside the locked exe.")
        raise SystemExit(1)

    new_name = locked_output_name(args.name)
    log_warn(message)
    log_warn(f"Using alternate output name: {new_name}")
    return new_name


def is_benign_hidden_import_warning(line):
    match = HIDDEN_IMPORT_RE.search(line)
    return bool(match and match.group(1) in BENIGN_HIDDEN_IMPORTS)


def stream_command(command, suppress_benign_warnings=False, verbose=False):
    global _running_process
    ui = get_ui()
    ui.log_raw(f"  [dim]$ {' '.join(command)}[/dim]\n")

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    _running_process = process

    assert process.stdout is not None
    milestone_keywords = [
        ("analyzing", 55),
        ("looking for", 60),
        ("checking", 62),
        ("processing", 65),
        ("compiling", 70),
        ("building pkg", 75),
        ("building exe", 85),
        ("building col", 88),
    ]
    last_milestone = ""

    try:
        for raw_line in process.stdout:
            line = raw_line.rstrip()
            if suppress_benign_warnings and is_benign_hidden_import_warning(line):
                continue

            lower = line.lower()
            is_err = "error" in lower or "failed" in lower or "traceback" in lower
            is_warn = "warning" in lower or "warn:" in lower

            if is_err:
                ui.log_raw(f"  [bold red]✖ {escape(line)}[/bold red]")
            elif is_warn:
                ui.log_raw(f"  [yellow]▲ {escape(line)}[/yellow]")
            elif verbose:
                ui.log_raw(f"  [dim]{escape(line)}[/dim]")
            else:
                for kw, pct in milestone_keywords:
                    if kw in lower and line != last_milestone:
                        last_milestone = line
                        clean = re.sub(r"^\d+\s+(INFO|DEBUG):\s*", "", line)
                        ui.set_status(clean)
                        ui.update_progress(percent=pct)
                        ui.log_raw(f"  [dim cyan]›[/dim cyan] [dim]{escape(clean)}[/dim]")
                        break

        ret = process.wait()
        _running_process = None
        return ret
    except KeyboardInterrupt:
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=2.0)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
        _running_process = None
        raise


def pyinstaller_command(args, icon_path, dsp_spec=None):
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--windowed",
        f"--name={args.resolved_name}",
        f"--distpath={args.dist_dir}",
        f"--workpath={args.work_dir}",
        "--clean",
        "--hidden-import=app",
    ]

    if dsp_spec is not None:
        command.append("--hidden-import=dsp_accel")
        if dsp_spec.submodule_search_locations:
            command.append("--collect-submodules=dsp_accel")

    if args.one_dir:
        command.append("--onedir")
    else:
        command.append("--onefile")

    if icon_path:
        command.append(f"--icon={icon_path}")
        command.append(f"--add-data={icon_path}{data_separator()}.")

    for item in args.add_data:
        command.append(f"--add-data={item}")

    for item in args.hidden_import:
        command.append(f"--hidden-import={item}")

    if not getattr(args, "no_default_excludes", False):
        for mod in DEFAULT_EXCLUDES:
            command.append(f"--exclude-module={mod}")

    for item in getattr(args, "exclude", []):
        command.append(f"--exclude-module={item}")

    if args.debug_imports:
        command.append("--debug=imports")

    command.append(ENTRY_POINT)
    return command


def cleanup_artifacts(args):
    if args.keep_spec:
        return
    spec_path = Path(f"{args.resolved_name}.spec")
    if spec_path.exists():
        spec_path.unlink()
        log_ok(f"Cleaned build spec: [dim]{spec_path}[/dim]")
    if args.clean_work and Path(args.work_dir).exists():
        shutil.rmtree(args.work_dir, ignore_errors=True)
        log_ok(f"Cleaned temporary work directory: [dim]{args.work_dir}/[/dim]")


def verify_build(args):
    exe = executable_path(args.dist_dir, app_name=args.resolved_name, onefile=not args.one_dir)
    return exe.exists()


def print_summary(args, exe_path, elapsed_sec, zip_path=None):
    if not _HAS_RICH:
        log_ok(f"Build completed in {elapsed_sec:.1f}s")
        print(f"Output: {exe_path}")
        if zip_path:
            print(f"Archive: {zip_path}")
        return

    size_str = "N/A"
    target = Path(exe_path)
    if target.exists():
        if target.is_file():
            size_mb = target.stat().st_size / (1024 * 1024)
            size_str = f"{size_mb:.1f} MB"
        elif target.is_dir():
            total = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
            size_str = f"{total / (1024 * 1024):.1f} MB"

    table = Table(box=box.ROUNDED, show_header=False, border_style="cyan", padding=(0, 2))
    table.add_column("Property", style="bold cyan")
    table.add_column("Value", style="white")

    table.add_row("Status", "[bold green]✔ Build Succeeded[/bold green]")
    table.add_row("Target", f"[bold]{args.resolved_name}[/bold]")
    table.add_row("Mode", "[magenta]onedir[/magenta]" if args.one_dir else "[magenta]onefile[/magenta]")
    table.add_row("Location", f"[dim]{exe_path}[/dim]")
    table.add_row("Bundle Size", f"[bold yellow]{size_str}[/bold yellow]")
    if zip_path and Path(zip_path).exists():
        zip_mb = Path(zip_path).stat().st_size / (1024 * 1024)
        table.add_row("Zip Package", f"[green]{zip_path}[/green] [dim]({zip_mb:.1f} MB)[/dim]")
    table.add_row("Elapsed", f"[bold white]{elapsed_sec:.2f}s[/bold white]")

    console.print()
    console.print(table)
    console.print()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build PyDSPMeters with PyInstaller (NPM-styled CLI).",
    )
    parser.add_argument("--icon", type=path_arg, default=DEFAULT_ICON, help="Executable icon path. Empty string enables auto-detect.")
    parser.add_argument("--no-icon", action="store_true", help="Build without an executable icon.")
    parser.add_argument("--yes", action="store_true", help="Use the first discovered icon without prompting.")
    parser.add_argument("--one-dir", action="store_true", help="Build an onedir distribution instead of onefile.")
    parser.add_argument("--name", default=APP_NAME, help="Executable/app name passed to PyInstaller.")
    parser.add_argument("--locked-output", choices=["timestamp", "fail"], default="timestamp", help="What to do when the target executable is locked.")
    parser.add_argument("--running-target", choices=["prompt", "wait", "terminate", "timestamp", "fail"], default="prompt", help="What to do when the target executable is already running.")
    parser.add_argument("--dist-dir", default="dist", help="PyInstaller output directory.")
    parser.add_argument("--work-dir", default="build", help="PyInstaller temporary work directory.")
    parser.add_argument("--keep-spec", action="store_true", help="Keep the generated .spec file.")
    parser.add_argument("--no-clean-work", action="store_false", dest="clean_work", help="Keep the PyInstaller work directory.")
    parser.add_argument("--debug-imports", action="store_true", help="Enable PyInstaller import debug output.")
    parser.add_argument("--verbose", action="store_true", help="Show full PyInstaller compiler logs.")
    parser.add_argument("--suppress-benign-warnings", action="store_true", help="Hide known harmless PyInstaller optional hidden-import warnings.")
    parser.add_argument("--hidden-import", action="append", default=[], help="Extra hidden import to pass to PyInstaller.")
    parser.add_argument("--exclude", action="append", default=[], help="Extra module to exclude from PyInstaller bundle.")
    parser.add_argument("--no-default-excludes", action="store_true", help="Disable default module exclusions.")
    parser.add_argument("--zip", action="store_true", help="Create a .zip archive of the dist output.")
    parser.add_argument("--add-data", action="append", default=[], help=f"Extra PyInstaller data entry, e.g. source{data_separator()}dest.")
    return parser.parse_args()


def build():
    enable_ansi()
    args = parse_args()
    start_time = time.time()
    ui = get_ui()

    # Detect version from main.pyw
    version = "v1.2.14.0"
    try:
        with open(ENTRY_POINT, "r", encoding="utf-8") as f:
            match = re.search(r'["\'](v\d+\.\d+\.\d+\.\d+)["\']', f.read())
            if match:
                version = match.group(1)
    except Exception:
        pass
    ui.version = version

    exe_target = None
    zip_path = None
    return_code = 0

    try:
        with live_ui_context(ui):
            # Step 1: Environment & Tools
            log_step(1, 5, "Resolving build environment & tools")
            entry = Path(ENTRY_POINT)
            if not entry.exists():
                log_err(f"Could not find entry point: {ENTRY_POINT}")
                return 1
            log_ok(f"Entry point verified: [cyan]{ENTRY_POINT}[/cyan]")

            pyinstaller_version = check_pyinstaller()
            if not pyinstaller_version:
                log_err("PyInstaller is not installed.")
                log_info("Run: pip install pyinstaller")
                return 1
            log_ok(f"PyInstaller [cyan]{pyinstaller_version}[/cyan]")
            log_ok(f"Python [dim]{sys.version.split()[0]} ({sys.executable})[/dim]")

            # Step 2: Native DSP Accelerator
            log_step(2, 5, "Inspecting native DSP accelerator")
            dsp_spec = importlib.util.find_spec("dsp_accel")
            if dsp_spec is not None:
                log_ok("Rust DSP accelerator active [dim](dsp_accel: AVX2/SIMD)[/dim]")
            else:
                log_warn("Rust DSP accelerator not installed (bundle will use pure-Python/NumPy fallback)")

            # Step 3: Assets & Exclusions
            log_step(3, 5, "Configuring assets & module exclusions")
            icon_path = choose_icon(args.icon, assume_yes=args.yes, no_icon=args.no_icon)
            if icon_path:
                log_ok(f"Executable icon: [cyan]{icon_path.name}[/cyan] [dim]({icon_path})[/dim]")
            else:
                log_warn("Building without an executable icon")

            args.resolved_name = prepare_output_name(args)
            log_ok(f"Resolved bundle name: [bold]{args.resolved_name}[/bold]")
            if not getattr(args, "no_default_excludes", False):
                log_ok(f"Excluded [cyan]{len(DEFAULT_EXCLUDES)}[/cyan] heavy modules [dim](AI/ML, QtWebEngine, 3D)[/dim]")

            # Step 4: Bundling Executable
            log_step(4, 5, "Bundling executable with PyInstaller")
            command = pyinstaller_command(args, icon_path, dsp_spec=dsp_spec)
            t_bundle_start = time.time()
            return_code = stream_command(
                command,
                suppress_benign_warnings=args.suppress_benign_warnings,
                verbose=getattr(args, "verbose", False),
            )
            t_bundle = time.time() - t_bundle_start
            cleanup_artifacts(args)

            if return_code != 0:
                log_err(f"PyInstaller failed with exit code {return_code}.")
                log_warn("If the traceback mentions PermissionError on dist\\*.exe, close the running exe or rebuild with --locked-output timestamp.")
            else:
                log_ok(f"Compilation finished in [bold white]{t_bundle:.1f}s[/bold white]")

            if return_code != 0:
                return return_code

            # Step 5: Packaging & Finalizing
            log_step(5, 5, "Finalizing distribution & packaging")
            exe_target = executable_path(args.dist_dir, app_name=args.resolved_name, onefile=not args.one_dir)
            if not verify_build(args):
                log_err(f"Expected executable was not found: {exe_target}")
                return 1
            log_ok(f"Verified executable: [cyan]{exe_target}[/cyan]")

            if args.zip or args.one_dir:
                target_path = Path(args.dist_dir) / args.resolved_name
                if target_path.is_dir():
                    archive_base = Path(args.dist_dir) / args.resolved_name
                    zip_path = shutil.make_archive(str(archive_base), "zip", root_dir=args.dist_dir, base_dir=args.resolved_name)
                    log_ok(f"Created release archive: [green]{zip_path}[/green]")

            ui.update_progress(percent=100)
            ui.set_status("Build complete!")

    except KeyboardInterrupt:
        ui.handle_cancel()
        return 130

    total_elapsed = time.time() - start_time
    if exe_target:
        print_summary(args, exe_target, total_elapsed, zip_path)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(build())
    except KeyboardInterrupt:
        if _HAS_RICH and console:
            console.print("\n[bold yellow]▲ Build cancelled by user (Ctrl+C).[/bold yellow]\n")
        else:
            print("\n[WARN] Build cancelled by user (Ctrl+C).\n")
        sys.exit(130)
