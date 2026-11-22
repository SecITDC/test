"""Add (or remove) the "Convert to" entry in the Windows right-click menu.

    python install_menu.py              # install / update
    python install_menu.py --uninstall  # remove

Only writes to HKEY_CURRENT_USER, so no admin rights needed and nothing changes
for other users. The registry layout it creates for .mov looks like:

  HKCU\\Software\\Classes\\SystemFileAssociations\\.mov\\shell\\QuickConvert
      MUIVerb     = "Convert to"      <- text shown in the menu
      SubCommands = ""                <- "I have a submenu, look in my shell key"
      shell\\
        mp4\\
          MUIVerb = "MP4"
          command\\ (default) = "...pythonw.exe" "...convert.py" "%1" --to mp4

"SystemFileAssociations" is used instead of the .mov key itself so the menu
shows up no matter which app is set as the default player for .mov files.

Windows 11 note: classic entries like this appear under "Show more options"
(or Shift + right-click). Getting into the new compact menu needs a signed
app package; that's a later phase.
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.platform != "win32":
    sys.exit("This installer only works on Windows.")

import winreg  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from formats import MENU, TARGETS  # noqa: E402

VERB = "QuickConvert"
BASE = r"Software\Classes\SystemFileAssociations"
HERE = Path(__file__).resolve().parent


def pythonw() -> Path:
    """pythonw.exe is python.exe without a console window - what we want from Explorer."""
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return candidate if candidate.is_file() else Path(sys.executable)


def set_value(key_path: str, name: str, value: str) -> None:
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def delete_tree(key_path: str) -> None:
    """winreg can only delete empty keys, so remove children first."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                except OSError:
                    break
                delete_tree(f"{key_path}\\{child}")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
    except FileNotFoundError:
        pass


def install() -> None:
    script = HERE / "convert.py"
    py = pythonw()
    for ext, targets in MENU.items():
        root = f"{BASE}\\{ext}\\shell\\{VERB}"
        delete_tree(root)  # start clean so removed targets disappear on update
        set_value(root, "MUIVerb", "Convert to")
        set_value(root, "SubCommands", "")
        for target in targets:
            label, _ = TARGETS[target]
            sub = f"{root}\\shell\\{target}"
            set_value(sub, "MUIVerb", label)
            set_value(f"{sub}\\command", "", f'"{py}" "{script}" "%1" --to {target}')
        print(f"  {ext:6} -> {', '.join(t.upper() for t in targets)}")
    print(f"\nInstalled. Using: {py}")
    print('Right-click a file -> "Show more options" -> "Convert to".')


def uninstall() -> None:
    for ext in MENU:
        delete_tree(f"{BASE}\\{ext}\\shell\\{VERB}")
    print("Removed QuickConvert from the right-click menu.")


if __name__ == "__main__":
    if "--uninstall" in sys.argv:
        uninstall()
    else:
        install()
