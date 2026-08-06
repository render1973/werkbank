"""
Besprechung → Protokoll Pipeline
=================================
Lokale Web-Oberfläche: Audio hochladen → Whisper (GPU) transkribiert →
Claude erstellt strukturiertes Protokoll im HSLU-Layout → Ausgabe als
.md und .docx. Mit Sitzungsreihen-Verwaltung und Pendenzen-Abgleich
zum letzten Protokoll derselben Reihe.

Start:
    python app.py   (oder start.bat unter Windows)
Dann im Browser: http://127.0.0.1:5000
"""

import os
import sys
import uuid
import datetime
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

# WICHTIG: load_dotenv() muss laufen, BEVOR eigene Module importiert werden,
# die beim Import Umgebungsvariablen lesen (transcribe.py: WHISPER_*,
# GPU_LOCK_*; routes.py: STUNDENRAPPORT_PATH; protocol.py: CLAUDE_MODEL) -
# sonst sehen deren modulweiten os.getenv()-Aufrufe noch nicht die Werte aus
# .env, sondern nur die hartcodierten Defaults (fiel erst bei
# STUNDENRAPPORT_PATH auf, weil die anderen .env-Werte zufaellig mit ihren
# Defaults uebereinstimmen).
load_dotenv(override=True)

import requests
from flask import Flask, request, render_template, jsonify, send_from_directory, send_file

from transcribe import transcribe_audio, GPU_LOCK_PATH
from protocol import generate_protocol
from protocol_local import generate_protocol_local, OllamaNichtErreichbar, OLLAMA_MODEL
from docx_export import save_as_docx
import sitzungsreihe as sr
import job_status

# apps/ liegt als Geschwisterordner von hub/ (nicht darunter) - fuer den
# Projektansicht-Blueprint (apps.projektansicht) muss der Projekt-Root auf
# sys.path stehen, sonst schlaegt der Import unten fehl.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from apps.projektansicht.routes import bp as projektansicht_bp

if not os.getenv("ANTHROPIC_API_KEY") or "hier" in os.getenv("ANTHROPIC_API_KEY", ""):
    print("=" * 60)
    print("WARNUNG: Kein gültiger ANTHROPIC_API_KEY gefunden.")
    print("Die Verarbeitung 'Protokoll via Cloud' wird damit fehlschlagen.")
    print("'Nur Transkript' und 'Protokoll lokal' funktionieren trotzdem.")
    print("=" * 60)

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".mp4", ".ogg", ".flac", ".webm"}
MAX_CONTENT_LENGTH = 2 * 1024 * 1024 * 1024  # 2 GB — lange Besprechungen sind groß

# Gültige Werte für das Formularfeld "verarbeitung"
MODUS_TRANSKRIPT = "transkript"          # nur lokal, kein Protokoll, kein Cloud-Zugriff
MODUS_CLOUD = "protokoll_cloud"          # Claude API
MODUS_LOKAL = "protokoll_lokal"          # Ollama, kein Cloud-Zugriff
GUELTIGE_MODI = {MODUS_TRANSKRIPT, MODUS_CLOUD, MODUS_LOKAL}
STANDARD_MODUS = MODUS_CLOUD  # vom Nutzer bestätigt: Cloud-Protokoll ist der Regelfall

ENGINE_LABEL = {
    MODUS_CLOUD: "Cloud (Claude API)",
    MODUS_LOKAL: f"lokal ({OLLAMA_MODEL})",
}

PDF_ALLOWED_EXTENSIONS = {".pdf"}
ANONYMIZE_SERVICE_URL = os.getenv("ANONYMIZE_SERVICE_URL", "http://127.0.0.1:5001")
# Basisordner, in dem der Sidecar seine Ergebnisse ablegt — zugleich die
# einzige Stelle, aus der /download-anonymized ausliefern darf.
ANONYMIZE_APPS_DIR = (BASE_DIR.parent / "apps" / "anonymisierung").resolve()
ANONYMIZE_OUTPUT_DIR = ANONYMIZE_APPS_DIR / "output"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
app.register_blueprint(projektansicht_bp)


def _format_when(mtime: float) -> str:
    return datetime.datetime.fromtimestamp(mtime).strftime("%d.%m.%Y %H:%M")


