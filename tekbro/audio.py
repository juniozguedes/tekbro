"""Audio capture + local transcription with faster-whisper.

Each Listener captures one source, splits it on silence and transcribes each chunk:
  - the mic (or any input device)            → speaker "me"
  - macOS system audio via bin/tekbro-audio  → speaker "them"

Speaker-mode support (no headphones): the system-audio listener feeds an EchoGate
with the times the call audio was playing; the mic listener mutes itself during
those windows, so the other person's voice coming out of the speakers isn't
transcribed a second time as "me". A text-level dedupe in app.py catches leftovers.

Language: Whisper's per-chunk auto-detect can flip a chunk to another language
(an accent is enough). A LanguageLock learns the call's language from the other
person's speech and then pins both listeners to it. No setting needed.
"""
import os
import queue
import shlex
import subprocess
import threading
import time
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16_000
FRAME_MS = 30
FRAME = int(SAMPLE_RATE * FRAME_MS / 1000)
SILENCE_RMS = 0.012       # below this a frame counts as silence
END_SILENCE_S = 0.8       # silence that closes an utterance
MAX_UTTERANCE_S = 20.0
MIN_UTTERANCE_S = 0.6
MIN_VOICED_S = 0.3        # at least this much actually-loud audio (filters clicks/echo blips)
NO_SPEECH_MAX = 0.6       # drop Whisper segments it thinks are not speech…
MIN_AVG_LOGPROB = -1.0    # …or that it is very unsure about (typical hallucinations)
MAX_COMPRESSION = 2.4     # …or that is mostly repetition, e.g. "ვვვვვ…" from noise
RESTART_DELAY_S = 2.0     # wait before restarting an interrupted capture helper

ROOT = Path(__file__).resolve().parent.parent
HELPER = ROOT / "bin" / "tekbro-audio"
MACOS = "macos"  # device value meaning "macOS system audio via ScreenCaptureKit"

_model = None
_model_lock = threading.Lock()


def get_model(size: str):
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            print(f"[audio] loading Whisper '{size}' (first run downloads it, ~0.5 GB for 'small')…")
            # num_workers=2 lets the "me" and "them" listeners transcribe in parallel.
            # Apple GPU (mps) is ~2.5x faster than CPU; fall back if unavailable.
            try:
                _model = WhisperModel(size, device="mps", compute_type="float16", num_workers=2)
            except Exception:
                _model = WhisperModel(size, device="cpu", compute_type="int8", num_workers=2)
        return _model


def resolve_device(name: str | None) -> int | None:
    if name is None:
        return None
    if name.isdigit():
        return int(name)
    for i, d in enumerate(sd.query_devices()):
        if name.lower() in d["name"].lower() and d["max_input_channels"] > 0:
            return i
    raise ValueError(f"Audio input device not found: {name!r} (run with --list-devices)")


def ensure_helper(name: str = "tekbro-audio") -> Path:
    """Path to a native helper in bin/, building them on first use."""
    path = ROOT / "bin" / name
    if not path.exists():
        print("[native] building helpers (first run)…")
        subprocess.run([str(ROOT / "native" / "build.sh")], check=True)
    return path


class EchoGate:
    """Remembers when call audio was playing, so the mic can ignore its echo.

    A mic frame captured at time t is treated as echo when the system audio was
    active anywhere in [t - TAIL, t + LEAD]:
      - TAIL covers room reverb + speaker latency after the sound was played.
      - LEAD covers ScreenCaptureKit delivering system audio later than the mic
        hears it. The mic is delayed by LEAD before deciding, so that future
        window is already known.
    """

    LEAD_S = 0.35
    TAIL_S = 0.45
    ACTIVE_RMS = 0.004   # system audio is digital and clean, so a low bar works

    def __init__(self):
        self._active: deque[float] = deque(maxlen=20_000)
        self._lock = threading.Lock()
        self.muted_frames = 0

    def feed(self, ts: float, frame: np.ndarray):
        if float(np.sqrt(np.mean(frame ** 2))) > self.ACTIVE_RMS:
            with self._lock:
                self._active.append(ts)

    def is_echo(self, ts: float) -> bool:
        lo, hi = ts - self.TAIL_S, ts + self.LEAD_S
        with self._lock:
            for t in reversed(self._active):
                if t < lo:
                    return False
                if t <= hi:
                    return True
        return False


