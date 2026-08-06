"""
Einfacher In-Memory-Status für den laufenden Transkriptions-Job, gepollt
vom Frontend (GET /status in app.py). Bewusst simpel gehalten (kein
Redis/Queue) — Einzelnutzer-Fall, ein Transkriptions-Job gleichzeitig.

Phasen: "idle", "wartet_auf_gpu", "modell_laden", "transkribiert",
"protokoll_wird_erstellt". "current"/"total" (Sekunden) sind nur während
"transkribiert" aussagekräftig, sonst 0.0.
"""

import threading

_lock = threading.Lock()
_status = {"phase": "idle", "current": 0.0, "total": 0.0}


def set_phase(phase: str, current: float = 0.0, total: float = 0.0) -> None:
    with _lock:
        _status["phase"] = phase
        _status["current"] = current
        _status["total"] = total


def snapshot() -> dict:
    with _lock:
        return dict(_status)
