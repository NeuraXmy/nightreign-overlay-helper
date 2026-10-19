# Nightreign Overlay Helper

[中文版](README.md)

A desktop overlay companion for **ELDEN RING NIGHTREIGN**, with circle timers, a rain exposure timer, Ultimate Art timers, map information, HP threshold markers, and co-op connection status. **GPT-6.1-Sol** assists with development and translation.

## Features

- **Circle Timer**: Recognizes the DAY I / DAY II / DAY III banner at the start of each day and displays an automatic circle countdown in the overlay. Manual timing is also available through shortcuts.
- **Rain Exposure Timer**: Periodically captures the screen and checks the HP bar color. When it changes to the rain exposure color, a countdown shows the time remaining before heavy damage begins. The countdown stops automatically when the normal color returns.
- **Ultimate Art Timer**: Displays the remaining duration of an Ultimate Art when you press its bound key and the Art icon lights up. Supports Duchess, Recluse, Executor, Revenant, and Scholar.
- **Map Information**: Identifies Shifting Earth terrain, the Nightlord portrait, and point-of-interest types to narrow down the map seed and display detailed location information. Supports all maps, including DLC maps, as well as events that hide the Nightlord or map details; some cases require manual filtering.
- **HP Threshold Markers**: Periodically captures the screen and detects the HP bar length, then displays reference markers for effects that activate when HP is below maximum or when HP is low.
- **Co-op Status**: Displays the nicknames, ping, and connection stability of your Steam co-op teammates.

## Usage

1. Extract the complete Windows release ZIP. Keep `_internal/`, `bin/`, `third-party/`, and the other bundled files alongside `nightreign-overlay-helper.exe`; do not move the EXE on its own. The release includes the Python and .NET runtimes, so you do not need to install them separately.
2. Run `nightreign-overlay-helper.exe` and approve the Windows administrator prompt. Co-op Status requires you to be signed in to Steam.
3. Open the **Guide** tab on each feature page and complete its initial setup, including region calibration, game language selection, and shortcut configuration. Run the game in windowed or borderless windowed mode.
4. Right-click an overlay or the system tray icon to open the main window. Closing the main window hides it to the tray; to exit completely, choose **Quit** from the context menu.

You can adjust overlay positions while the main window is open. General Settings provides display mode, opacity, and other options. If recognition fails, first check that the calibrated region is accurate and unobstructed. Recalibrate after changing monitors, resolution, display scaling, or the game window size. To report an issue, export a diagnostic ZIP using the **Report** button on the **About** page.

## Running from Source

### Requirements

- Python 3.11 or later.
- Windows is the primary supported platform. macOS is for development and debugging only; Co-op Status uses simulated data there.
- On macOS, game foreground detection is unavailable and screen capture requires Screen Recording permission. If transparent overlays do not display correctly, select **Standard window** in General Settings.

### Installation and Startup

Run all commands from the repository root. Using `uv` is recommended to install dependencies from `uv.lock`:

```bash
uv sync --locked --dev
uv run python main.py
```

Alternatively, use a standard `venv`. On Windows PowerShell:

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

After installation, you can also launch the application with `nightreign-overlay-helper` from an activated virtual environment. To use Co-op Status when running from source on Windows, build the helper program separately; see the [Co-op Status documentation](docs/features/p2p.md) (Chinese).

### Verification

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

### Windows Build

Install `uv` and the .NET 8 SDK on Windows x64, then run `build.bat`. The script uses Python 3.13 and locked dependencies to produce a complete release folder. See the [release guide](docs/development/releases/README.md) (Chinese) for the build process, GitHub Actions ZIP downloads, and release acceptance requirements.

## Project Documentation

The [documentation index](docs/INDEX.md) organizes the project overview, architecture, features, usage guides, and development resources. These technical documents are primarily in Chinese; localized feature tutorials are available in the application.

- Understand the project: [Overview](docs/overview.md) and [Architecture](docs/architecture/README.md).
- Explore features: [Feature documentation](docs/features/README.md) and the in-app tutorials.
- Troubleshoot issues: [Usage and diagnostic guides](docs/guides/README.md).
- Develop and release: [Development guidelines](docs/development/contributing.md), [Testing strategy](docs/development/testing/README.md), and [Windows builds and releases](docs/development/releases/README.md).

## Safety Statement

This application is a standalone program, not a mod or plugin for ELDEN RING NIGHTREIGN. Its recognition features rely primarily on screenshots and image analysis. It does not read or write any game process memory, modify game data or files, inject code into the game, alter game logic, or capture game network packets. As such, it poses essentially no anti-cheat risk and can be used in official online multiplayer.

## Acknowledgments

- [Fuwish](https://github.com/Fuwishx): Extracted map data.
- [雀煊](https://space.bilibili.com/391379672): Shared Great Hollow crystal layouts.
- [SteamP2PInfo](https://github.com/tremwil/SteamP2PInfo): Approach to P2P connection queries and ETW latency measurement.
- [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets/): Fluent Design UI components.

## License

[AGPL-3.0-only](LICENSE)