def get_recent_transkription_results(n: int = 5) -> list:
    """Neueste Protokolle (Cloud/lokal) + reine Transkripte (Modus "transkript"),
    gemischt nach Änderungsdatum sortiert — fürs Dashboard "Letzte Ergebnisse".

    Reine Transkripte landen seit dem Verarbeitungs-Schalter im selben
    Sitzungsreihen-Ordner wie Protokolle (nicht mehr nur in "Rohfassungen"),
    als `<base>_transkript.txt` ohne begleitende `<base>.docx`. Deshalb: jede
    .docx zählt als ein Ergebnis, jede *_transkript.txt OHNE docx-Geschwister
    zählt als ein eigenes (reines Transkript-)Ergebnis — sonst würde die
    Transkript-Begleitdatei eines Protokolls doppelt auftauchen."""
    items = []
    for docx_path in OUTPUT_DIR.rglob("*.docx"):
        reihe = docx_path.parent.name
        items.append({
            "name": f"{reihe} — {docx_path.stem}",
            "url": f"/download/{reihe}/{docx_path.name}",
            "mtime": docx_path.stat().st_mtime,
        })
    for txt_path in OUTPUT_DIR.rglob("*_transkript.txt"):
        docx_geschwister = txt_path.with_name(
            txt_path.name.replace("_transkript.txt", ".docx")
        )
        if docx_geschwister.exists():
            continue  # bereits als Protokoll-Ergebnis oben gelistet
        reihe = txt_path.parent.name
        label = "Rohfassung" if reihe == "Rohfassungen" else reihe
        items.append({
            "name": f"{label} — {txt_path.stem}",
            "url": f"/download/{reihe}/{txt_path.name}",
            "mtime": txt_path.stat().st_mtime,
        })
    items.sort(key=lambda i: i["mtime"], reverse=True)
    for item in items:
        item["when"] = _format_when(item.pop("mtime"))
    return items[:n]


def get_recent_anonymisierung_results(n: int = 5) -> list:
    """Neueste anonymisierte PDFs (anonymisiert.md je Job-Ordner)."""
    items = []
    for md_path in ANONYMIZE_OUTPUT_DIR.rglob("anonymisiert.md"):
        items.append({
            "name": md_path.parent.name,
            "url": f"/download-anonymized?path={quote(str(md_path.resolve()))}",
            "mtime": md_path.stat().st_mtime,
        })
    items.sort(key=lambda i: i["mtime"], reverse=True)
    for item in items:
        item["when"] = _format_when(item.pop("mtime"))
    return items[:n]


@app.route("/")
def index():
    return render_template(
        "index.html",
        reihen=sr.list_reihen(),
        recent_transkription=get_recent_transkription_results(),
        recent_anonymisierung=get_recent_anonymisierung_results(),
    )


@app.route("/reihen")
def get_reihen():
    """Für dynamisches Nachladen der Reihenliste im Frontend, falls gewünscht."""
    return jsonify({"reihen": sr.list_reihen()})


@app.route("/status")
def status():
    """Wird vom Dashboard alle 2-3s gepollt: grobe Phase des laufenden
    Transkriptions-Jobs (inkl. Fortschritt), grobe Phase des Sidecars (per
    HTTP erfragt) und ob die GPU gerade belegt ist (gpu.lock)."""
    try:
        resp = requests.get(f"{ANONYMIZE_SERVICE_URL}/status", timeout=2)
        anon_status = resp.json() if resp.ok else {"phase": "fehler"}
    except requests.exceptions.RequestException:
        anon_status = {"phase": "nicht_erreichbar"}

    return jsonify({
        "transkription": job_status.snapshot(),
        "anonymisierung": anon_status,
        "gpu": {"belegt": GPU_LOCK_PATH.exists()},
    })


