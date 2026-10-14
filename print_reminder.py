#!/usr/bin/env python3
"""Color printer reminder for Windows and Linux (Python 3.10+).

Options: --mark-printed, --set-interval DAYS, --status, --config PATH.
Windows: put this script beside the shared print_reminder.json.
Linux: install python3-tk for the warning window and Copy command button.
Launch from your desktop session. Copying does not record a print.
"""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_FILE = Path(__file__).resolve()
DEFAULT_INTERVAL_DAYS = 5

CONFIG_FILE = SCRIPT_FILE.with_name("print_reminder.json")

def load_config(path: Path) -> dict:
    try:
        cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}
    if not isinstance(cfg, dict):
        raise ValueError("The configuration must be a JSON object.")
    return cfg


def save_config(path: Path, cfg: dict) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=path.name + ".", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(cfg, stream, indent=2)
            stream.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def days_since_last_print(cfg: dict) -> float | None:
    raw = cfg.get("last_print_utc")
    if not raw:
        return None
    last = datetime.fromisoformat(raw)
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last).total_seconds() / 86400


def mark_command(path: Path) -> str:
    executable = Path(sys.executable)
    if os.name == "nt" and executable.name.lower() == "pythonw.exe":
        executable = executable.with_name("python.exe")
    args = [str(executable), str(SCRIPT_FILE), "--config", str(path),
            "--mark-printed"]
    if os.name == "nt":
        # Quoted executable paths need the & operator in PowerShell.
        return "& " + " ".join("'" + arg.replace("'", "''") + "'" for arg in args)
    return shlex.join(args)


def notify(title: str, message: str, command: str) -> None:
    print(f"\n*** {title} ***\n{message}\n\n{command}\n", flush=True)
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError as exc:
        fallback_notify(title, message, command, str(exc))
        return
    try:
        window = tk.Tk()
    except tk.TclError as exc:
        fallback_notify(title, message, command, str(exc))
        return

    window.title(title)
    window.resizable(False, False)
    frame = ttk.Frame(window, padding=20)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=message, wraplength=580, justify="left").pack(
        anchor="w", pady=(0, 12))
    command_box = tk.Text(frame, width=72, height=5, wrap="char")
    command_box.insert("1.0", command)
    command_box.configure(state="disabled")
    command_box.pack(fill="x", pady=(0, 12))
    hint = tk.StringVar(value="Copying the command does not reset the reminder.")
    ttk.Label(frame, textvariable=hint, wraplength=580).pack(
        anchor="w", pady=(0, 12))
    buttons = ttk.Frame(frame)
    buttons.pack(fill="x")

    def copy_command() -> None:
        try:
            window.clipboard_clear()
            window.clipboard_append(command)
            window.update_idletasks()
            hint.set("Copied! Paste it into PowerShell after printing."
                     if os.name == "nt" else
                     "Copied! Paste into your terminal before closing this window.")
        except tk.TclError as exc:
            hint.set(f"Could not copy: {exc}")

    ttk.Button(buttons, text="Copy command", command=copy_command).pack(side="left")
    ttk.Button(buttons, text="Close", command=window.destroy).pack(side="right")
    window.bind("<Escape>", lambda event: window.destroy())
    window.update_idletasks()
    x = max(0, (window.winfo_screenwidth() - window.winfo_width()) // 2)
    y = max(0, (window.winfo_screenheight() - window.winfo_height()) // 2)
    window.geometry(f"+{x}+{y}")
    window.lift()
    window.mainloop()


def fallback_notify(title: str, message: str, command: str, error: str) -> None:
    print(f"Warning window unavailable: {error}", file=sys.stderr)
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None, message + "\n\n" + command +
            "\n\nInstall Python's Tcl/Tk component for the Copy command button.",
            title, 0x30,
        )
    else:
        print("For the window on Linux Mint: sudo apt install python3-tk", file=sys.stderr)
        sender = shutil.which("notify-send")
        if sender:
            try:
                subprocess.run(
                    [sender, "-u", "critical", "-a", "print_reminder", title,
                     message + "\n\n" + command], check=False, timeout=10,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                print(f"Desktop notification failed: {exc}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Color printer keep-alive reminder")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--mark-printed", action="store_true")
    actions.add_argument("--set-interval", type=int, metavar="DAYS")
    actions.add_argument("--status", action="store_true")
    parser.add_argument("--config", type=Path, default=CONFIG_FILE)
    args = parser.parse_args()
    path = args.config.expanduser().resolve()
    cfg = load_config(path)

    if args.set_interval is not None:
        if args.set_interval <= 0:
            parser.error("--set-interval must be greater than zero")
        cfg["interval_days"] = args.set_interval
        save_config(path, cfg)
        print(f"Interval set to {args.set_interval} days. State: {path}")
        return 0
    if args.mark_printed:
        cfg["last_print_utc"] = datetime.now(timezone.utc).isoformat()
        cfg.setdefault("interval_days", DEFAULT_INTERVAL_DAYS)
        save_config(path, cfg)
        print(f"Marked as printed: {cfg['last_print_utc']}\nState: {path}")
        return 0

    interval = cfg.get("interval_days", DEFAULT_INTERVAL_DAYS)
    if isinstance(interval, bool) or not isinstance(interval, int) or interval <= 0:
        raise ValueError("interval_days must be a positive integer.")
    elapsed = days_since_last_print(cfg)
    if args.status:
        print(f"State: {path}")
        if elapsed is None:
            print("No previous print recorded.")
        else:
            state = "OK" if elapsed < interval else "OVERDUE"
            print(f"Last print: {elapsed:.1f} days ago | Interval: {interval} days | {state}")
        return 0
    if elapsed is not None and elapsed < interval:
        print(f"OK - last print {elapsed:.1f} days ago; {interval - elapsed:.1f} days remaining.")
        return 0

    reason = ("No previous print has been recorded" if elapsed is None else
              f"{elapsed:.1f} days since last print (interval: {interval} days)")
    shell = "PowerShell" if os.name == "nt" else "your terminal"
    notify("Color printer needs a test print",
           f"{reason}.\n\nPrint a color page, then run this command in {shell}:",
           mark_command(path))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
