"""Streams a 16 kHz mono float32 PCM file to stdout in real time (fake call audio)."""
import sys, time
import numpy as np

path, start_at, tail_s = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
audio = np.fromfile(path, dtype=np.float32)
sr, frame = 16000, 480
out = sys.stdout.buffer
t0 = time.time()
def emit(chunk, i):
    target = t0 + i * frame / sr
    d = target - time.time()
    if d > 0: time.sleep(d)
    out.write(chunk.astype(np.float32).tobytes()); out.flush()
lead = np.zeros(int((start_at - time.time()) * sr), dtype=np.float32) if start_at > time.time() else np.zeros(0, np.float32)
full = np.concatenate([lead, audio, np.zeros(int(tail_s * sr), np.float32)])
for i in range(0, len(full) // frame):
    emit(full[i*frame:(i+1)*frame], i)
