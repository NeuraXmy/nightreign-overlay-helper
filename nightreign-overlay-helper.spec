# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

import PyQt6


project_root = Path(SPECPATH)
pyqt_bin = Path(PyQt6.__file__).resolve().parent / "Qt6" / "bin"
qt_vc_runtime = [
    (str(path), "PyQt6/Qt6/bin")
    for path in pyqt_bin.glob("*140*.dll")
]

a = Analysis(
    [str(project_root / "src" / "app.py")],
    pathex=[str(project_root)],
    binaries=qt_vc_runtime + [
        (str(project_root / "native" / "MaaWin32Screencap.dll"), "native"),
    ],
    datas=[(str(project_root / "pyproject.toml"), ".")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# OpenCV 5 may expose its own ICU DLLs through PATH. PyInstaller can mistake
# those DLLs for Qt dependencies and place them at the archive root, where
# Windows loads them before Qt's expected dependencies. The ABI mismatch makes
# importing PyQt6.QtCore fail with WinError 127 on clean machines.
def is_foreign_root_icu(entry):
    destination = entry[0].replace("\\", "/").lower()
    return "/" not in destination and (
        destination in {"icuuc.dll", "icuin.dll"}
        or destination.startswith("icudt") and destination.endswith(".dll")
    )


a.binaries = [entry for entry in a.binaries if not is_foreign_root_icu(entry)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="nightreign-overlay-helper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    icon=str(project_root / "assets" / "icon.ico"),
)
