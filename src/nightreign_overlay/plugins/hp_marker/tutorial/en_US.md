## Overview

The feature periodically captures screenshots and detects the HP bar length, displaying the HP thresholds required to trigger the in-game effects described as "when HP is not full" and "when HP is low".

## Initial setup

### 1. Calibrate the HP bar region.

It is recommended to set a controller or keyboard shortcut. Then enter the training area or any scene with an HP bar, and press the shortcut to open the calibration screen.

![Set calibration shortcut](1.jpg)

Click the button in the upper-right corner to start selecting (if the mouse cannot move, try clicking the left mouse button once). Select **a section on the left side of the HP bar**, then press Enter or the Save button to confirm.

![Calibration screen](2.jpg)

The calibrated region should look like this: **a section on the left side of the HP bar**, with the left, top, and bottom edges of the box aligned with the bar. If selecting a small region is inconvenient, select a larger area first and adjust its corners.

![Selected region](3.jpg)

Return to the main window. A green "Calibrated" status indicates success. Hover over the eye icon to view the calibrated region.

## Result

![Appearance](4.jpg)

From left to right, the markers show the thresholds for "when HP is low", "when HP is not full", and the end of the HP bar. Marker appearance can be adjusted on this feature's settings page.

## Notes

The stability mechanism may leave markers visible briefly after the HP bar disappears, or delay marker updates briefly after the HP bar changes. This is normal and does not affect use.

Do not let another overlay cover the HP bar region, such as the circle timer overlay.

For other recognition failures or inaccurate results, see the "FAQ" page.
