import argparse
import csv
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


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


def print_step(message):
    print(f"\n{Colors.BLUE}{Colors.BOLD}>>> {message}{Colors.RESET}")


def print_success(message):
    print(f"{Colors.GREEN}[OK] {message}{Colors.RESET}")


def print_warning(message):
    print(f"{Colors.YELLOW}[WARN] {message}{Colors.RESET}")


def print_error(message):
    print(f"{Colors.RED}[ERR] {message}{Colors.RESET}")


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
        print_warning(f"Requested icon was not found: {preferred_path}")

    default_icon = Path(DEFAULT_ICON)
    if default_icon.exists():
        return default_icon.resolve()

    icons = discover_icons()
    if not icons:
        return None

    if assume_yes or not sys.stdin.isatty():
        return icons[0].resolve()

    print(f"{Colors.CYAN}Found executable icons:{Colors.RESET}")
    for idx, icon in enumerate(icons, start=1):
        print(f"  {idx}. {icon}")
    print("  0. Build without an icon")

    while True:
        choice = input(f"{Colors.CYAN}Use which icon? [1]: {Colors.RESET}").strip()
        if not choice:
            return icons[0].resolve()
        if choice == "0":
            return None
        try:
            index = int(choice)
        except ValueError:
            print_warning("Please enter a number from the list.")
            continue
        if 1 <= index <= len(icons):
            return icons[index - 1].resolve()
        print_warning("That icon number is out of range.")


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
    print_warning(f"Waiting for {image_name} to exit. Press Ctrl+C to abort.")
    while True:
        processes = find_running_target_processes(app_name)
        if not processes:
            print_success(f"{image_name} is no longer running.")
            return
        time.sleep(1.0)


def timestamped_running_output(args, reason):
    new_name = locked_output_name(args.name)
    print_warning(reason)
    print_warning(f"Using alternate output name: {new_name}")
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
            print_warning(f"Terminating {describe_processes(processes)}.")
            terminate_processes(processes)
            time.sleep(0.5)
            processes = find_running_target_processes(args.name)
            if not processes:
                print_success(f"{image_name} was terminated.")
                return None
            raise SystemExit(f"{image_name} is still running after terminate attempt.")
        if mode == "timestamp":
            return timestamped_running_output(args, reason)
        if mode == "fail":
            print_error(reason)
            print(f"{Colors.CYAN}Close {image_name}, or run with --running-target wait, terminate, or timestamp.{Colors.RESET}")
            raise SystemExit(1)

        print_warning(reason)
        print(f"{Colors.CYAN}Choose: [c] closed/check again, [w] wait, [k] terminate, [t] timestamped build, [q] abort{Colors.RESET}")
        choice = input(f"{Colors.CYAN}Action [c]: {Colors.RESET}").strip().lower() or "c"
        if choice in {"c", "check", "closed"}:
            processes = find_running_target_processes(args.name)
            if not processes:
                print_success(f"{image_name} is no longer running.")
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
        print_warning("Please choose c, w, k, t, or q.")

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
        print_error(message)
        print(f"{Colors.CYAN}Tip: run with --locked-output timestamp to build beside the locked exe.{Colors.RESET}")
        raise SystemExit(1)

    new_name = locked_output_name(args.name)
    print_warning(message)
    print_warning(f"Using alternate output name: {new_name}")
    return new_name


def is_benign_hidden_import_warning(line):
    match = HIDDEN_IMPORT_RE.search(line)
    return bool(match and match.group(1) in BENIGN_HIDDEN_IMPORTS)


def classify_pyinstaller_line(line):
    if is_benign_hidden_import_warning(line):
        return Colors.DIM

    lower = line.lower()
    if "error" in lower or "failed" in lower or "traceback" in lower:
        return Colors.RED
    if "warning" in lower or "warn:" in lower or "missing" in lower:
        return Colors.YELLOW
    if "building" in lower or "completed successfully" in lower:
        return Colors.GREEN
    if "pyinstaller" in lower or "info:" in lower:
        return Colors.CYAN
    return Colors.DIM


def stream_command(command, suppress_benign_warnings=False):
    print(f"{Colors.DIM}{' '.join(command)}{Colors.RESET}\n")
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.rstrip()
        if suppress_benign_warnings and is_benign_hidden_import_warning(line):
            continue
        color = classify_pyinstaller_line(line)
        print(f"{color}{line}{Colors.RESET}")

    return process.wait()


def pyinstaller_command(args, icon_path):
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

    dsp_spec = importlib.util.find_spec("dsp_accel")
    if dsp_spec is not None:
        command.append("--hidden-import=dsp_accel")
        if dsp_spec.submodule_search_locations:
            command.append("--collect-submodules=dsp_accel")
        print_success("Rust DSP accelerator detected; including dsp_accel.")
    else:
        print_warning("Rust DSP accelerator not installed; build will use the Python fallback.")

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
        print_success(f"Removed {spec_path}")
    if args.clean_work and Path(args.work_dir).exists():
        shutil.rmtree(args.work_dir, ignore_errors=True)
        print_success(f"Removed {args.work_dir}/")


def verify_build(args):
    exe = executable_path(args.dist_dir, app_name=args.resolved_name, onefile=not args.one_dir)
    if exe.exists():
        print_success(f"Built executable: {exe}")
        return True
    print_error(f"Expected executable was not found: {exe}")
    return False


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build PyDSPMeters with PyInstaller.",
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

    print(f"{Colors.HEADER}{Colors.BOLD}   PyDSPMeters PyInstaller Builder    {Colors.RESET}")

    entry = Path(ENTRY_POINT)
    if not entry.exists():
        print_error(f"Could not find entry point: {ENTRY_POINT}")
        return 1

    pyinstaller_version = check_pyinstaller()
    if not pyinstaller_version:
        print_error("PyInstaller is not installed.")
        print(f"Run: {Colors.CYAN}pip install pyinstaller{Colors.RESET}")
        return 1
    print_success(f"PyInstaller {pyinstaller_version}")

    icon_path = choose_icon(args.icon, assume_yes=args.yes, no_icon=args.no_icon)
    if icon_path:
        print_success(f"Using icon: {icon_path}")
    else:
        print_warning("Building without an executable icon.")

    args.resolved_name = prepare_output_name(args)
    command = pyinstaller_command(args, icon_path)
    print_step("Building executable")
    return_code = stream_command(command, suppress_benign_warnings=args.suppress_benign_warnings)
    cleanup_artifacts(args)

    if return_code != 0:
        print_error(f"PyInstaller failed with exit code {return_code}.")
        print_warning("If the traceback mentions PermissionError on dist\\*.exe, close the running exe or rebuild with --locked-output timestamp.")
        return return_code

    if not verify_build(args):
        return 1

    if args.zip or args.one_dir:
        target_path = Path(args.dist_dir) / args.resolved_name
        if target_path.is_dir():
            print_step("Creating zip archive")
            archive_base = Path(args.dist_dir) / args.resolved_name
            zip_path = shutil.make_archive(str(archive_base), "zip", root_dir=args.dist_dir, base_dir=args.resolved_name)
            print_success(f"Created archive: {zip_path}")

    print_success("Build completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
