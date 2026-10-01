"""Build the Tracey executable for this OS with PyInstaller.

    uv run scripts/build.py [--clean]

Windows: dist/Tracey-windows-<arch>.exe, a single self-contained executable.
macOS:   dist/Tracey.app, plus dist/Tracey-macos-<arch>.zip for distribution.

PyInstaller can't cross-compile, so each OS builds its own. CI runs this too.
"""

import argparse
import platform
import subprocess
import sys
import time
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "packaging" / "tracey.spec"
DIST = ROOT / "dist"
BUILD = ROOT / "build"
ARCHS = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}


def target() -> str:
    system = {"win32": "windows", "darwin": "macos"}.get(sys.platform)
    if system is None:
        sys.exit(f"Building on {sys.platform} isn't supported, only Windows and macOS")
    machine = platform.machine().lower()
    return f"{system}-{ARCHS.get(machine, machine)}"


def package(name: str) -> Path:
    """Give the PyInstaller output its release name."""
    if sys.platform == "win32":
        output = DIST / f"{name}.exe"
        (DIST / "Tracey.exe").replace(output)
        return output
    output = DIST / f"{name}.zip"
    output.unlink(missing_ok=True)
    # ditto keeps the framework symlinks and code signatures of the .app intact
    subprocess.run(
        ["ditto", "-c", "-k", "--keepParent", DIST / "Tracey.app", output],
        check=True,
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--clean", action="store_true", help="drop PyInstaller's cache first"
    )
    args = parser.parse_args()

    name = f"Tracey-{target()}"
    print(f"building {name}", flush=True)
    started = time.monotonic()

    options = [str(SPEC), "--noconfirm", f"--distpath={DIST}", f"--workpath={BUILD}"]
    if args.clean:
        options.append("--clean")
    PyInstaller.__main__.run(options)

    output = package(name)
    size = output.stat().st_size / 1_000_000
    elapsed = time.monotonic() - started
    print(f"\n{output.relative_to(ROOT)} ({size:.0f} MB) built in {elapsed:.0f}s")


if __name__ == "__main__":
    main()
