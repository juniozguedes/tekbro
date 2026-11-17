"""Periodic screenshots with change detection."""
import io
import threading
import time
from typing import Callable

import mss
from PIL import Image, ImageChops, ImageStat

MAX_WIDTH = 1568          # Claude downsizes larger images anyway
CHANGE_THRESHOLD = 4.0    # mean abs diff (0-255) on a small grayscale thumbnail


class ScreenWatcher(threading.Thread):
    def __init__(self, monitor: int, interval: float, on_change: Callable[[bytes], None] | None = None):
        super().__init__(daemon=True, name="screen")
        self.monitor = monitor
        self.interval = interval
        self.on_change = on_change
        self.latest_png: bytes | None = None
        self.latest_at: float = 0.0
        self._thumb: Image.Image | None = None
        self._lock = threading.Lock()
        self.stop_event = threading.Event()

    def capture(self) -> bytes:
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[self.monitor])
        img = Image.frombytes("RGB", shot.size, shot.rgb)
        if img.width > MAX_WIDTH:
            img = img.resize((MAX_WIDTH, int(img.height * MAX_WIDTH / img.width)), Image.LANCZOS)
        thumb = img.convert("L").resize((96, 54))
        out = io.BytesIO()
        img.save(out, format="PNG", optimize=True)
        png = out.getvalue()

        with self._lock:
            changed = self._thumb is None or ImageStat.Stat(
                ImageChops.difference(self._thumb, thumb)
            ).mean[0] > CHANGE_THRESHOLD
            self._thumb = thumb
            self.latest_png, self.latest_at = png, time.time()
        if changed and self.on_change:
            self.on_change(png)
        return png

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.capture()
            except Exception as e:  # keep running if one grab fails
                print(f"[screen] capture failed: {e}")
            self.stop_event.wait(self.interval)
