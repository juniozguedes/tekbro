import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.split(" #", 1)[0].strip().strip('"').strip("'")  # allow inline comments / quotes
        os.environ.setdefault(k.strip(), v)


_load_dotenv()


@dataclass
class Config:
    # "opus" / "sonnet" aliases resolve to the latest model your Claude plan allows
    model: str = os.getenv("TEKBRO_MODEL", "sonnet")
    effort: str = os.getenv("TEKBRO_EFFORT", "medium")            # solving code on screen
    answer_effort: str = os.getenv("TEKBRO_ANSWER_EFFORT", "low")  # answering heard questions: speed first
    whisper_model: str = os.getenv("TEKBRO_WHISPER_MODEL", "small")
    # None = learn it from the other person's speech and lock it (see audio.LanguageLock).
    language: str | None = os.getenv("TEKBRO_LANGUAGE") or None
    screen_interval: float = float(os.getenv("TEKBRO_SCREEN_INTERVAL", "5"))
    monitor: int = int(os.getenv("TEKBRO_MONITOR", "1"))
    mic_device: str | None = os.getenv("TEKBRO_MIC_DEVICE") or None
    # "macos" = native system-audio capture, "off" = disabled, or a loopback device name (e.g. BlackHole)
    system_device: str | None = os.getenv("TEKBRO_SYSTEM_AUDIO", "macos")
    # Mute the mic while call audio plays, so speaker echo isn't transcribed as you. Safe with
    # headphones too (you're just not transcribed while talking over them), so it stays on.
    echo_cancel: bool = os.getenv("TEKBRO_ECHO_CANCEL", "1") == "1"
    call_app: str | None = os.getenv("TEKBRO_CALL_APP") or None  # e.g. Teams, zoom, Chrome
    port: int = int(os.getenv("TEKBRO_PORT", "8765"))
    auto_screen: bool = os.getenv("TEKBRO_AUTO_SCREEN", "0") == "1"
    auto_answer: bool = os.getenv("TEKBRO_AUTO_ANSWER", "1") == "1"
    hotkeys: bool = os.getenv("TEKBRO_HOTKEYS", "1") == "1"
    hotkey_solve: str = os.getenv("TEKBRO_HOTKEY_SOLVE", "ctrl+alt+s")
    hotkey_answer: str = os.getenv("TEKBRO_HOTKEY_ANSWER", "ctrl+alt+a")
    # Off by default: answers show in the terminal/dashboard. TEKBRO_NOTIFY=1 adds a macOS
    # notification + sound when a hotkey answer is ready; TEKBRO_SOUNDS=1 clicks on hotkey press.
    notify: bool = os.getenv("TEKBRO_NOTIFY", "0") == "1"
    sounds: bool = os.getenv("TEKBRO_SOUNDS", "0") == "1"
    # Serve the dashboard to your paired devices over Tailscale (see remote.py).
    remote: bool = os.getenv("TEKBRO_REMOTE", "0") == "1"
    workdir: Path = field(default_factory=lambda: ROOT / "captures")
    # Your background (profile.md) and extra notes for the call (context/*.md, e.g. the job
    # description). Both are gitignored; see profile.example.md.
    profile_path: Path = field(default_factory=lambda: ROOT / "profile.md")
    context_dir: Path = field(default_factory=lambda: ROOT / "context")
