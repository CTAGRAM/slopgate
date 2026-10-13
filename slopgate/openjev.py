"""Client for the Jev-compatible /v1/systemone API (Codiv, or a self-hosted OpenJev server)."""

import math
import re
import time
from dataclasses import dataclass

import httpx

RETRY_STATUS = {429, 503, 529}


@dataclass
class Reading:
    answers: dict
    model: str
    input_tokens: int
    server_ms: float | None  # the server's own total, from the Server-Timing header
    wall_ms: float  # includes the network


def noul_confidence(p: float) -> float:
    """Same measure the server uses for choices and scores: 1 - H(p)/ln 2."""
    h = -sum(x * math.log(x) for x in (p, 1 - p) if x > 0)
    return max(0.0, 1.0 - h / math.log(2))


def _server_total(header: str | None) -> float | None:
    m = re.search(r"total;dur=([\d.]+)", header or "")
    return float(m.group(1)) if m else None


class OpenJev:
    def __init__(self, base_url: str, api_key: str | None, model: str, timeout: float = 30.0):
        self.model = model
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.Client(base_url=base_url, headers=headers, timeout=timeout)

    def ask(self, state: str, questions: dict) -> Reading:
        body = {"model": self.model, "state": state, "questions": questions}
        start = time.perf_counter()
        for attempt in range(4):
            r = self._http.post("/v1/systemone", json=body)
            if r.status_code not in RETRY_STATUS or attempt == 3:
                break
            time.sleep(float(r.headers.get("retry-after", 2)) * (attempt + 1))
        if r.status_code != 200:
            raise RuntimeError(f"OpenJev {r.status_code}: {r.text[:300]}")
        data = r.json()
        return Reading(
            answers=data["answers"],
            model=data.get("model", self.model),
            input_tokens=data.get("usage", {}).get("input_tokens", 0),
            server_ms=_server_total(r.headers.get("server-timing")),
            wall_ms=(time.perf_counter() - start) * 1000,
        )
