"""
Sidecar-Service: PDF-Anonymisierung als lokaler Web-Service.

Kapselt die bestehende batch_pipeline.py-Logik (PaddleOCR-VL + Presidio/GLiNER)
hinter zwei HTTP-Endpunkten. Läuft als EIGENER Prozess im venv ocr-env, damit
die Abhängigkeiten (PyYAML 6.0.2, paddlepaddle-gpu cu118 usw.) nicht mit dem
Hub-Prozess (Whisper-venv) kollidieren.

WICHTIG (Stand 28.08.2026) - GEÄNDERT gegenüber der ursprünglichen Version:
PaddleOCR-VL hat einen bekannten Bug - eine PaddleOCRVL-Instanz verträgt nur
EINEN .predict()-Aufruf zuverlässig, der zweite crasht deterministisch mit
"int(Tensor) is not supported in static graph mode" und korrumpiert danach
den GPU-Zustand des Prozesses unreparierbar. Das urspruengliche Design hier
("Modelle bleiben nach dem ersten Request im Speicher, kein Reload pro PDF")
ist fuer PaddleOCR-VL darum NICHT haltbar - jeder /process-Aufruf braucht
zwingend eine frische Instanz. Darum laeuft der OCR-Schritt jetzt pro Request
in einem eigenen Subprozess (ocr_worker.py, via batch_pipeline.convert_pdf_
via_subprocess) statt im Sidecar-Prozess selbst.

Presidio + GLiNER sind vom Bug NICHT betroffen (laufen ohnehin auf CPU,
map_location="cpu") und bleiben wie bisher warm im Sidecar-Prozess - dafuer
gilt das "einmal laden, danach resident"-Prinzip weiterhin.

Nebeneffekt: da der OCR-Subprozess nach jedem Job sofort beendet wird, gibt
er seinen VRAM automatisch frei. Der Idle-Timeout unten ist fuer die
PaddleOCR-VL-VRAM-Freigabe damit nicht mehr noetig, bleibt aber aktiv fuer
Presidio/GLiNER (unschaedlich, da CPU-only ohnehin kein VRAM betrifft -
kann bei Bedarf auch ganz entfernt werden).

Voraussetzung: diese Datei liegt im selben Ordner wie batch_pipeline.py und
ocr_worker.py (werkbank\\apps\\anonymisierung\\), damit der Import funktioniert.
Zusätzlich im venv ocr-env installieren: pip install flask

Start:
    <ocr-env>\\Scripts\\python.exe anonymize_service.py

Läuft auf http://127.0.0.1:5001

Endpunkte:
    GET  /health   -> Status, ob Presidio/GLiNER schon geladen sind
    GET  /status   -> {"phase": "idle"|"ocr_laeuft"|"anonymisierung_laeuft"}
                       grobe Phase des laufenden /process-Jobs, gepollt vom
                       Hub (kein Seiten-Fortschritt - für den Nutzen zu
                       aufwendig, siehe _set_status_phase() unten)
    POST /process  -> {"pdf_path": "...", "output_dir": "..." (optional)}
                       -> {"success": true, "roh_path": "...",
                           "anonymisiert_path": "...", "n_hits": int,
                           "elapsed_seconds": float}

Idle-Timeout: nach IDLE_TIMEOUT_SECONDS ohne neue /process-Anfrage beendet
sich der Prozess selbst (os._exit). Aktiv erst nach dem ersten erfolgreich
geladenen Presidio/GLiNER-Modell - siehe _touch_idle_timer().
"""

import contextlib
import os
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request

from batch_pipeline import anonymize, build_analyzer_and_anonymizer, convert_pdf_via_subprocess

app = Flask(__name__)

PORT = int(os.getenv("ANONYMIZE_SERVICE_PORT", "5001"))

