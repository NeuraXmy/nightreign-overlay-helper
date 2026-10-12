# Overlay test

A demo feature that **does not need the game**. Use it to confirm that the overlay basics work on your system.

## What you will see

Once enabled, a small panel appears at the top centre of the screen showing:

- a title and the current time
- a repeating countdown with a progress bar
- whether the game window is focused, and the current overlay presentation

## Things to try

| Action | Expected result |
| --- | --- |
| Drag the panel with the left mouse button | It follows the cursor and keeps its position after a restart |
| Right-click the panel | Menu: reset position / enable click-through / open main window |
| Change "Opacity" or "Scale" | The panel updates immediately |
| Enable "Click-through" | Clicks pass through the panel; turn it off on the settings tab |
| Disable "Show background panel" | Only text and the progress bar remain — handy for checking transparency |
| Switch "Settings → Overlay presentation" | The panel toggles between a transparent overlay and a regular window |

## Troubleshooting

- **The background is black / white instead of transparent**: your system does not support transparent overlays.
  Choose "Regular window" in "Settings → Overlay presentation".
- **The panel disappears with "Only show while the game is focused"**: expected while the game is not running or
  not focused. On macOS the game window cannot be detected, so this option has no effect.