@app.route("/process", methods=["POST"])
def process():
    """Nimmt eine Audiodatei entgegen, transkribiert sie lokal (immer, GPU,
    verlässt den Rechner nie), und verarbeitet sie je nach Formularfeld
    "verarbeitung" weiter:
      - transkript:        nur lokale Transkription, kein weiterer Schritt,
                            KEIN Cloud-Zugriff
      - protokoll_cloud:    zusätzlich Protokoll via Claude API (Cloud)
      - protokoll_lokal:    zusätzlich Protokoll via lokalem LLM (Ollama)
    Pendenzen-Abgleich mit dem letzten Protokoll derselben Reihe läuft nur
    bei den beiden Protokoll-Modi."""

    if "audio" not in request.files:
        return jsonify({"error": "Keine Datei erhalten."}), 400

    file = request.files["audio"]
    if file.filename == "":
        return jsonify({"error": "Keine Datei ausgewählt."}), 400

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({
            "error": f"Dateityp {ext} nicht unterstützt. "
                     f"Erlaubt: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        }), 400

    modus = request.form.get("verarbeitung", STANDARD_MODUS).strip()
    if modus not in GUELTIGE_MODI:
        return jsonify({
            "error": f"Unbekannte Verarbeitung '{modus}'. "
                     f"Erlaubt: {', '.join(sorted(GUELTIGE_MODI))}"
        }), 400

    meeting_title = request.form.get("title", "").strip() or "Aufnahme"
    meeting_date = request.form.get("date", "").strip() or datetime.date.today().isoformat()
    meeting_time = request.form.get("time", "").strip()
    participants = request.form.get("participants", "").strip()
    custom_notes = request.form.get("notes", "").strip()
    reihe_input = request.form.get("reihe", "").strip() or meeting_title

    # Sitzungsreihe registrieren/finden — unabhängig vom Modus, damit Dateien
    # (auch reine Transkripte) organisatorisch am richtigen Ort landen.
    reihe_name = sr.register_reihe(reihe_input)
    reihe_dir = sr.get_reihe_dir(reihe_name)

    # Vorprotokoll nur relevant, wenn tatsächlich ein Protokoll entsteht
    previous_protocol = None
    previous_pendenzen = []
    previous_date = ""
    if modus in (MODUS_CLOUD, MODUS_LOKAL):
        previous_protocol = sr.find_latest_protocol(reihe_name)
        if previous_protocol:
            previous_pendenzen = sr.extract_pendenzen_from_protocol(previous_protocol)
            previous_date = sr.extract_date_from_protocol(previous_protocol)

    job_id = uuid.uuid4().hex[:8]
    safe_name = f"{job_id}{ext}"
    audio_path = UPLOAD_DIR / safe_name
    file.save(audio_path)

    try:
        # Schritt 1 — lokale Transkription (Whisper, GPU). Läuft IMMER,
        # unabhängig vom Modus, und verlässt den Rechner nie.
        transcript_result = transcribe_audio(str(audio_path))
        transcript_text = transcript_result["text"]

        if not transcript_text or len(transcript_text.strip()) < 20:
            return jsonify({
                "error": "Transkript ist leer oder zu kurz. Audio prüfen "
                         "(stumme Datei? falsches Format? sehr leise Aufnahme?)."
            }), 422

        base_name = f"{meeting_date}_Protokoll" if modus != MODUS_TRANSKRIPT \
            else f"{meeting_date}_Transkript"
        base_name = "".join(c for c in base_name if c.isalnum() or c in "_-")

        transcript_path = reihe_dir / f"{base_name}_transkript.txt"
        # Bei Namenskollision (mehrere Aufnahmen am selben Tag) job_id anhängen
        if transcript_path.exists():
            base_name = f"{base_name}_{job_id}"
            transcript_path = reihe_dir / f"{base_name}_transkript.txt"
        transcript_path.write_text(transcript_text, encoding="utf-8")

        downloads = {
            "transcript": f"/download/{reihe_name}/{transcript_path.name}",
        }

        if modus == MODUS_TRANSKRIPT:
            # Kein weiterer Schritt — insbesondere KEIN Cloud-Zugriff.
            return jsonify({
                "success": True,
                "modus": modus,
                "reihe": reihe_name,
                "text_typ": "transkript",
                "text_preview": transcript_text,
                "downloads": downloads,
                "transcript_language": transcript_result.get("language", "unbekannt"),
            })

        # Schritt 2 — Protokoll, entweder Cloud (Claude) oder lokal (Ollama)
        job_status.set_phase("protokoll_wird_erstellt")
        protocol_kwargs = dict(
            transcript=transcript_text,
            meeting_title=meeting_title,
            meeting_date=meeting_date,
            participants=participants,
            custom_notes=custom_notes,
            previous_pendenzen=previous_pendenzen,
            previous_date=previous_date,
        )
        if modus == MODUS_CLOUD:
            protocol_md = generate_protocol(**protocol_kwargs)
        else:  # MODUS_LOKAL
            protocol_md = generate_protocol_local(**protocol_kwargs)

        # Provenienz-Vermerk — bei lokalem Modell besonders wichtig, damit
        # später klar ist, mit welcher Engine (und welcher Zuverlässigkeit)
        # das Protokoll entstanden ist.
        protocol_md = (
            f"{protocol_md}\n\n---\n*Protokoll erstellt: {ENGINE_LABEL[modus]}, "
            f"{datetime.datetime.now():%d.%m.%Y %H:%M}*"
        )

        md_path = reihe_dir / f"{base_name}.md"
        if md_path.exists():
            md_path = reihe_dir / f"{base_name}_{job_id}.md"
        md_path.write_text(protocol_md, encoding="utf-8")

        docx_path = reihe_dir / f"{base_name}.docx"
        if docx_path.exists():
            docx_path = reihe_dir / f"{base_name}_{job_id}.docx"
        save_as_docx(
            protocol_md, str(docx_path),
            title=meeting_title, date=meeting_date,
            participants=participants, time=meeting_time,
        )

        downloads["docx"] = f"/download/{reihe_name}/{docx_path.name}"
        downloads["md"] = f"/download/{reihe_name}/{md_path.name}"

        return jsonify({
            "success": True,
            "modus": modus,
            "engine": ENGINE_LABEL[modus],
            "reihe": reihe_name,
            "hatte_vorprotokoll": previous_protocol is not None,
            "text_typ": "protokoll",
            "text_preview": protocol_md,
            "downloads": downloads,
            "transcript_language": transcript_result.get("language", "unbekannt"),
        })

    except OllamaNichtErreichbar as exc:
        # Eigener Fehlercode, damit das Frontend gezielt auf "Ollama starten /
        # Modell nachladen" statt auf eine generische Fehlermeldung hinweisen kann.
        return jsonify({"error": str(exc), "modus": modus}), 503
    except RuntimeError as exc:
        # GPU aktuell durch den Anonymisierungs-Sidecar belegt
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:
        return jsonify({"error": f"Verarbeitung fehlgeschlagen: {exc}"}), 500

    finally:
        job_status.set_phase("idle")
        try:
            audio_path.unlink(missing_ok=True)
        except Exception:
            pass


@app.route("/anonymize", methods=["POST"])
def anonymize():
    """Nimmt eine PDF-Datei entgegen und lässt sie vom Anonymisierungs-Sidecar
    (apps/anonymisierung/anonymize_service.py, eigener Prozess auf Port 5001)
    verarbeiten. Hub und Sidecar sehen dasselbe Dateisystem — es wird nur der
    Pfad übergeben, keine Datei per HTTP hochgeladen (siehe CLAUDE.md)."""

    if "pdf" not in request.files:
        return jsonify({"error": "Keine Datei erhalten."}), 400

    file = request.files["pdf"]
    if file.filename == "":
        return jsonify({"error": "Keine Datei ausgewählt."}), 400

    ext = Path(file.filename).suffix.lower()
    if ext not in PDF_ALLOWED_EXTENSIONS:
        return jsonify({
            "error": f"Dateityp {ext} nicht unterstützt. Erlaubt: .pdf"
        }), 400

    job_id = uuid.uuid4().hex[:8]
    safe_name = f"{job_id}{ext}"
    pdf_path = UPLOAD_DIR / safe_name
    file.save(pdf_path)

    output_dir = ANONYMIZE_OUTPUT_DIR / job_id

    try:
        try:
            response = requests.post(
                f"{ANONYMIZE_SERVICE_URL}/process",
                json={
                    "pdf_path": str(pdf_path.resolve()),
                    "output_dir": str(output_dir),
                },
                timeout=1800,  # Verarbeitung dauert je nach Seitenzahl mehrere Minuten
            )
        except requests.exceptions.ConnectionError:
            return jsonify({
                "error": "PDF-Anonymisierung läuft nicht - bitte anonymize_service.py starten"
            }), 503
        except requests.exceptions.RequestException as exc:
            return jsonify({"error": f"Verarbeitung fehlgeschlagen: {exc}"}), 500

        try:
            result = response.json()
        except ValueError:
            return jsonify({
                "error": f"Verarbeitung fehlgeschlagen: unerwartete Antwort vom "
                         f"Sidecar (Status {response.status_code})."
            }), 500

        if response.status_code == 503:
            # GPU aktuell durch anderen Prozess belegt — Meldung vom Sidecar
            # unverändert durchreichen, kein generischer 500er.
            return jsonify(result), 503

        if not response.ok:
            return jsonify({
                "error": result.get("error", f"Verarbeitung fehlgeschlagen (Status {response.status_code}).")
            }), 500

        return jsonify({
            "success": True,
            "roh_path": result["roh_path"],
            "anonymisiert_path": result["anonymisiert_path"],
            "n_hits": result["n_hits"],
        })

    finally:
        try:
            pdf_path.unlink(missing_ok=True)
        except Exception:
            pass


@app.route("/download-anonymized")
def download_anonymized():
    """Liefert eine Ergebnisdatei der PDF-Anonymisierung aus (roh_path oder
    anonymisiert_path aus der /anonymize-Antwort). Die Ergebnisse liegen als
    absolute Pfade vor und sind nicht an die Sitzungsreihen-Struktur von
    /download/<reihe>/<filename> gebunden, deshalb eigene Route.

    Path-Traversal-Schutz: der aufgelöste Pfad muss tatsächlich innerhalb von
    apps/anonymisierung/output liegen (Path.resolve() + relative_to-Vergleich),
    sonst 403 — der übergebene Pfad wird nie ungeprüft an send_file weiter-
    gereicht. Bewusst auf output/ verengt statt auf apps/anonymisierung: der
    Endpunkt soll nur Ergebnisdateien ausliefern können, nicht Quellcode
    (batch_pipeline.py) oder hochgeladene PDFs (pdfs/)."""

    path_param = request.args.get("path", "")
    if not path_param:
        return jsonify({"error": "Parameter 'path' fehlt."}), 400

    requested_path = Path(path_param).resolve()

    try:
        requested_path.relative_to(ANONYMIZE_OUTPUT_DIR)
    except ValueError:
        return jsonify({"error": "Pfad liegt außerhalb des erlaubten Ordners."}), 403

    if not requested_path.is_file():
        return jsonify({"error": "Datei nicht gefunden."}), 404

    return send_file(requested_path, as_attachment=True)


@app.route("/download/<reihe>/<filename>")
def download(reihe, filename):
    # "Rohfassungen" ist kein Sitzungsreihen-Name im eigentlichen Sinn (keine
    # Registrierung, kein Pendenzen-Abgleich) — direkt aus OUTPUT_DIR bedienen,
    # nicht über sr.get_reihe_dir (das würde zufällig auch funktionieren, ist
    # aber nicht die eigentlich vorgesehene Verwendung dieser Funktion).
    if reihe == "Rohfassungen":
        reihe_dir = OUTPUT_DIR / "Rohfassungen"
    else:
        reihe_dir = sr.get_reihe_dir(reihe)
    return send_from_directory(reihe_dir, filename, as_attachment=True)


if __name__ == "__main__":
    print("=" * 60)
    print("Besprechung → Protokoll Pipeline")
    print("=" * 60)
    print(f"Uploads:  {UPLOAD_DIR}")
    print(f"Output:   {OUTPUT_DIR}")
    print(f"Bekannte Sitzungsreihen: {sr.list_reihen() or '(keine)'}")
    print(f"Lokales Protokoll-Modell (Ollama): {OLLAMA_MODEL}")
    print("Server läuft auf http://127.0.0.1:5000")
    print("=" * 60)
    # threaded=True: /status muss waehrend eines laufenden /process- oder
    # /anonymize-Requests weiter antworten koennen (Status-Polling fuers
    # Dashboard). Die eigentliche GPU-Arbeit bleibt serialisiert - dafuer
    # sorgt gpu_lock() in transcribe.py, unabhaengig vom Threading hier.
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
