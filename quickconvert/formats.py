"""The one place that says what can be converted into what.

Both the right-click menu installer and the converter read this, so adding a
new conversion later is: write a function, add one line here, re-run install.
"""

from video import convert_to_mp4

# target format -> (menu label, function that does the work)
TARGETS = {
    "mp4": ("MP4", convert_to_mp4),
}

# source extension -> list of target formats shown in its "Convert to" submenu
MENU = {
    ".mov": ["mp4"],
}
