## Overview

Tracks the effect that increases attack power when a status buildup meter appears and checks again every 20 seconds. The first detected meter starts a 20-second countdown at Lv.1.

At the end of each countdown, a meter adds one level, up to Lv.10. No meter clears all levels, hides the timer, and resumes waiting. Checks continue at Lv.10 to maintain the effect. Meters disappearing, reappearing, or being covered by the inventory between checks do not affect the countdown. Covering the meter at a check clears the levels.

The chocolate-colored bar shows time until the next check. Position, scale, and text visibility follow the shared HUD settings.

## Initial setup

### 1. Calibrate the meter area

Uncalibrated areas automatically adapt to a 16:9 game window. Try the feature first; if detection does not work, follow the selection steps below.

Make a meter appear in the game, then select Calibrate or use your assigned calibration shortcut. Select the full area where all status icons and their meters can appear, including vertically stacked meters.

### 2. Enable the plugin

Enable Status Buildup Timer on its feature page. Waiting for the first meter uses the general detection interval. Once running, detection occurs only at each 20-second check.

Levels gained before enabling the plugin cannot be reconstructed. Enable it before the first meter appears. Disabling the plugin or resetting its settings clears the countdown and levels.
