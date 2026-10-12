@echo off
setlocal
chcp 65001 >nul
title NightReign Overlay Helper Build Script
set "current_dir=%cd%"

:: 检查 uv 是否存在
where uv >nul 2>nul
if %errorlevel% equ 0 goto run_main

:: 安装 uv
echo 未检测到 uv，正在安装...
powershell -ExecutionPolicy Bypass -Command "irm https://gitee.com/wangnov/uv-custom/releases/download/latest/uv-installer-custom.ps1     | iex"

call :refresh_path
:: 验证 uv 是否可用
where uv >nul 2>nul
if %errorlevel% neq 0 (
    echo 安装 uv 后仍未找到，请检查安装路径
    pause
    exit /b 1
)
:: ===================================

:run_main
cd /d "%current_dir%"

uv sync
if errorlevel 1 goto build_failed

dotnet restore native\NightreignP2PHelper\NightreignP2PHelper.csproj --locked-mode
if errorlevel 1 goto build_failed
dotnet publish native\NightreignP2PHelper\NightreignP2PHelper.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -p:PublishTrimmed=false -o "build\NightreignP2PHelper" --no-restore
if errorlevel 1 goto build_failed

uv run pyinstaller --noconfirm --clean --distpath "dist\nightreign-overlay-helper" --workpath "build\pyinstaller" nightreign-overlay-helper.spec
if errorlevel 1 goto build_failed

xcopy /E /I /Y "assets" "dist\nightreign-overlay-helper\assets"
xcopy /E /I /Y "data" "dist\nightreign-overlay-helper\data"
copy "manual.txt" "dist\nightreign-overlay-helper\manual.txt"
copy "config.yaml" "dist\nightreign-overlay-helper\config.yaml"
if errorlevel 1 goto build_failed

if not exist "dist\nightreign-overlay-helper\bin" mkdir "dist\nightreign-overlay-helper\bin"
if not exist "dist\nightreign-overlay-helper\third-party" mkdir "dist\nightreign-overlay-helper\third-party"
copy "build\NightreignP2PHelper\NightreignP2PHelper.exe" "dist\nightreign-overlay-helper\bin\NightreignP2PHelper.exe"
if errorlevel 1 goto build_failed
xcopy /E /I /Y "build\NightreignP2PHelper\amd64" "dist\nightreign-overlay-helper\bin\amd64"
if errorlevel 1 goto build_failed
xcopy /E /I /Y "native\licenses" "dist\nightreign-overlay-helper\third-party\licenses"
if errorlevel 1 goto build_failed
copy "native\THIRD-PARTY-NOTICES.txt" "dist\nightreign-overlay-helper\third-party\THIRD-PARTY-NOTICES.txt"
if errorlevel 1 goto build_failed

echo 构建完成，输出目录：dist\nightreign-overlay-helper
if not defined CI pause
exit /b 0

:build_failed
echo 构建失败。
if not defined CI pause
exit /b 1
