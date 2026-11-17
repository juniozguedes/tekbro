"""Global hotkeys (via bin/tekbro-hotkey) and macOS notifications."""
import re
import subprocess
import threading
from typing import Callable

from .audio import ensure_helper


class HotkeyListener(threading.Thread):
    """Runs tekbro-hotkey and calls the matching action for each line it prints."""

    def __init__(self, bindings: dict[str, str], actions: dict[str, Callable[[], None]], sounds: bool = False):
        super().__init__(daemon=True, name="hotkeys")
        self.bindings = bindings  # action name -> combo, e.g. {"solve": "ctrl+alt+s"}
        self.actions = actions
        self.sounds = sounds

    def run(self):
        cmd = [str(ensure_helper("tekbro-hotkey"))] + [f"{a}={c}" for a, c in self.bindings.items() if c]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
        assert proc.stdout
        for line in proc.stdout:
            action = self.actions.get(line.strip())
            if action:
                if self.sounds:
                    sound("Tink")
                action()


def sound(name: str = "Glass"):
    subprocess.Popen(["afplay", f"/System/Library/Sounds/{name}.aiff"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _summary(markdown: str, limit: int = 180) -> str:
    """First sentence(s) under '## Answer', as plain text."""
    m = re.search(r"##\s*Answer\s*\n+(.+?)(\n\s*\n|\n##|$)", markdown, re.S)
    text = (m.group(1) if m else markdown).strip()
    text = re.sub(r"[`*_#>]", "", text).replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def notify(title: str, markdown: str):
    body = _summary(markdown)
    esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')  # noqa: E731
    subprocess.Popen(
        ["osascript", "-e",
         f'display notification "{esc(body)}" with title "Tek Bro" subtitle "{esc(title)}" sound name "Glass"'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
