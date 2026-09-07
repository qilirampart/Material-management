"""Throttled byte progress; transport retries reset the active stream."""
import time


class DownloadProgress:
    def __init__(self, emit, clock=time.monotonic):
        self.emit, self.clock = emit, clock
        self.started = self.last = clock()
        self.bytes = 0

    def __call__(self, received, total):
        now = self.clock()
        if received == 0 or received < self.bytes:
            self.started = now
            self.last = now - 1
        self.bytes = received
        if now - self.last < .3 and not (total > 0 and received >= total):
            return
        self.last = now
        total = total if total >= received and total > 0 else 0
        self.emit({'type': 'download_progress', 'received': received, 'total': total,
                   'speed': received / max(now - self.started, .001),
                   'percent': min(100, round(received * 100 / total, 1)) if total else None})