# --- GPU-Sperre --------------------------------------------------------
# Einfache datei-basierte Sperre, damit Hub (Whisper) und dieser Sidecar
# (PaddleOCR + GLiNER) sich nicht gleichzeitig um die GPU streiten. Bewusst
# simpel gehalten (nur Standardbibliothek) - fuer den Einzelnutzer-Fall
# reicht das; ein Redis/Celery-Lock waere hier Overkill.
#
# WICHTIG: Dieser Pfad muss identisch sein mit dem, was der Hub-Prozess
# verwendet (shared/gpu.lock relativ zum Projekt-Root) - siehe Hub-Integration.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
GPU_LOCK_PATH = Path(os.getenv("GPU_LOCK_PATH", str(PROJECT_ROOT / "shared" / "gpu.lock")))
GPU_LOCK_STALE_SECONDS = 600  # hängengebliebenen Lock nach 10 Min ignorieren (z.B. nach Absturz)


@contextlib.contextmanager
def gpu_lock():
    GPU_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)

    if GPU_LOCK_PATH.exists():
        age = time.time() - GPU_LOCK_PATH.stat().st_mtime
        if age > GPU_LOCK_STALE_SECONDS:
            GPU_LOCK_PATH.unlink(missing_ok=True)

    try:
        # "x" = exklusiv anlegen, schlaegt fehl wenn Datei schon existiert -> atomar
        with open(GPU_LOCK_PATH, "x") as f:
            f.write(f"anonymize_service pid={os.getpid()} ts={time.time()}")
    except FileExistsError:
        raise RuntimeError(
            "GPU ist gerade durch einen anderen Prozess belegt (gpu.lock vorhanden). "
            "Bitte kurz warten und erneut versuchen."
        )

    try:
        yield
    finally:
        GPU_LOCK_PATH.unlink(missing_ok=True)


# --- Presidio/GLiNER: lazy geladen, bleiben resident --------------------
# PaddleOCR-VL läuft NICHT mehr hier - siehe convert_pdf_via_subprocess()
# in batch_pipeline.py (frischer Prozess pro PDF, wegen Paddle-Bug).
_analyzer = None
_anonymizer = None


def _get_models():
    global _analyzer, _anonymizer
    if _analyzer is None:
        print("Lade Presidio/GLiNER (einmalig) ...")
        t0 = time.time()
        _analyzer, _anonymizer = build_analyzer_and_anonymizer()
        print(f"Presidio/GLiNER geladen in {time.time() - t0:.1f}s.")
    return _analyzer, _anonymizer


# --- Idle-Timeout: Prozess beendet sich selbst -----------------------
# Aktiv erst nach dem ersten erfolgreichen Modell-Laden. Wird nach jeder
# abgeschlossenen /process-Anfrage zurueckgesetzt (Erfolg oder Fehler) -
# siehe finally-Block in process().
IDLE_TIMEOUT_SECONDS = int(os.getenv("IDLE_TIMEOUT_SECONDS", "600"))

_idle_timer = None
_idle_timer_lock = threading.Lock()


def _idle_timeout_exit():
    # flush=True: os._exit() unten ueberspringt Pythons normales Shutdown
    # (inkl. Flush der stdout-Puffer) - ohne expliziten Flush kann die
    # Meldung verloren gehen, wenn stdout nicht in ein Terminal, sondern
    # z.B. in eine Log-Datei umgeleitet ist (dort voll statt zeilengepuffert).
    print("Idle-Timeout erreicht, beende mich selbst", flush=True)
    # os._exit statt sys.exit: beendet den kompletten Prozess inkl. aller
    # Threads sofort, ohne auf sauberes Herunterfahren von Flask/Werkzeug
    # zu warten.
    os._exit(0)


def _touch_idle_timer():
    global _idle_timer
    if _analyzer is None:
        return  # noch keine Modelle geladen - nichts zu ueberwachen
    with _idle_timer_lock:
        if _idle_timer is not None:
            _idle_timer.cancel()
        _idle_timer = threading.Timer(IDLE_TIMEOUT_SECONDS, _idle_timeout_exit)
        _idle_timer.daemon = True
        _idle_timer.start()


