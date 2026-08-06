# Besprechung → Protokoll Pipeline

Lokale Web-App: Audio hochladen → Whisper transkribiert (GPU) → Claude erstellt
strukturiertes Protokoll → Download als Word und Markdown.

Läuft komplett auf deinem eigenen Rechner. Nur der Protokoll-Schritt geht
über die Anthropic-API ins Netz — die Audiodatei und das rohe Transkript
verlassen deinen Rechner nie.

Dieser Ordner (`hub/`) ist der Hub-Prozess der **KI-Werkbank** (`werkbank/`) —
die gemeinsame Weboberfläche für mehrere lokale KI-Apps. Läuft auf Port 5000,
eigenes venv (`hub/venv/`). Eine zweite App, die PDF-Anonymisierung, läuft als
eigener Sidecar-Prozess in `apps/anonymisierung/` (Port 5001, eigenes venv
`ocr-env`) — siehe Abschnitt [PDF-Anonymisierung](#pdf-anonymisierung) unten.
Jede App läuft bewusst als eigener Prozess mit eigenem venv, wegen
Dependency-Konflikten und GPU-Konkurrenz zwischen den Apps.

## Setup

### 1. Virtuelle Umgebung

Wenn du bereits ein venv für dein Whisper-CUDA-Setup hast, kannst du das
weiterverwenden — dann reicht `pip install -r requirements.txt` darin.
Sonst neu anlegen:

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

pip install -r requirements.txt
```

### 2. API-Key eintragen

```bash
cp .env.example .env
```

Dann `.env` öffnen und deinen `ANTHROPIC_API_KEY` eintragen
(zu finden unter console.anthropic.com).

### 3. GPU prüfen

`faster-whisper` braucht CUDA + cuDNN, um die GPU zu nutzen. Falls du
bereits eine funktionierende Whisper-GPU-Installation hast (dein ROG-Laptop
mit RTX-Setup), sollte das hier mitlaufen, ohne dass du etwas Neues
installieren musst — `faster-whisper` nutzt dieselben CUDA-Libraries wie
das reguläre `openai-whisper`.

**Falls die GPU nicht gefunden wird:** Die App fällt automatisch auf CPU
zurück (langsamer, aber funktioniert). Kein Blocker, nur langsamer.

**Falls du lieber dein bestehendes Whisper-Setup 1:1 weiterverwenden willst**
(z.B. weil du eine andere Whisper-Variante als `faster-whisper` installiert
hast): Öffne `transcribe.py` und ersetze die `transcribe_audio()`-Funktion
durch einen Aufruf deines bestehenden Skripts. Die einzige Anforderung:
Rückgabe von `{"text": str, "language": str, "duration": float}`.

### 4. Starten

```bash
python app.py
```

(oder `start.bat` unter Windows — aktiviert das venv und setzt die
CUDA-Pfade automatisch)

Dann im Browser: **http://127.0.0.1:5000**

Für die Transkription reicht das allein. Für die PDF-Anonymisierung muss
zusätzlich der Sidecar-Prozess laufen — siehe
[PDF-Anonymisierung](#pdf-anonymisierung) unten.

## Erste Nutzung

Beim allerersten Lauf lädt `faster-whisper` das Modell herunter
(bei `medium` ca. 1.5 GB) — das dauert einmalig ein paar Minuten,
danach ist es lokal gecacht.

## Die Protokollstruktur anpassen

Die Gliederung des Protokolls steht in `protocol.py`, in der Variable
`PROTOCOL_STRUCTURE`. Diese Datei enthält aktuell eine sinnvolle
Standard-Struktur (Traktanden, Entscheidungen, Pendenzen, Offene Punkte,
Notizen) — **nicht** den exakten Wortlaut deines bestehenden
`besprechung-protokoll`-Skills, den ich nicht kenne.

**Empfehlung:** Öffne `protocol.py` und ersetze `PROTOCOL_STRUCTURE` durch
die Gliederung, die du aus deinem Chat-Skill gewohnt bist. Dann verhält
sich diese Pipeline identisch zu deinem gewohnten Workflow, nur automatisiert.

## Whisper-Modellgrößen

In `.env` über `WHISPER_MODEL_SIZE` einstellbar:

| Größe | Geschwindigkeit | Genauigkeit | Empfehlung |
|---|---|---|---|
| `small` | schnell | ok | schnelle Entwürfe |
| `medium` | mittel | gut | **Default, guter Kompromiss** |
| `large-v3` | langsam | am besten | wichtige Besprechungen, Dialekt/Fachbegriffe |

Bei Schweizerdeutsch-Anteilen oder vielen Fachbegriffen (SIA, IFC, etc.)
lohnt sich `large-v3` trotz der längeren Laufzeit.

## PDF-Anonymisierung

Zweite App der Werkbank, über den Hub erreichbar unter dem Formular
"PDF-Anonymisierung" auf http://127.0.0.1:5000. PDF hochladen → OCR
(PaddleOCR-VL) liest den Text aus → Presidio/GLiNER erkennt und schwärzt
personenbezogene Daten (Namen, Adressen, Orte, Organisationen,
Telefonnummern, E-Mail-Adressen) → Rohtext und anonymisierte Version stehen
als Markdown zum Download bereit.

Läuft komplett lokal, GPU-basiert (PaddleOCR-VL + GLiNER), kein Datenversand
ins Netz.

### Sidecar starten

Die eigentliche Verarbeitung läuft nicht im Hub-Prozess, sondern in einem
eigenen Sidecar-Prozess unter `apps/anonymisierung/` — eigenes venv
(`ocr-env`, liegt bewusst außerhalb des Projektordners), eigene
Abhängigkeiten (PaddlePaddle, Presidio, GLiNER), die mit dem Whisper-venv
des Hubs kollidieren würden.

**Aktuell müssen Hub und Sidecar manuell in zwei separaten Fenstern
gestartet werden** — es gibt noch kein gemeinsames Start-Skript:

```bash
# Fenster 1 — Hub (Transkription + Weboberfläche)
cd hub
start.bat            # oder: venv\Scripts\activate && python app.py

# Fenster 2 — Sidecar (PDF-Anonymisierung)
cd apps\anonymisierung
C:\Users\thoma\ocr-env\Scripts\activate
python anonymize_service.py
```

Der Sidecar läuft auf Port 5001. Ist er nicht gestartet, meldet das
PDF-Anonymisierungs-Formular im Hub das klar ("PDF-Anonymisierung läuft
nicht - bitte anonymize_service.py starten") statt eines generischen
Fehlers.

### GPU-Koordination

Hub (Whisper) und Sidecar (PaddleOCR + GLiNER) laufen als getrennte
Prozesse, teilen sich aber dieselbe GPU. Eine einfache dateibasierte Sperre
(`shared/gpu.lock`, über die Umgebungsvariable `GPU_LOCK_PATH` im Sidecar
konfiguriert) verhindert, dass beide gleichzeitig die GPU beanspruchen: ist
die GPU gerade belegt, antwortet der Sidecar mit HTTP 503, das der Hub
unverändert an die Weboberfläche durchreicht ("GPU ist gerade durch einen
anderen Prozess belegt..."). Einfach kurz warten und erneut versuchen.

## Dateien im Projekt

```
werkbank/
  hub/                    # dieser Ordner — Hub-Prozess, Port 5000
    app.py                # Flask-Server, verbindet alle Schritte, Routen /process + /anonymize
    transcribe.py          # Lokale Whisper-Transkription (GPU)
    protocol.py             # Claude-API-Aufruf + Protokollstruktur (HIER ANPASSEN)
    docx_export.py         # Markdown → Word-Konvertierung
    templates/index.html   # Weboberfläche (beide Formulare: Transkription + Anonymisierung)
    uploads/                # Temporär — Dateien werden nach Verarbeitung gelöscht
    output/                  # Fertige Protokolle (.docx, .md) und Transkripte
  apps/anonymisierung/    # Sidecar-Prozess PDF-Anonymisierung, Port 5001 (eigenes venv ocr-env)
  shared/                  # gpu.lock — Sperre zur GPU-Koordination zwischen Hub und Sidecar
```

## Bekannte Grenzen

- **Keine Sprechererkennung.** Das Transkript unterscheidet nicht, wer was
  gesagt hat. Wenn dir das wichtig ist, müsste ein Diarization-Schritt
  ergänzt werden (z.B. `pyannote.audio`) — das ist ein größerer Ausbauschritt,
  hier bewusst nicht enthalten.
- **Lange Aufnahmen brauchen Zeit.** Eine einstündige Besprechung dauert je
  nach Modellgröße und GPU einige Minuten zur Transkription.
- **Kein Multi-User-Betrieb.** Das ist für den Einzelgebrauch auf deinem
  Rechner gebaut, kein Server für mehrere Nutzer gleichzeitig.
