"""
Lokale Protokoll-Erstellung via Ollama — dritte Option neben "nur Transkript"
und "Protokoll via Cloud (Claude API)". Läuft vollständig offline, kein
Datenabfluss.

Modell-Empfehlung (Stand August 2026, RTX 4080 Laptop 12GB VRAM):
  ministral-3:14b  — 14B, Apache-2.0, explizit Deutsch, ~9.1GB (Q4), passt
                     komfortabel in 12GB VRAM neben dem sequenziell davor
                     laufenden Whisper. Braucht Ollama >= 0.13.1 — falls
                     der Pull fehlschlägt, zuerst `ollama --version` prüfen.
  Alternative:      qwen3:14b (OLLAMA_MODEL in .env umstellen)

Setup:
    ollama pull ministral-3:14b
    (Ollama muss laufen: 'ollama serve' oder die Ollama-Desktop-App)

Nutzt dieselbe Gliederung wie protocol.py (PROTOCOL_STRUCTURE), damit lokale
und Cloud-Protokolle strukturell nicht auseinanderlaufen — es wird nur die
Konstante importiert, protocol.py bleibt unverändert.

Qualitätshinweis: Ein lokales 14B-Modell ist bei reinem Formulieren gut,
beim Pendenzen-Abgleich (Konsistenz zwischen altem und neuem Protokoll)
aber weniger zuverlässig als die Cloud-Variante. Vor Produktiveinsatz an
echten Transkripten gegentesten.
"""

import os

import requests

from protocol import PROTOCOL_STRUCTURE  # einzige Abhängigkeit zu protocol.py

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "ministral-3:14b")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "300"))  # lange Transkripte brauchen Zeit
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "16384"))  # Kontextfenster, muss in 12GB passen


class OllamaNichtErreichbar(Exception):
    """Ollama läuft nicht, oder das konfigurierte Modell ist nicht installiert."""


def _pruefe_ollama() -> None:
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        r.raise_for_status()
        installiert = [m.get("name", "") for m in r.json().get("models", [])]
    except requests.RequestException as exc:
        raise OllamaNichtErreichbar(
            f"Ollama unter {OLLAMA_URL} nicht erreichbar. Läuft der Dienst? "
            f"('ollama serve' bzw. Ollama-Desktop-App starten). "
            f"Technischer Fehler: {exc}"
        ) from exc

    basis = OLLAMA_MODEL.split(":")[0]
    if not any(m == OLLAMA_MODEL or m.startswith(basis + ":") for m in installiert):
        raise OllamaNichtErreichbar(
            f"Modell '{OLLAMA_MODEL}' ist in Ollama nicht installiert. "
            f"Zuerst ausführen: ollama pull {OLLAMA_MODEL}"
        )


def _build_prompt(transcript, meeting_title, meeting_date, participants,
                   custom_notes, previous_pendenzen, previous_date) -> str:
    pendenzen_block = ""
    if previous_pendenzen:
        punkte = "\n".join(f"- {p}" for p in previous_pendenzen)
        pendenzen_block = (
            f"\n\nOFFENE PENDENZEN AUS DEM LETZTEN PROTOKOLL ({previous_date}):\n"
            f"{punkte}\n"
            f"Bitte im neuen Protokoll pro Punkt vermerken: erledigt / "
            f"weiterhin offen / neu terminiert.\n"
        )

    zusatz = f"Zusätzliche Hinweise: {custom_notes}\n" if custom_notes else ""

    return f"""Du erstellst ein strukturiertes Besprechungsprotokoll auf Deutsch,
im Format der Hochschule Luzern. Halte dich exakt an diese Gliederung:

{PROTOCOL_STRUCTURE}

Besprechung: {meeting_title}
Datum: {meeting_date}
Teilnehmende: {participants or "nicht angegeben"}
{zusatz}{pendenzen_block}
TRANSKRIPT:
{transcript}

Gib ausschliesslich das fertige Protokoll als Markdown zurück — ohne
Einleitungssatz, ohne Kommentar davor oder danach, ohne Code-Fences."""


def generate_protocol_local(transcript: str, meeting_title: str, meeting_date: str,
                             participants: str, custom_notes: str,
                             previous_pendenzen: list, previous_date: str) -> str:
    """Drop-in-Ersatz für protocol.generate_protocol() — läuft vollständig lokal
    über Ollama, kein Netzwerkzugriff nach aussen. Wirft OllamaNichtErreichbar
    mit einer UI-tauglichen deutschen Fehlermeldung, wenn Ollama nicht läuft
    oder das Modell fehlt."""

    _pruefe_ollama()
    prompt = _build_prompt(transcript, meeting_title, meeting_date, participants,
                            custom_notes, previous_pendenzen, previous_date)

    resp = requests.post(
        f"{OLLAMA_URL}/api/chat",
        json={
            "model": OLLAMA_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"num_ctx": OLLAMA_NUM_CTX},
        },
        timeout=OLLAMA_TIMEOUT,
    )
    resp.raise_for_status()
    text = resp.json()["message"]["content"].strip()

    # Falls das Modell trotz Anweisung Code-Fences drumherum setzt
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3].rstrip()

    return text
