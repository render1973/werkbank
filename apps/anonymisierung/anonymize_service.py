"""
Sidecar-Service: PDF-Anonymisierung als lokaler Web-Service.

Kapselt die bestehende batch_pipeline.py-Logik (PaddleOCR-VL + Presidio/GLiNER)
hinter zwei HTTP-Endpunkten. Läuft als EIGENER Prozess im venv ocr-env, damit
die Abhängigkeiten (PyYAML 6.0.2, paddlepaddle-gpu cu118 usw.) nicht mit dem
Hub-Prozess (Whisper-venv) kollidieren.

Die Kernlogik selbst wurde NICHT verändert - convert_pdf() und anonymize()
aus batch_pipeline.py arbeiten bereits pro Einzel-PDF, das passt direkt.

Modelle werden beim ersten Request geladen und bleiben danach im Speicher
(Ladezeit ~60s, soll nicht bei jedem PDF erneut passieren) - gleiches Prinzip
wie transcribe.py im Hub (_model = None, lazy).

Voraussetzung: diese Datei liegt im selben Ordner wie batch_pipeline.py
(aktuell C:\\Users\\thoma\\ocr-test\\), damit der Import funktioniert.
Zusätzlich im venv ocr-env installieren: pip install flask

Start:
    <ocr-env>\\Scripts\\python.exe anonymize_service.py

Läuft auf http://127.0.0.1:5001

Endpunkte:
    GET  /health   -> Status, ob Modelle schon geladen sind
    GET  /status   -> {"phase": "idle"|"modelle_laden"|"ocr_laeuft"|"anonymisierung_laeuft"}
                       grobe Phase des laufenden /process-Jobs, gepollt vom
                       Hub (kein Seiten-Fortschritt - für den Nutzen zu
                       aufwendig, siehe _set_status_phase() unten)
    POST /process  -> {"pdf_path": "...", "output_dir": "..." (optional)}
                       -> {"success": true, "roh_path": "...",
                           "anonymisiert_path": "...", "n_hits": int,
                           "elapsed_seconds": float}

Idle-Timeout: nach IDLE_TIMEOUT_SECONDS ohne neue /process-Anfrage beendet
sich der Prozess selbst (os._exit), um den VRAM freizugeben. Aktiv erst
nach dem ersten erfolgreich geladenen Modell - siehe _touch_idle_timer().
"""

import contextlib
import os
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request

from batch_pipeline import anonymize, build_analyzer_and_anonymizer, convert_pdf

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


# --- Modelle: lazy geladen, bleiben resident ---------------------------
_ocr_pipeline = None
_analyzer = None
_anonymizer = None


def _get_models():
    global _ocr_pipeline, _analyzer, _anonymizer
    if _ocr_pipeline is None:
        print("Lade PaddleOCR-VL + Presidio/GLiNER (einmalig, ca. 60s) ...")
        t0 = time.time()
        from paddleocr import PaddleOCRVL

        _ocr_pipeline = PaddleOCRVL()
        _analyzer, _anonymizer = build_analyzer_and_anonymizer()
        print(f"Modelle geladen in {time.time() - t0:.1f}s.")
    return _ocr_pipeline, _analyzer, _anonymizer


# --- Idle-Timeout: Prozess beendet sich selbst, um VRAM freizugeben ------
# Aktiv erst nach dem ersten erfolgreichen Modell-Laden (vorher gibt es
# nichts freizugeben). Wird nach jeder abgeschlossenen /process-Anfrage
# zurueckgesetzt (Erfolg oder Fehler) - siehe finally-Block in process().
IDLE_TIMEOUT_SECONDS = int(os.getenv("IDLE_TIMEOUT_SECONDS", "600"))

_idle_timer = None
_idle_timer_lock = threading.Lock()


def _idle_timeout_exit():
    # flush=True: os._exit() unten ueberspringt Pythons normales Shutdown
    # (inkl. Flush der stdout-Puffer) - ohne expliziten Flush kann die
    # Meldung verloren gehen, wenn stdout nicht in ein Terminal, sondern
    # z.B. in eine Log-Datei umgeleitet ist (dort voll statt zeilengepuffert).
    print("Idle-Timeout erreicht, beende mich selbst zur VRAM-Freigabe", flush=True)
    # os._exit statt sys.exit: beendet den kompletten Prozess inkl. aller
    # Threads sofort, ohne auf sauberes Herunterfahren von Flask/Werkzeug
    # zu warten - garantiert, dass der VRAM tatsaechlich freigegeben wird.
    os._exit(0)


def _touch_idle_timer():
    global _idle_timer
    if _ocr_pipeline is None:
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
        "models_loaded": _ocr_pipeline is not None,
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
                if _ocr_pipeline is None:
                    _set_status_phase("modelle_laden")
                ocr_pipeline, analyzer, anonymizer = _get_models()

                _set_status_phase("ocr_laeuft")
                merged_text = convert_pdf(pdf_path, work_dir, ocr_pipeline)
                roh_path = work_dir / "roh.md"
                roh_path.write_text(merged_text, encoding="utf-8")

                _set_status_phase("anonymisierung_laeuft")
                anonymized_text, n_hits = anonymize(merged_text, analyzer, anonymizer)
                anonymisiert_path = work_dir / "anonymisiert.md"
                anonymisiert_path.write_text(anonymized_text, encoding="utf-8")

        except RuntimeError as exc:
            # GPU aktuell belegt
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
    print("Modelle werden beim ersten /process-Aufruf geladen (~60s).")
    print("=" * 60)
    # threaded=True: /health und /status muessen waehrend eines laufenden
    # /process-Requests weiter antworten koennen (Status-Polling). Die
    # eigentliche GPU-Arbeit bleibt trotzdem serialisiert - dafuer sorgt
    # gpu_lock() als dateibasierte Sperre, unabhaengig vom Threading hier.
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
