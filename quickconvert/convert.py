"""Entry point that the right-click menu runs.

    pythonw convert.py "C:\\Videos\\clip.mov" --to mp4

Shows a small progress window (tkinter, ships with Python) while FFmpeg works.
Use --no-gui to run in a terminal instead (handy for testing).
"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
from pathlib import Path

# Make imports work no matter which folder Explorer launches us from.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from formats import TARGETS  # noqa: E402
from video import Cancelled, ConversionError  # noqa: E402


def run_cli(src: Path, convert) -> int:
    def show(fraction: float, status: str) -> None:
        print(f"\r{status}: {fraction * 100:5.1f}%", end="", flush=True)

    try:
        out = convert(src, on_progress=show)
    except ConversionError as e:
        print(f"\nError: {e}", file=sys.stderr)
        return 1
    print(f"\nSaved: {out}")
    return 0


def run_gui(src: Path, convert) -> int:
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title("QuickConvert")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    tk.Label(root, text=src.name, font=("Segoe UI", 10, "bold")).pack(padx=16, pady=(14, 2), anchor="w")
    status = tk.Label(root, text="Starting…", font=("Segoe UI", 9))
    status.pack(padx=16, anchor="w")
    bar = ttk.Progressbar(root, length=340, maximum=1.0)
    bar.pack(padx=16, pady=10)

    cancel_event = threading.Event()
    button = ttk.Button(root, text="Cancel", command=cancel_event.set)
    button.pack(pady=(0, 14))
    root.protocol("WM_DELETE_WINDOW", cancel_event.set)

    # Tkinter isn't thread-safe: the worker thread puts messages in a queue and
    # the UI thread picks them up every 100 ms.
    messages: queue.Queue = queue.Queue()
    result = {"code": 0}

    def worker() -> None:
        try:
            out = convert(src, on_progress=lambda f, s: messages.put(("progress", f, s)),
                          cancel_event=cancel_event)
            messages.put(("done", out))
        except Cancelled:
            messages.put(("cancelled",))
        except ConversionError as e:
            messages.put(("error", str(e)))
        except Exception as e:  # anything unexpected should still be shown, not swallowed
            messages.put(("error", f"{type(e).__name__}: {e}"))

    def poll() -> None:
        try:
            while True:
                msg = messages.get_nowait()
                kind = msg[0]
                if kind == "progress":
                    _, fraction, text = msg
                    bar["value"] = fraction
                    status["text"] = f"{text} — {fraction * 100:.0f}%"
                elif kind == "done":
                    bar["value"] = 1.0
                    status["text"] = f"Saved as {msg[1].name}"
                    button.configure(text="Close", command=root.destroy)
                    root.after(2500, root.destroy)
                    return
                elif kind == "cancelled":
                    root.destroy()
                    return
                elif kind == "error":
                    result["code"] = 1
                    root.withdraw()
                    messagebox.showerror("QuickConvert – conversion failed", msg[1])
                    root.destroy()
                    return
        except queue.Empty:
            pass
        root.after(100, poll)

    threading.Thread(target=worker, daemon=True).start()
    poll()
    root.mainloop()
    return result["code"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert a file to another format.")
    parser.add_argument("file", type=Path)
    parser.add_argument("--to", required=True, choices=sorted(TARGETS))
    parser.add_argument("--no-gui", action="store_true", help="print progress to the terminal")
    args = parser.parse_args()

    _, convert = TARGETS[args.to]
    if args.no_gui:
        return run_cli(args.file, convert)
    return run_gui(args.file, convert)


if __name__ == "__main__":
    sys.exit(main())
