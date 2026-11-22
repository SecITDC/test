# QuickConvert

Right-click a file in Windows Explorer → **Convert to** → pick a format.

Currently supported:

| From | To  |
|------|-----|
| .mov | MP4 |

## Setup (Windows 11)

1. **Install Python 3.10+** from python.org (tick *"Add python.exe to PATH"*).
   `tkinter` is included by default and is used for the progress window.
2. **Install FFmpeg**:
   ```powershell
   winget install Gyan.FFmpeg
   ```
   Or download `ffmpeg.exe` + `ffprobe.exe` and put them in `quickconvert\bin\`.
3. **Restart Explorer** so it picks up the new PATH (Task Manager → Windows Explorer → Restart),
   or just sign out and back in.
4. **Add the menu entry**:
   ```powershell
   cd path\to\quickconvert
   python install_menu.py
   ```
5. Right-click a `.mov` → **Show more options** → **Convert to** → **MP4**.

To remove it: `python install_menu.py --uninstall`.
If you move the folder, run `install_menu.py` again (the menu stores the full path).

## How MOV → MP4 works

MOV and MP4 are both *containers*: boxes holding a video stream and an audio stream.

- If the video inside is **H.264** (8-bit), it is **copied** into an MP4 box: takes seconds, no quality loss.
- If it's **HEVC/H.265** (what iPhones record by default) or anything else, it is
  **re-encoded to H.264**, which every website accepts. That takes longer but is
  done at high quality (`-crf 20`).
- Audio is copied when it's AAC/MP3, otherwise converted to AAC.
- The output goes next to the original as `name.mp4` (or `name (1).mp4`). The original is never touched.

Known limitation: iPhone **HDR** clips may look slightly less vivid after re-encoding,
because they're converted to standard (SDR) colour without tone mapping.

## Testing from a terminal

```powershell
python convert.py "C:\path\clip.mov" --to mp4 --no-gui
```

## Files

| File | Purpose |
|------|---------|
| `convert.py` | Entry point the menu runs; progress window |
| `video.py` | FFmpeg logic (probe, choose copy vs. re-encode, run) |
| `formats.py` | Which extensions get which menu entries |
| `install_menu.py` | Writes/removes the registry keys (current user only, no admin) |
