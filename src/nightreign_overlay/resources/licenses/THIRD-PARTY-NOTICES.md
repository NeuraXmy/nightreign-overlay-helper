# Licenses and third-party notices

Nightreign Overlay Helper — Copyright NeuraXmy and contributors.

The project's own code is licensed under GNU AGPL version 3 only. You may
use, modify and redistribute it, including commercially, under that license.
It is provided WITHOUT ANY WARRANTY, including merchantability or fitness for
a particular purpose. See `AGPL-3.0.txt` (also `LICENSE` in the release folder).
The licenses and copyright notices of incorporated third-party components
continue to apply to those components.

## PyQt6-Fluent-Widgets

- Copyright © 2021 by zhiyiYo.
- License distributed with the dependency: GNU GPL version 3; see
  `PyQt6-Fluent-Widgets-LICENSE.txt`.
- Source: https://github.com/zhiyiYo/PyQt-Fluent-Widgets/tree/PyQt6
- The application uses the public PyQt6-Fluent-Widgets distribution, without
  local modifications. The exact version is recorded in `licenses/source-manifest.json`
  and `uv.lock` in the source attachment. The separate `<version>-sources.zip`
  Release attachment contains its source distribution, together with a matching
  upstream repository archive containing editable Qt
  resources. The pinned commit and hash are recorded in the manifest.
- The upstream README additionally describes GPL use as being for
  “non-commercial project” and directs commercial users to
  https://qfluentwidgets.com/price. This notice preserves that statement; it
  does not add a non-commercial restriction to the GPL text or claim a
  commercial license has been purchased. Resolve any ambiguity with the
  copyright holder before relying on a separate commercial grant.

## PyQt6

- Copyright (c) 2026 Riverbank Computing Limited <info@riverbankcomputing.com>.
  Earlier files retain their respective copyright notices in the source archive.
- This application uses the public GNU GPL version 3 distribution, without
  local modifications; see `PyQt6-LICENSE.txt`.
- Homepage: https://www.riverbankcomputing.com/software/pyqt/
- The exact version, source URL and hash are recorded in `licenses/source-manifest.json`;
  the corresponding source distribution is included in the separate `<version>-sources.zip` Release attachment.
- Riverbank also offers commercial licenses. This release does not claim one.
  Qt itself is a separate dependency with its own licensing terms; this notice
  does not replace Qt's notices or constitute an audit of all bundled libraries.

## MaaWin32Screencap

- Win32 screen-capture library extracted from
  [MaaFramework](https://github.com/MaaXYZ/MaaFramework); copyright the
  MaaFramework authors and contributors. Licensed under the GNU LGPL
  version 3; see `MaaWin32Screencap-LICENSE.txt`.
- Bundled as the prebuilt `MaaWin32Screencap.dll` (Windows x64) that the
  application loads at runtime. First distributed with the upstream PR #23
  migration (`3c427af`); the DLL remains a separate LGPL work.
- The distributed DLL carries changes ahead of upstream MaaFramework:
  the `ensure_window_on_screen` fix (anchoring to the full monitor rect
  and skipping borderless fullscreen windows), maintained in the
  extraction repository
  <https://codeberg.org/AbyssRei/MaaWin32Screencap> (commits `f9e7fae`,
  `b0e45dd`). Corresponding source for the DLL is available there.

## SteamP2PInfo and P2P helper components

- SteamP2PInfo — Copyright (c) 2022 William Tremblay.
  https://github.com/tremwil/SteamP2PInfo — MIT License.
- The helper adapts connection-query and ETW latency-monitoring concepts/code;
  this is not a claim that the helper is an unmodified upstream distribution.
- The original notices for SteamP2PInfo, Steamworks.NET and Microsoft TraceEvent
  are in `third-party/THIRD-PARTY-NOTICES.txt`. Their complete MIT licenses are
  in `third-party/licenses/`, including `SteamP2PInfo-LICENSE.txt`.

## Source and redistribution

See `SOURCE.md` for source locations and build instructions. GPLv3 and AGPLv3
permit combining these components under their compatibility provisions; the
GPL components retain their GPL terms. Preserve all applicable licenses,
copyright notices and source materials when redistributing the release.

This file covers the components listed above. It is not a complete inventory
of every Python, Qt, .NET or native dependency in the application.
