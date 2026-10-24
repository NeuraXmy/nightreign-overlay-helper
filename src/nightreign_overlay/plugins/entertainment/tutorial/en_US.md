## Overview

Various entertainment features. Currently includes automatic audio playback when a teammate is downed.

## Automatic audio on teammate down — Initial setup

### 1. Calibrate the downed status information region.

ℹ️ This step is **optional**. The program automatically calculates the detection region from a 16:9 full-screen game image.

If the automatic region does not work correctly, the game is not full screen, or you want to detect a window other than the game, see the [Calibration Tutorial](app://tutorial/region-calibration).

:::collapse Manual calibration steps

It is recommended to set a controller or keyboard shortcut, then enter the training area or a three-player scene and press the shortcut to open the calibration screen.

![Set calibration shortcut](1.jpg)

Click the upper-right button to start selecting (if the mouse cannot move, try clicking the left mouse button once). Select **the area containing the complete teammate portraits and HP bars**, or **the training menu area shown below**, then press Enter or Save to confirm.

![Calibration screen](2.jpg)

To make "Stop playback when you are downed" work correctly, you also need to calibrate your own downed ring region.

![Set calibration shortcut](4.jpg)

Click the upper-right button to start selecting (if the mouse cannot move, try clicking the left mouse button once). Select **the area containing the entire downed ring** (taking a screenshot while downed in multiplayer is recommended, or use a wall at that location as a reference), then press Enter or Save to confirm.

![Calibration screen](5.jpg)

Return to the main window. A green "Calibrated" status indicates success. Hover over the eye icon to preview the region.

:::

### 2. Enable detection and audio.

![Enable detection and audio](3.jpg)

## Notes

For other recognition failures or inaccurate results, see the "FAQ" page.
