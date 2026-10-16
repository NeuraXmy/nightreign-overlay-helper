# Debug image storage

The application stores diagnostic images through `DebugImageApi` in `src/nightreign_overlay/core/debug.py`.

## Storage contract

- Root directory: `user_data_dir()/debug`.
- Each result has its own directory: `debug/{result_name}/`.
- Images use timestamp names such as `20261016_153012_123456.jpg`.
- JPEG quality is 85. A metadata dictionary is written beside the image as the same timestamp with a `.json` suffix.
- The default retention is 10 image/metadata pairs. Callers can pass a different `keep` value; calibration results use `keep=1`.
- `cooldown_seconds` prevents a result from being queued again until the cooldown expires.
- A single background worker performs conversion, compression, JSON writing, and retention cleanup, so detector and UI threads do not block on disk I/O.
- Diagnostics are enabled by default and can be disabled from General Settings. When disabled, submissions are ignored.

## Integrated result names

| Result | Directory | Retention / cooldown |
| --- | --- | --- |
| Region calibration | `region_{region_key}` and `region_sample_{sample_key}` | 1 / none |
| DAYX | `day_timer_dayx` | 10 / 10 minutes |
| Rain HP color | `rain_timer_hp_color` | 10 / 10 minutes |
| Ultimate recognition | `art_timer_ultimate` | 10 / 10 minutes |
| Full map | `map_full_map` | 10 / 10 minutes |
| Special terrain | `map_terrain` | 10 / none |
| Nightlord | `map_nightlord` | 10 / none |
| POI input/result | `map_poi`, `map_poi_result` | 10 / none |
| HP marker | `hp_marker` | 10 / 10 minutes |

Metadata includes the recognition scores or ratios available at the detection point. Region calibration metadata also records the screen geometry, device pixel ratio, capture origin, and selected rectangle.

## Measured save cost

On October 16, 2026, a local benchmark used a noisy 3840x2160 RGB `QImage` to represent a worst-case full-screen calibration capture. The caller-side `save()` submission averaged 7.2 ms (maximum 8.6 ms), while the background JPEG encoding and file write averaged 115.0 ms (maximum 116.4 ms) and produced a 6.0 MiB file. The detector thread therefore pays only the image snapshot/enqueue cost; compression and disk I/O remain on the debug worker. For comparison, the same benchmark measured 29.0 ms for 1920x1080 and 8.1 ms for a 750x750 map image.