class LanguageLock:
    """Learns the call's language from confident detections, then pins it."""

    MIN_PROB = 0.8   # Whisper's confidence in its language guess
    VOTES = 2        # agreeing confident chunks needed to lock

    def __init__(self, fixed: str | None = None):
        self.language = fixed
        self._votes: list[str] = []
        self._lock = threading.Lock()

    def vote(self, lang: str, prob: float, words: int):
        if self.language or prob < self.MIN_PROB or words < 4:
            return
        with self._lock:
            self._votes = (self._votes + [lang])[-self.VOTES:]
            if len(self._votes) == self.VOTES and len(set(self._votes)) == 1:
                self.language = lang
                print(f"[audio] call language: {lang}")


class Listener(threading.Thread):
    """Transcribes one audio source.

    device: None = default mic · name/index = that input device ·
            "macos" = system audio via tekbro-audio · "cmd:<shell cmd>" = a
            command that prints 16 kHz mono float32 PCM (used for tests).
    echo_gate + role: "reference" feeds the gate, "gated" is muted by it.
    """

    def __init__(
        self,
        speaker: str,
        device: str | None,
        whisper_size: str,
        language: str | None,
        on_text: Callable[[str, str], None],
        call_app: str | None = None,
        echo_gate: EchoGate | None = None,
        role: str | None = None,
        lang_lock: LanguageLock | None = None,
    ):
        super().__init__(daemon=True, name=f"listener-{speaker}")
        self.speaker = speaker
        self.command: list[str] | None = None
        self.restart = False
        if device == MACOS:
            self.command = [str(ensure_helper())] + (["--app", call_app] if call_app else [])
            self.restart = True  # macOS may interrupt capture; bring it back
            self.device = None
        elif device and device.startswith("cmd:"):
            # Test hook: run a command that prints PCM. Off unless explicitly allowed.
            if os.getenv("TEKBRO_ALLOW_CMD_SOURCE") != "1":
                raise ValueError("cmd: audio sources are for tests; set TEKBRO_ALLOW_CMD_SOURCE=1")
            self.command = shlex.split(device[4:])
            self.device = None
        else:
            self.device = resolve_device(device)
        self.whisper_size = whisper_size
        self.lang = lang_lock or LanguageLock(language)
        self.on_text = on_text
        self.gate = echo_gate
        self.role = role
        self.frames: "queue.Queue[tuple[float, np.ndarray]]" = queue.Queue()
        self.stop_event = threading.Event()

    # ---------- sources ----------
    def _callback(self, indata, _frames, _time, _status):
        self.frames.put((time.monotonic(), indata[:, 0].copy()))

    @contextmanager
    def _source(self):
        if not self.command:
            with sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                blocksize=FRAME, device=self.device, callback=self._callback,
            ):
                yield
            return
        current: dict[str, subprocess.Popen] = {}
        closing = threading.Event()

        def pump():
            # macOS can interrupt a capture stream (another capture starting, sleep,
            # device change). Restart the helper instead of going deaf for the session.
            nbytes = FRAME * 4  # float32
            while True:
                proc = current["p"] = subprocess.Popen(self.command, stdout=subprocess.PIPE)
                assert proc.stdout
                while chunk := proc.stdout.read(nbytes):
                    usable = len(chunk) - len(chunk) % 4
                    self.frames.put((time.monotonic(), np.frombuffer(chunk[:usable], dtype=np.float32).copy()))
                code = proc.wait()
                if closing.is_set() or not self.restart:
                    print(f"[audio] {self.speaker} source exited (code {code})")
                    return
                print(f"[audio] {self.speaker} source exited (code {code}), restarting in {RESTART_DELAY_S:.0f}s…")
                if closing.wait(RESTART_DELAY_S):
                    return

        threading.Thread(target=pump, daemon=True).start()
        try:
            yield
        finally:
            closing.set()
            if "p" in current:
                current["p"].terminate()

    # ---------- main loop ----------
    def run(self):
        model = get_model(self.whisper_size)
        buf: list[np.ndarray] = []
        loud_frames = 0
        voiced = False
        last_voice = 0.0
        started = 0.0
        gated = self.gate is not None and self.role == "gated"
        with self._source():
            while not self.stop_event.is_set():
                try:
                    ts, frame = self.frames.get(timeout=0.2)
                except queue.Empty:
                    continue
                if self.gate and self.role == "reference":
                    self.gate.feed(ts, frame)
                if gated:
                    wait = ts + EchoGate.LEAD_S - time.monotonic()
                    if wait > 0:
                        time.sleep(wait)
                    if self.gate.is_echo(ts):
                        frame = np.zeros_like(frame)
                        self.gate.muted_frames += 1
                loud = float(np.sqrt(np.mean(frame ** 2))) > SILENCE_RMS
                if loud:
                    if not voiced:
                        voiced, started = True, ts
                    last_voice = ts
                if voiced:
                    buf.append(frame)
                    loud_frames += loud
                    ended = ts - last_voice > END_SILENCE_S
                    too_long = ts - started > MAX_UTTERANCE_S
                    if ended or too_long:
                        audio = np.concatenate(buf)
                        enough_voice = loud_frames * FRAME_MS / 1000 >= MIN_VOICED_S
                        buf, voiced, loud_frames = [], False, 0
                        if len(audio) / SAMPLE_RATE >= MIN_UTTERANCE_S and enough_voice:
                            self._transcribe(model, audio)

    def _transcribe(self, model, audio: np.ndarray):
        segments, info = model.transcribe(
            audio, language=self.lang.language, vad_filter=True, beam_size=1,
        )
        text = " ".join(
            s.text.strip() for s in segments
            if s.no_speech_prob <= NO_SPEECH_MAX and s.avg_logprob >= MIN_AVG_LOGPROB
            and s.compression_ratio <= MAX_COMPRESSION
        ).strip()
        text = clean_transcript(text)
        # Only the other side teaches the lock: your accent is what confuses the detector.
        if self.speaker != "me":
            self.lang.vote(info.language, info.language_probability, len(text.split()))
        if text:
            self.on_text(self.speaker, text)


