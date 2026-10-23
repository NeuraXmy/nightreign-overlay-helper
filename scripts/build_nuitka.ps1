# Build from a clean Windows x64 checkout; use the same distribution contract as build.bat.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Program failed with exit code $LASTEXITCODE"
    }
}

Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    Invoke-Checked uv @('sync', '--locked', '--python', '3.13', '--group', 'build', '--group', 'nuitka')
    # Pass code through stdin so Windows PowerShell 5.1 preserves Python quotes.
    @'
import struct, sys
sys.exit(0 if sys.platform == "win32" and struct.calcsize("P") == 8 else "Windows x64 Python is required")
'@ | & uv run --no-sync python -
    if ($LASTEXITCODE -ne 0) { throw "Python platform check failed with exit code $LASTEXITCODE" }
    Invoke-Checked uv @('run', '--no-sync', 'python', 'scripts/prepare_release_licenses.py', '--check-tree')

    & "$PSScriptRoot/build_p2p_helper.ps1" -OutputDirectory "$PWD/build/p2p/bin" -NoSingleFile
    if ($LASTEXITCODE -ne 0) { throw 'P2P helper build failed' }
    $env:NROH_TEST_NATIVE_HELPER = "$PWD/build/p2p/bin/NightreignP2PHelper.exe"
    try {
        Invoke-Checked uv @('run', '--no-sync', 'pytest', '-q', 'tests/native/test_helper_startup.py')
    } finally {
        Remove-Item Env:NROH_TEST_NATIVE_HELPER -ErrorAction SilentlyContinue
    }

    $nuitkaArguments = @(
        'run', '--no-sync', 'python', '-m', 'nuitka',
        '--mode=standalone', '--msvc=latest', '--assume-yes-for-downloads', '--jobs=2',
        '--enable-plugin=pyqt6', '--include-qt-plugins=sensible,multimedia',
        '--include-package=nightreign_overlay', '--include-package-data=nightreign_overlay',
        '--include-package-data=qfluentwidgets',
        '--include-module=mss.windows',
        '--include-module=pynput.keyboard._win32', '--include-module=pynput.mouse._win32',
        '--include-module=pynput._util.win32', '--include-module=scripts.check_runtime_resources',
        '--user-package-configuration-file=scripts/nuitka-package.config.yml',
        '--windows-console-mode=disable', '--windows-uac-admin',
        '--windows-icon-from-ico=src/nightreign_overlay/resources/icons/app.ico',
        '--output-filename=nightreign-overlay-helper.exe', '--output-dir=build/nuitka',
        '--report=build/nuitka/compilation-report.xml', 'scripts/nuitka_entry.py'
    )
    # Make the repository's namespace package (scripts) visible alongside the src layout.
    $previousPythonPath = $env:PYTHONPATH
    $env:PYTHONPATH = "$PWD;$PWD/src"
    try {
        Invoke-Checked uv $nuitkaArguments
    } finally {
        $env:PYTHONPATH = $previousPythonPath
    }

    $bundle = 'dist/nightreign-overlay-helper'
    if (Test-Path $bundle) { Remove-Item $bundle -Recurse -Force }
    New-Item -ItemType Directory -Force dist | Out-Null
    Copy-Item 'build/nuitka/nuitka_entry.dist' $bundle -Recurse
    Copy-Item 'build/p2p/bin' "$bundle/bin" -Recurse
    Copy-Item 'build/p2p/third-party' "$bundle/third-party" -Recurse
    Copy-Item LICENSE, README.md $bundle
    Invoke-Checked uv @('run', '--no-sync', 'python', 'scripts/prepare_release_licenses.py')
    Write-Host "Build complete: $PWD/$bundle"
} finally {
    Pop-Location
}
