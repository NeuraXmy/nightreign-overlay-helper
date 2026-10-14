# ruff: noqa: F821
"""Windows onedir bundle; package-relative resources stay beside their modules."""

from pathlib import Path

import PyQt6
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

project_root = Path(SPECPATH)
package_root = project_root / "src" / "nightreign_overlay"
capture_dll = package_root / "plugins" / "capture" / "native" / "MaaWin32Screencap.dll"
if not capture_dll.is_file():
    raise FileNotFoundError(f"Missing capture runtime: {capture_dll}")

pyqt_bin = Path(PyQt6.__file__).resolve().parent / "Qt6" / "bin"
qt_vc_runtime = [(str(path), "PyQt6/Qt6/bin") for path in pyqt_bin.glob("*140*.dll")]

a = Analysis(
    [str(package_root / "__main__.py")],
    pathex=[str(project_root / "src")],
    binaries=[*qt_vc_runtime, (str(capture_dll), "nightreign_overlay/plugins/capture/native")],
    datas=[
        *collect_data_files("nightreign_overlay", excludes=["**/*.dll"]),
        *collect_data_files("qfluentwidgets"),
        (str(project_root / "LICENSE"), "."),
        (str(project_root / "README.md"), "."),
    ],
    # Plugin discovery and pynput's platform backends use dynamic imports.
    hiddenimports=[
        "mss.windows",
        *collect_submodules("nightreign_overlay.plugins"),
        "pynput.keyboard._win32",
        "pynput.mouse._win32",
        "pynput._util.win32",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)


def is_foreign_root_icu(entry):
    """Retain the legacy fix for OpenCV DLLs shadowing Qt's ICU dependencies."""
    destination = entry[0].replace("\\", "/").lower()
    return "/" not in destination and (
        destination in {"icuuc.dll", "icuin.dll"}
        or (destination.startswith("icudt") and destination.endswith(".dll"))
    )


a.binaries = [entry for entry in a.binaries if not is_foreign_root_icu(entry)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="nightreign-overlay-helper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    contents_directory="_internal",
    icon=str(package_root / "resources" / "icons" / "app.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="nightreign-overlay-helper",
)
