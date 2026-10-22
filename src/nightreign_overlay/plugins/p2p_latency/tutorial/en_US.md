# Online status

When enabled, this feature displays the names, ping, and stability of Steam teammates.

## Show players' Steam names

Enable **Show players' Steam names** to temporarily block non-friend teammates' Steam communication and display their Steam names during matches. Communication is restored when they leave.

The switch is off by default. A connected non-friend with a valid ping can be processed. Friends, unknown relationships, and existing blocks are skipped. Two teammates are handled independently; preparation failures are retried. Disabling the feature or exiting also requests restoration. Recovery status appears at the bottom of the settings page.

Brief roster gaps do not immediately restore communication. A separate recovery process retains a journal across crashes and network failures. Startup resumes recovery even with the switch off. Keep the original Steam account online and retain pending journals; offline recovery cannot be immediate. Commendations wait for confirmed restoration, while profile links remain available. Do not run old and new helpers simultaneously.

## Initial setup

Launch the overlay helper as administrator, then launch the game. The feature will work automatically.

The overlay appearance can be adjusted separately in Settings.

## Notes

The feature's runtime status is shown at the bottom of its settings page.
