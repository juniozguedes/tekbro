"""Live speaker-echo test.

Plays a question out loud AND streams it as call audio ("them"), then plays a
different sentence out loud only (simulating you speaking). With the echo gate,
the question must appear only as "them" and the second sentence as "me".

    .venv/bin/python tests/echo_test.py            # gate on
    .venv/bin/python tests/echo_test.py --no-gate  # baseline
"""
import subprocess, sys, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import os  # noqa: E402
os.environ["TEKBRO_ALLOW_CMD_SOURCE"] = "1"
from tekbro import audio as A  # noqa: E402
from tekbro.app import TekBro  # noqa: E402
from tekbro.config import Config  # noqa: E402

B = ROOT / "build"
B.mkdir(exist_ok=True)
QUESTION = "Can you explain how a hash map works and what its time complexity is?"
ANSWER = "I would use an array of buckets and handle collisions with chaining."

def synth(voice, text, name):
    subprocess.run(["say", "-v", voice, "-o", str(B / f"{name}.aiff"), text], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(B / f"{name}.aiff"),
                    "-ar", "16000", "-ac", "1", "-f", "f32le", str(B / f"{name}.pcm")], check=True)

synth("Samantha", QUESTION, "them_q")
synth("Daniel", ANSWER, "me_a")

gate = "--no-gate" not in sys.argv
cfg = Config()
cfg.echo_cancel = gate
cfg.auto_answer = False
cfg.language = "en"
start_at = time.time() + 8  # leave time for the model to load
# OFFSET>0: call audio reaches Tek Bro later than the speakers play it (capture lag)
# OFFSET<0: speakers play later than the capture (e.g. Bluetooth latency)
import os
offset = float(os.getenv("OFFSET", "0"))
real = os.getenv("REAL") == "1"   # real macOS capture: QuickTime plays "them"
if real:
    cfg.system_device, cfg.call_app = "macos", "QuickTime Player"
    subprocess.run(["open", "-a", "QuickTime Player"])
    time.sleep(2)
else:
    cfg.system_device = f"cmd:{sys.executable} {ROOT/'tests'/'stream_pcm.py'} {B/'them_q.pcm'} {start_at + offset} 14"
A.get_model(cfg.whisper_model)

j = TekBro(cfg, use_audio=True, use_screen=False)
lines = []
orig = j._publish_text
j._publish_text = lambda s, t, ts=None: (lines.append((s, t)), orig(s, t, ts))
j.start()

def play():
    time.sleep(max(0, start_at - time.time()))
    if real:  # the other person, via a "call app" that Tek Bro captures
        subprocess.run(["osascript", "-e", 'tell application "QuickTime Player"',
                        "-e", f'set d to open POSIX file "{B / "them_q.aiff"}"', "-e", "play d", "-e", "end tell"])
        time.sleep(5)
    else:     # the other person, through the speakers
        subprocess.run(["afplay", str(B / "them_q.aiff")])
    time.sleep(1.5)
    subprocess.run(["afplay", str(B / "me_a.aiff")])        # "you", talking in the room
threading.Thread(target=play, daemon=True).start()
time.sleep(start_at - time.time() + 20)
if real:
    subprocess.run(["osascript", "-e", 'tell application "QuickTime Player" to quit'])

print("\n===== RESULT (gate %s, offset %+.2fs) =====" % ("ON" if gate else "OFF", offset))
for s, t in lines:
    print(f"  [{s}] {t}")
if j.echo_gate:
    print(f"  muted mic frames: {j.echo_gate.muted_frames}")
them_ok = any(s == "them" and "hash map" in t.lower() for s, t in lines)
echo_leak = any(s == "me" and "hash" in t.lower() for s, t in lines)
me_ok = any(s == "me" and ("bucket" in t.lower() or "chaining" in t.lower()) for s, t in lines)
print(f"  them heard question: {them_ok} | echo leaked into me: {echo_leak} | my speech kept: {me_ok}")
