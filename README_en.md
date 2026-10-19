<div align="center">
  <h1>Nightreign Overlay Helper</h1>
  <p>A desktop overlay for ELDEN RING NIGHTREIGN with timers, map details, HP markers, and co-op status.</p>
  <p>
    <a href="https://github.com/NeuraXmy/nightreign-overlay-helper/releases"><img alt="Downloads" src="https://img.shields.io/github/downloads/NeuraXmy/nightreign-overlay-helper/total?logo=github&style=flat-square&color=1E9BFA"></a>
    <a href="https://github.com/NeuraXmy/nightreign-overlay-helper/releases"><img alt="Release" src="https://img.shields.io/github/v/release/NeuraXmy/nightreign-overlay-helper?style=flat-square&color=1E9BFA"></a>
  </p>
  <p><a href="https://github.com/NeuraXmy/nightreign-overlay-helper/releases">Download for Windows</a> · <a href="README.md">中文版</a></p>
</div>

Developed and translated with assistance from **GPT-6.1-Sol**.

The current version is developed on [`main`](https://github.com/NeuraXmy/nightreign-overlay-helper/tree/main), formerly `rewrite`. The legacy main branch has moved to [`legacy`](https://github.com/NeuraXmy/nightreign-overlay-helper/tree/legacy), formerly `main`, and the legacy development branch has moved to [`legacy-dev`](https://github.com/NeuraXmy/nightreign-overlay-helper/tree/legacy-dev), formerly `dev`. Forks maintaining the legacy version should sync from `legacy` or `legacy-dev`; `main` now contains the new version.

## Features

- **Circle Timer**: Recognizes the DAY I / DAY II / DAY III banner at the start of each day and shows a circle countdown in the overlay. You can also start timing manually with shortcuts.
- **Rain Exposure Timer**: Periodically checks the HP bar color in screenshots. When the rain exposure color appears, a countdown shows the time before heavy damage begins; it stops when the normal color returns.
- **Ultimate Art Timer**: Shows the remaining active duration when you press the in-game Ultimate Art key and the Art icon lights up. Supports Duchess, Recluse, Executor, Revenant, and Scholar.
- **Map Information**: Recognizes Shifting Earth terrain, the Nightlord portrait, and point-of-interest types to narrow down the map seed and show detailed location information. Supports all maps, including DLC, and events that hide the Nightlord or map details. Some cases need manual filtering.
- **HP Threshold Markers**: Periodically detects HP bar length in screenshots and shows reference lines for effects that activate below maximum HP or at low HP.
- **Co-op Status**: Shows your Steam co-op teammates' nicknames, ping, and connection stability.

## Usage

1. Download and fully extract the [Windows release ZIP](https://github.com/NeuraXmy/nightreign-overlay-helper/releases). Keep `_internal/`, `bin/`, `third-party/`, and all other bundled files alongside the EXE. Do not move the EXE on its own. Python and .NET runtimes are included; no separate installation is needed.
2. Run `nightreign-overlay-helper.exe` and approve the administrator prompt. Sign in to Steam before using Co-op Status.
3. Set the game to windowed or borderless windowed mode, then follow the **Guide** tab on each feature page to calibrate regions, select the game language, and configure shortcuts.
4. Right-click an overlay or the system tray icon to open the main window. Closing it hides the app to the tray; choose **Quit** from the context menu to exit completely.

Move the overlays while the main window is open. Display mode, opacity, and other options are available in General Settings.

### Recognition and Issue Reports

- If recognition fails, check that the calibrated region is accurate and no other window covers it.
- Recalibrate after changing monitors, resolution, display scaling, or the game window size.
- To report an issue, export a diagnostic ZIP with the **Report** button on the **About** page.

## Running from Source

### Requirements

- Python 3.11 or later. Windows is the primary supported platform.
- macOS is for development and debugging only. Co-op Status uses simulated data, and game foreground detection is unavailable.
- Screen capture on macOS requires Screen Recording permission. If transparent overlays display incorrectly, select **Standard window** in General Settings.

### Installation and Startup

Run these commands from the repository root. We recommend `uv` to install dependencies from `uv.lock`:

```bash
uv sync --locked --dev
uv run python main.py
```

You can also use a standard `venv`. On Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e . pytest ruff
.venv\Scripts\python.exe main.py
```

On macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e . pytest ruff
.venv/bin/python main.py
```

Once installed, you can also run `nightreign-overlay-helper` from an activated virtual environment. To use Co-op Status from source on Windows, build the helper program separately; see the [Co-op Status documentation](docs/features/p2p.md) (Chinese).

### Verification

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

### Windows Build

Install `uv` and the .NET 8 SDK on Windows x64, then run `build.bat`. The script uses Python 3.13 and locked dependencies to create a complete release folder.

See the [release guide](docs/development/releases/README.md) (Chinese) for build steps, GitHub Actions ZIP downloads, and release acceptance requirements.

## Project Documentation

The [documentation index](docs/INDEX.md) covers the project overview, architecture, features, usage, and development. Technical documents are primarily in Chinese; localized feature tutorials are available in the app.

- Understand the project: [Overview](docs/overview.md), [Architecture](docs/architecture/README.md).
- Explore features: [Feature documentation](docs/features/README.md), in-app tutorials.
- Troubleshoot issues: [Usage and diagnostic guides](docs/guides/README.md).
- Develop and release: [Development guidelines](docs/development/contributing.md), [Testing strategy](docs/development/testing/README.md), [Windows builds and releases](docs/development/releases/README.md).

## Safety Statement

This is a standalone application, not a game mod or plugin. Recognition relies primarily on screenshots and image analysis. It does not read or write game process memory, modify game data or files, inject code, or change game logic. It reads Steam P2P network packets solely to measure latency, without intercepting or modifying game information. Given how it currently operates, this tool is generally not expected to trigger anti-cheat detection and can be used normally in official online multiplayer. However, any third-party software carries potential risks, and there is no guarantee that anti-cheat systems will never flag it. Please assess these risks yourself and use the tool at your own risk.

## Acknowledgments

- [Fuwish](https://github.com/Fuwishx): Extracted map data.
- [雀煊](https://space.bilibili.com/391379672): Shared Great Hollow crystal layouts.
- [SteamP2PInfo](https://github.com/tremwil/SteamP2PInfo): Approach to P2P connection queries and ETW latency measurement.
- [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets/): Fluent Design UI components.

## License

Licensed under [AGPL-3.0-only](LICENSE). Use, modification, and redistribution, including commercial use, are permitted under the license, WITHOUT ANY WARRANTY.

Third-party components retain their own licenses: MIT for SteamP2PInfo, and GPLv3 for PyQt6-Fluent-Widgets and PyQt6. See the [third-party notices](src/nightreign_overlay/resources/licenses/THIRD-PARTY-NOTICES.md) and [corresponding source and build instructions](src/nightreign_overlay/resources/licenses/SOURCE.md) for full texts and details.

Windows runtime ZIPs include `licenses/`, `third-party/`, and `SOURCE.md`. Corresponding source is available separately as `<version>-sources.zip` in the same Release. Preserve the complete runtime folder and provide access to the matching source when redistributing. License texts are also available offline under **About → Licenses and source**.
