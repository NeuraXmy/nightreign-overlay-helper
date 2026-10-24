## Overview

When you press the art key in the game and the art icon lights up, the overlay displays a countdown for the art effect. Supported characters: Duchess, Recluse, Executor, Revenant, and Scholar.

It also supports a countdown for the duration of Undertaker's additional art.

## Initial setup

### 1. Calibrate the art icon region.

ℹ️ This step is **optional**. The program automatically calculates the detection region from a 16:9 full-screen game image.

If the automatic region does not work correctly, the game is not full screen, or you want to detect a window other than the game, see the [Calibration Tutorial](app://tutorial/region-calibration).

:::collapse Manual calibration steps

It is recommended to set a controller or keyboard shortcut. Then enter the training area or any scene where the art icon is visible, and press the shortcut to open the calibration screen.

![Set calibration shortcut](1.jpg)

Click the button in the upper-right corner to start selecting (if the mouse cannot move, try clicking the left mouse button once). Select an area **tightly around the bright edge of the art icon**, excluding the outer gradient ring, then press Enter or the Save button to confirm.

![Calibration screen](2.jpg)

Return to the main window. A green "Calibrated" status indicates success. Hover over the eye icon to view the calibrated region.

:::

### 2. Set the in-game art shortcut.

![Set art shortcut](3.jpg)

Undertaker's art can be detected without pressing this shortcut.

## Result

![Appearance](4.jpg)

The appearance of the main overlay can be adjusted in the general "Settings".

## Notes

Sometimes an unsupported character may still trigger an incorrect countdown. This is normal and does not affect use.

For other recognition failures or inaccurate results, see the "FAQ" page.