# ---------- text helpers ----------
# Phrases Whisper invents on noise or silence (it was trained on lots of subtitled videos).
HALLUCINATIONS = (
    "for watching", "subscribe to", "like and subscribe", "next video", "subtitles by",
    "obrigado por assistir", "legendas pela", "inscreva-se",
)
MAX_REPEATS = 2  # "Bye! Bye! Bye! Bye!" → "Bye! Bye!"


def clean_transcript(text: str) -> str:
    """Drop Whisper's typical hallucinations: stock video phrases and runaway repetition."""
    import re
    tokens = text.split()
    norm = [re.sub(r"\W", "", t.lower()) for t in tokens]
    out: list[str] = []
    i = 0
    while i < len(tokens):
        for n in (1, 2, 3, 4):  # collapse an n-word group repeated more than MAX_REPEATS times
            gram = norm[i:i + n]
            if len(gram) < n or not any(gram):
                continue
            reps = 1
            while norm[i + reps * n:i + (reps + 1) * n] == gram:
                reps += 1
            if reps > MAX_REPEATS:
                out += tokens[i:i + n * MAX_REPEATS]
                i += reps * n
                break
        else:
            out.append(tokens[i])
            i += 1
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(out))
    keep = [x for x in sentences if not any(h in x.lower() for h in HALLUCINATIONS)]
    return " ".join(keep).strip()


def _words(text: str) -> list[str]:
    return [w for w in "".join(c.lower() if c.isalnum() else " " for c in text).split() if w]


def is_echo_text(me_text: str, recent_them: list[str], threshold: float = 0.6) -> bool:
    """True when most words of a 'me' line were just said by 'them'."""
    mine = _words(me_text)
    if len(mine) < 2:
        return bool(mine) and any(mine[0] in _words(t) for t in recent_them)
    theirs = set(w for t in recent_them for w in _words(t))
    return sum(w in theirs for w in mine) / len(mine) >= threshold


# Question detection lives in questions.py; re-exported here for callers.
from .questions import looks_like_question  # noqa: E402,F401
