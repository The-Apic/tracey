"""Build the Tracey executable for this OS with PyInstaller.

    uv run scripts/build.py [--clean]

Windows: dist/Tracey-windows-<arch>.exe, a single self-contained executable.
macOS:   dist/Tracey.app, plus dist/Tracey-macos-<arch>.zip for distribution.

PyInstaller can't cross-compile, so each OS builds its own. CI runs this too.
All PyInstaller settings live here, the .spec file it generates is a throwaway.
"""

import argparse
import os
import platform
import plistlib
import subprocess
import sys
import time
from pathlib import Path

import PyInstaller.__main__

from tracey import APP_NAME, APP_VERSION

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
RESOURCES = SRC / "tracey" / "resources"
DIST = ROOT / "dist"
BUILD = ROOT / "build"
ARCHS = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}
BUNDLE_ID = "de.theapic.tracey"


def target() -> str:
    system = {"win32": "windows", "darwin": "macos"}.get(sys.platform)
    if system is None:
        sys.exit(f"Building on {sys.platform} isn't supported, only Windows and macOS")
    machine = platform.machine().lower()
    return f"{system}-{ARCHS.get(machine, machine)}"


def pyinstaller_options(clean: bool) -> list[str]:
    options = [
        str(SRC / "tracey" / "__main__.py"),
        f"--name={APP_NAME}",
        f"--paths={SRC}",
        f"--add-data={RESOURCES}{os.pathsep}tracey/resources",
        "--windowed",  # no console window
        "--noupx",
        "--noconfirm",
        f"--distpath={DIST}",
        f"--workpath={BUILD}",
        f"--specpath={BUILD}",  # keep the generated .spec out of the repository
    ]
    if sys.platform == "darwin":
        options += [
            "--onedir",
            f"--icon={RESOURCES / 'tracey.icns'}",
            f"--osx-bundle-identifier={BUNDLE_ID}",
        ]
    else:
        options += ["--onefile", f"--icon={RESOURCES / 'tracey.ico'}"]
    if clean:
        options.append("--clean")
    return options


def finish_app() -> None:
    """Set the app version, which PyInstaller's options can't, then re-sign.

    Changing Info.plist breaks the ad-hoc signature PyInstaller gave the app,
    and Apple silicon Macs refuse to start an app with a broken signature.
    """
    app = DIST / f"{APP_NAME}.app"
    plist = app / "Contents" / "Info.plist"
    with plist.open("rb") as fp:
        info = plistlib.load(fp)
    info["CFBundleShortVersionString"] = info["CFBundleVersion"] = APP_VERSION
    with plist.open("wb") as fp:
        plistlib.dump(info, fp)
    subprocess.run(
        ["codesign", "--force", "--deep", "--sign", "-", app],
        check=True,
    )


def package(name: str) -> Path:
    """Give the PyInstaller output its release name."""
    if sys.platform == "win32":
        output = DIST / f"{name}.exe"
        (DIST / f"{APP_NAME}.exe").replace(output)
        return output
    output = DIST / f"{name}.zip"
    output.unlink(missing_ok=True)
    # ditto keeps the framework symlinks and code signatures of the .app intact
    subprocess.run(
        ["ditto", "-c", "-k", "--keepParent", DIST / f"{APP_NAME}.app", output],
        check=True,
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--clean", action="store_true", help="drop PyInstaller's cache first"
    )
    args = parser.parse_args()

    name = f"{APP_NAME}-{target()}"
    print(f"building {name} {APP_VERSION}", flush=True)
    started = time.monotonic()

    PyInstaller.__main__.run(pyinstaller_options(args.clean))
    if sys.platform == "darwin":
        finish_app()

    output = package(name)
    size = output.stat().st_size / 1_000_000
    elapsed = time.monotonic() - started
    print(f"\n{output.relative_to(ROOT)} ({size:.0f} MB) built in {elapsed:.0f}s")


if __name__ == "__main__":
    main()
