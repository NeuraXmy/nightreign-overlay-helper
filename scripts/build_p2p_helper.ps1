# Run on Windows with the .NET 8 SDK. Runtime behaviour and publish options match the legacy project.
param(
    [string]$OutputDirectory = "",
    [switch]$NoSingleFile
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path $PSScriptRoot -Parent
$project = Join-Path $projectRoot "native/NightreignP2PHelper/NightreignP2PHelper.csproj"
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $projectRoot "bin" }
dotnet restore $project --locked-mode
if ($LASTEXITCODE -ne 0) { throw "P2P helper restore failed" }
$singleFile = if ($NoSingleFile) { "false" } else { "true" }
dotnet publish $project -c Release -r win-x64 --self-contained true "-p:PublishSingleFile=$singleFile" "-p:IncludeNativeLibrariesForSelfExtract=$singleFile" -p:PublishTrimmed=false -o $OutputDirectory --no-restore
if ($LASTEXITCODE -ne 0) { throw "P2P helper publish failed" }
$requiredFiles = @("NightreignP2PHelper.exe", "amd64/KernelTraceControl.dll", "amd64/msdia140.dll")
foreach ($file in $requiredFiles) {
    if (-not (Test-Path (Join-Path $OutputDirectory $file) -PathType Leaf)) {
        throw "Missing P2P runtime file: $file"
    }
}
$notices = Join-Path $projectRoot "native/THIRD-PARTY-NOTICES.txt"
$licenses = Join-Path $projectRoot "native/licenses"
$thirdParty = Join-Path (Split-Path $OutputDirectory -Parent) "third-party"
New-Item -ItemType Directory -Force $thirdParty | Out-Null
Copy-Item $notices $thirdParty -Force
Copy-Item $licenses $thirdParty -Recurse -Force
