"""Records mic + system audio with arrival timestamps; estimates lag by envelope cross-correlation."""
import subprocess, sys, threading, time
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from tekbro import audio as A
B = ROOT / "build"

def record(l, out, secs):
    with l._source():
        end = time.monotonic() + secs
        while time.monotonic() < end:
            try: out.append(l.frames.get(timeout=0.2))
            except Exception: pass

def envelope(frames, t0, t1, hop=0.01):
    n = int((t1 - t0) / hop); env = np.zeros(n)
    for ts, f in frames:
        i = int((ts - t0) / hop)
        if 0 <= i < n: env[i] = max(env[i], np.sqrt(np.mean(f ** 2)))
    return env

sysf, micf = [], []
s = A.Listener("them", "macos", "small", "en", lambda *a: None, call_app="QuickTime Player")
m = A.Listener("me", None, "small", "en", lambda *a: None)
th = [threading.Thread(target=record, args=(s, sysf, 20)), threading.Thread(target=record, args=(m, micf, 20))]
[t.start() for t in th]
for at in (3, 10):
    time.sleep(at - (3 if at == 10 else 0) if at == 3 else 7)
    subprocess.run(["osascript", "-e", 'tell application "QuickTime Player"', "-e", f'set d to open POSIX file "{B/"them_q.aiff"}"', "-e", "play d", "-e", "end tell"], capture_output=True)
[t.join() for t in th]
subprocess.run(["osascript", "-e", 'tell application "QuickTime Player" to quit'])
t0 = min(sysf[0][0], micf[0][0]); t1 = max(sysf[-1][0], micf[-1][0])
es, em = envelope(sysf, t0, t1), envelope(micf, t0, t1)
hop = 0.01
for name, (a, b) in {"play 1": (0, 900), "play 2": (900, len(es))}.items():
    x, y = es[a:b] - es[a:b].mean(), em[a:b] - em[a:b].mean()
    lags = range(-150, 151)  # ±1.5 s
    corr = [np.dot(x[max(0, L):len(x) + min(0, L)], y[max(0, -L):len(y) - max(0, L)]) for L in lags]
    best = lags[int(np.argmax(corr))]
    print(f"{name}: system lags mic by {best * hop * 1000:+.0f} ms")
# arrival cadence of system frames (bursty delivery shows up as big gaps)
gaps = np.diff([ts for ts, _ in sysf])
print(f"system frame arrival gaps: median {np.median(gaps)*1000:.0f} ms, p99 {np.percentile(gaps,99)*1000:.0f} ms, max {gaps.max()*1000:.0f} ms")