# --- Grober Status fuer /status-Polling durch den Hub ---------------------
# Bewusst nur grobe Phasen, kein Seiten-Fortschritt (zu aufwendig fuer den
# Nutzen). Eigener Lock statt Wiederverwendung von _idle_timer_lock, damit
# ein Status-Read nie auf eine Idle-Timer-Operation warten muss.
_status_lock = threading.Lock()
_status_phase = "idle"


def _set_status_phase(phase: str) -> None:
    global _status_phase
    with _status_lock:
        _status_phase = phase


# --- Endpunkte -----------------------------------------------------------
@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "models_loaded": _analyzer is not None,
    })


@app.route("/status")
def status():
    with _status_lock:
        phase = _status_phase
    return jsonify({"phase": phase})


@app.route("/process", methods=["POST"])
def process():
    data = request.get_json(silent=True) or {}
    pdf_path_str = data.get("pdf_path")
    output_dir_str = data.get("output_dir")

    try:
        if not pdf_path_str:
            return jsonify({"error": "pdf_path fehlt."}), 400

        pdf_path = Path(pdf_path_str)
        if not pdf_path.is_file():
            return jsonify({"error": f"PDF nicht gefunden: {pdf_path}"}), 404

        work_dir = Path(output_dir_str) if output_dir_str else pdf_path.parent / pdf_path.stem
        work_dir.mkdir(parents=True, exist_ok=True)

        t0 = time.time()
        try:
            with gpu_lock():
                analyzer, anonymizer = _get_models()

                _set_status_phase("ocr_laeuft")
                # Läuft in einem frischen Subprozess (ocr_worker.py) - siehe
                # Modul-Docstring, Grund: PaddleOCR-VL-Bug bei Wiederverwendung.
                merged_text = convert_pdf_via_subprocess(pdf_path, work_dir)
                roh_path = work_dir / "roh.md"

                _set_status_phase("anonymisierung_laeuft")
                anonymized_text, n_hits = anonymize(merged_text, analyzer, anonymizer)
                anonymisiert_path = work_dir / "anonymisiert.md"
                anonymisiert_path.write_text(anonymized_text, encoding="utf-8")

        except RuntimeError as exc:
            # GPU aktuell belegt ODER OCR-Worker-Subprozess fehlgeschlagen
            return jsonify({"error": str(exc)}), 503
        except Exception as exc:
            return jsonify({"error": f"Verarbeitung fehlgeschlagen: {exc}"}), 500

        return jsonify({
            "success": True,
            "roh_path": str(roh_path),
            "anonymisiert_path": str(anonymisiert_path),
            "n_hits": n_hits,
            "elapsed_seconds": round(time.time() - t0, 1),
        })
    finally:
        # Nach jeder abgeschlossenen Anfrage (Erfolg oder Fehler) den
        # Idle-Timer zuruecksetzen - ein no-op, solange noch keine Modelle
        # geladen sind.
        _touch_idle_timer()
        _set_status_phase("idle")


if __name__ == "__main__":
    print("=" * 60)
    print("PDF-Anonymisierung - Sidecar-Service")
    print("=" * 60)
    print(f"Server läuft auf http://127.0.0.1:{PORT}")
    print("PaddleOCR-VL läuft pro PDF in einem eigenen Subprozess (Bug-Workaround).")
    print("Presidio/GLiNER werden beim ersten /process-Aufruf geladen und bleiben resident.")
    print("=" * 60)
    # threaded=True: /health und /status muessen waehrend eines laufenden
    # /process-Requests weiter antworten koennen (Status-Polling). Die
    # eigentliche GPU-Arbeit bleibt trotzdem serialisiert - dafuer sorgt
    # gpu_lock() als dateibasierte Sperre, unabhaengig vom Threading hier.
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
