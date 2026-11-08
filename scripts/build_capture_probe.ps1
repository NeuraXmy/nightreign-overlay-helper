param([string]$OutputDirectory = "")
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path $PSScriptRoot -Parent
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $projectRoot "bin" }
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$vswhere = Join-Path ([Environment]::GetFolderPath('ProgramFilesX86')) "Microsoft Visual Studio/Installer/vswhere.exe"
if (-not (Test-Path -LiteralPath $vswhere)) { throw "Install Visual Studio C++ Build Tools and Windows SDK" }
$installation = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $installation) { throw "Visual Studio x64 C++ tools not found" }
$vcvars = Join-Path $installation "VC/Auxiliary/Build/vcvars64.bat"
# Import compiler variables into this process only; the user's environment is unchanged.
$setupCommand = 'call "{0}" >nul && set' -f $vcvars
$compilerEnvironment = & cmd.exe /d /c $setupCommand
if ($LASTEXITCODE -ne 0) { throw "C++ environment setup failed" }
foreach ($line in $compilerEnvironment) {
    if ($line -match '^([^=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process') }
}
$source = Join-Path $projectRoot "native/CaptureProbe/main.cpp"
$object = Join-Path $OutputDirectory "CaptureProbe.obj"
$executable = Join-Path $OutputDirectory "NightreignCaptureProbe.exe"
& cl.exe /nologo /std:c++17 /O2 /EHsc /W4 /MT /utf-8 /DUNICODE /D_UNICODE $source "/Fo$object" "/Fe$executable" /link /SUBSYSTEM:WINDOWS d3d12.lib dxgi.lib d2d1.lib dwrite.lib windowscodecs.lib ole32.lib user32.lib shell32.lib
if ($LASTEXITCODE -ne 0) { throw "Capture probe build failed" }
& $executable --self-test
if ($LASTEXITCODE -ne 0) { throw "Capture probe validator regression failed" }
Write-Output "Capture probe built: $executable"
