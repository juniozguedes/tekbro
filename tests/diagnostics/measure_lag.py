"""Measures how much later macOS system-audio capture delivers a sound than the mic hears it."""
import subprocess, sys, threading, time
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from tekbro import audio as A

B = ROOT / "build"
results = []
for trial in range(3):
    onsets = {}
    def make_cb(name):
        def cb(s, t): pass
        return cb
    sysl = A.Listener("them", "macos", "small", "en", make_cb("them"), call_app="QuickTime Player")
    mic = A.Listener("me", None, "small", "en", make_cb("me"))
    # Read raw frames directly instead of running the transcription loop.
    def watch(l, name, thr):
        with l._source():
            t_end = time.monotonic() + 9
            while time.monotonic() < t_end:
                try: ts, f = l.frames.get(timeout=0.2)
                except Exception: continue
                if name not in onsets and np.sqrt(np.mean(f**2)) > thr: onsets[name] = ts
    th = [threading.Thread(target=watch, args=(sysl, "system", 0.004)), threading.Thread(target=watch, args=(mic, "mic", 0.012))]
    [t.start() for t in th]
    time.sleep(2.5)
    subprocess.run(["osascript", "-e", 'tell application "QuickTime Player"', "-e", f'set d to open POSIX file "{B/"them_q.aiff"}"', "-e", "play d", "-e", "end tell"])
    [t.join() for t in th]
    subprocess.run(["osascript", "-e", 'tell application "QuickTime Player" to close every document'])
    if len(onsets) == 2:
        lag = onsets["system"] - onsets["mic"]
        results.append(lag)
        print(f"trial {trial+1}: system capture lag vs mic = {lag*1000:+.0f} ms")
    else:
        print("trial", trial+1, "missing onset", onsets)
subprocess.run(["osascript", "-e", 'tell application "QuickTime Player" to quit'])
if results: print(f"max lag: {max(results)*1000:+.0f} ms")
