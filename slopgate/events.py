"""A small in-process event bus: the pipeline publishes each stage of each PR, and the 3D view,
the dashboard and `demo/watch.py` subscribe over server-sent events."""

import queue
import threading
import time
from collections import deque
from typing import Callable

Emit = Callable[..., None]


class Bus:
    def __init__(self, keep: int = 400):
        self._subs: list[queue.Queue] = []
        self._lock = threading.Lock()
        self.recent: deque[dict] = deque(maxlen=keep)

    def publish(self, event: dict) -> None:
        event = {"t": time.time(), **event}
        with self._lock:
            self.recent.append(event)
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(event)
            except queue.Full:
                pass  # a stalled client misses events rather than stalling the gate

    def subscribe(self) -> tuple[queue.Queue, list[dict]]:
        q: queue.Queue = queue.Queue(maxsize=2000)
        with self._lock:
            self._subs.append(q)
            return q, list(self.recent)

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def emitter(self, url: str, source: str) -> Emit:
        """One PR's journey: every event carries the same id."""
        run_id = f"{url}#{time.time_ns()}"

        def emit(stage: str, **data) -> None:
            self.publish({"id": run_id, "url": url, "source": source, "stage": stage, **data})
        return emit


def quiet(stage: str, **data) -> None:
    """The emitter for callers that don't watch (the CLI, the evaluation)."""
