# PyInstaller spec, builds the Windows .exe and the macOS .app:
#   uv run --group build pyinstaller packaging/tracey.spec
# PyInstaller injects Analysis, PYZ, EXE, COLLECT, BUNDLE and SPECPATH.

import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT / "src"))
from tracey import APP_NAME, APP_VERSION

RESOURCES = ROOT / "src" / "tracey" / "resources"

a = Analysis(
    [str(ROOT / "src" / "tracey" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    datas=[(str(RESOURCES), "tracey/resources")],
    # the stylesheet's check marks and chevrons are SVGs, loaded by Qt's svg plugin
    hiddenimports=["PySide6.QtSvg"],
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)

if sys.platform == "darwin":
    exe = EXE(
        pyz,
        a.scripts,
        exclude_binaries=True,
        name=APP_NAME,
        console=False,
        upx=False,
    )
    app = BUNDLE(
        COLLECT(exe, a.binaries, a.datas, name=APP_NAME, upx=False),
        name=f"{APP_NAME}.app",
        icon=str(RESOURCES / "tracey.icns"),
        bundle_identifier="de.theapic.tracey",
        version=APP_VERSION,
        info_plist={
            "CFBundleDisplayName": APP_NAME,
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,  # follow light / dark mode
        },
    )
else:
    # a single self-contained .exe
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        name=APP_NAME,
        icon=str(RESOURCES / "tracey.ico"),
        console=False,
        upx=False,
    )
