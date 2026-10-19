@echo off
setlocal
chcp 65001 >nul
title Nightreign Overlay Helper Build
pushd "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    echo Please install uv and add it to PATH before building.
    goto build_failed
)
where dotnet >nul 2>nul
if errorlevel 1 (
    echo Please install the .NET 8 SDK before building.
    goto build_failed
)

:: Release builds use Python 3.13 on Windows x64
uv sync --locked --python 3.13 --group build
if errorlevel 1 goto build_failed
uv run --no-sync python -c "import struct, sys; sys.exit(0 if sys.platform == 'win32' and struct.calcsize('P') == 8 else 'Windows x64 Python is required')"
if errorlevel 1 goto build_failed
uv run --no-sync python scripts\prepare_release_licenses.py --check-tree
if errorlevel 1 goto build_failed

:: Keep the helper and its .NET/native dependencies unpacked too.
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_p2p_helper.ps1 -OutputDirectory "%cd%\build\p2p\bin" -NoSingleFile
if errorlevel 1 goto build_failed

uv run --no-sync pyinstaller --noconfirm --clean --distpath dist --workpath build\pyinstaller nightreign-overlay-helper.spec
if errorlevel 1 goto build_failed

xcopy /E /I /Y "build\p2p\bin" "dist\nightreign-overlay-helper\bin" >nul
if errorlevel 1 goto build_failed
xcopy /E /I /Y "build\p2p\third-party" "dist\nightreign-overlay-helper\third-party" >nul
if errorlevel 1 goto build_failed
copy /Y LICENSE "dist\nightreign-overlay-helper\LICENSE" >nul
if errorlevel 1 goto build_failed
copy /Y README.md "dist\nightreign-overlay-helper\README.md" >nul
if errorlevel 1 goto build_failed
uv run --no-sync python scripts\prepare_release_licenses.py
if errorlevel 1 goto build_failed

echo Build complete: %cd%\dist\nightreign-overlay-helper
echo Distribute the entire folder, including _internal, bin and third-party.
popd
if not defined CI pause
exit /b 0

:build_failed
echo Build failed. See the error above.
popd
if not defined CI pause
exit /b 1
