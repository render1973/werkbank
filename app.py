"""
Besprechung → Protokoll Pipeline
=================================
Lokale Web-Oberfläche: Audio hochladen → Whisper (GPU) transkribiert →
je nach gewählter Verarbeitung: nur Transkript lokal, ODER Claude erstellt
strukturiertes Protokoll (Cloud), ODER ein lokales LLM via Ollama erstellt
das Protokoll (kein Datenabfluss). Ausgabe als .md/.docx (Protokoll) bzw.
.txt (Transkript). Mit Sitzungsreihen-Verwaltung und Pendenzen-Abgleich
zum letzten Protokoll derselben Reihe (nur bei Protokoll-Modi).

Start:
    python app.py   (oder start.bat unter Windows)
Dann im Browser: http://127.0.0.1:5000
"""

import os
import uuid
import datetime
from pathlib import Path

from flask import Flask, request, render_template, jsonify, send_from_directory
from dotenv import load_dotenv

load_dotenv(override=True)  # MUSS vor den eigenen Modul-Imports laufen,
# sonst sehen protocol.py / protocol_local.py beim Start noch die
# hartcodierten Platzhalter statt der echten .env-Werte.

from transcribe import transcribe_audio
from protocol import generate_protocol
from protocol_local import generate_protocol_local, OllamaNichtErreichbar, OLLAMA_MODEL
from docx_export import save_as_docx
import sitzungsreihe as sr

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
MODUS_CLOUD = "protokoll_cloud"          # bestehend: Claude API
MODUS_LOKAL = "protokoll_lokal"          # neu: Ollama, kein Cloud-Zugriff
GUELTIGE_MODI = {MODUS_TRANSKRIPT, MODUS_CLOUD, MODUS_LOKAL}
STANDARD_MODUS = MODUS_CLOUD  # bisheriges Verhalten bleibt Default, bis bewusst geändert

ENGINE_LABEL = {
    MODUS_CLOUD: "Cloud (Claude API)",
    MODUS_LOKAL: f"lokal ({OLLAMA_MODEL})",
}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH


@app.route("/")
def index():
    return render_template("index.html", reihen=sr.list_reihen())


@app.route("/reihen")
def get_reihen():
    """Für dynamisches Nachladen der Reihenliste im Frontend, falls gewünscht."""
    return jsonify({"reihen": sr.list_reihen()})


@app.route("/process", methods=["POST"])
def process():
    """Nimmt eine Audiodatei entgegen, transkribiert sie lokal, und verarbeitet
    sie je nach gewähltem Modus weiter:
      - transkript:        nur lokale Transkription, kein weiterer Schritt
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

    meeting_title = request.form.get("title", "").strip() or "Besprechung"
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

    except Exception as exc:
        return jsonify({"error": f"Verarbeitung fehlgeschlagen: {exc}"}), 500

    finally:
        try:
            audio_path.unlink(missing_ok=True)
        except Exception:
            pass


@app.route("/download/<reihe>/<filename>")
def download(reihe, filename):
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
    app.run(host="127.0.0.1", port=5000, debug=False)
