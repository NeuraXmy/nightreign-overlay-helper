## Why is the overlay not visible in fullscreen mode?

The game must run in "Windowed" or "Borderless Windowed" mode. "Fullscreen" mode is not supported.

## Why does the overlay always show a translucent background?

When the main window is open, the overlay shows a translucent background to make its position easier to drag.

## How do I exit the program completely after closing the main window?

Right-click the overlay or the tray icon and choose "Quit".

## Recognition is wrong or inaccurate. What should I check?

Please check the following:

1. Make sure the feature is enabled and that its initial setup was completed according to the tutorial.
2. Make sure the calibrated region is accurate. Each feature has its own requirements for the calibration region.
3. In general "Settings", the "Detection interval" may be too large, making detection less responsive. The recommended default is 250 ms.
4. Make sure the region to be detected (the map or HP bar) is not covered by this helper's overlay or another application overlay.
5. If HDR (Display Settings → High Dynamic Range) is enabled in the game, or another setting changes the game's colors, recognition may become inaccurate. Try enabling "HDR image processing" in general "Settings"; it may help, but changing this setting does not guarantee a fix. We recommend disabling HDR when using the helper.
6. If the number or resolution of your monitors changes, or the game window size changes, calibrate the region again.

## The system or game stutters after enabling the helper. What should I check?

Please check the following:

1. In general "Settings", the "Detection interval" may be too small, causing screenshots to be analyzed too frequently. The recommended default is 250 ms.
2. In the map information feature, setting "Recognition result count" too high may use considerable performance.
3. An overlay may affect system big.LITTLE scheduling. You can use a tool such as Process Lasso to make the helper run only on the efficiency cores.
4. Recognition itself requires some processing power.

## The game stutters when used with frame-generation software such as Lossless Scaling. What can I do?

Overlays are difficult to use together with frame-generation software, and this issue cannot currently be resolved. Some features, such as the circle timer, can be moved to another monitor to avoid it.

## Do I need to keep the old files when updating? Will my settings be lost?

Settings are stored separately in the user data directory, away from the program files, so it is safe to delete the old program files.

## Can using this helper trigger anti-cheat detection?

See the "Security statement" on the "About" page.

## What if none of the above solves my problem?

This is a non-profit project, and we apologize for any issues.

Use "Feedback" on the "About" page. It is best to send feedback immediately after a problem occurs; the program automatically packages recent logs and detection results into a ZIP archive, which you can email to the author.

Please do not describe the problem only in text through GitHub Issues or Bilibili comments.
