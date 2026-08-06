# KI-Werkbank — Technische Referenz

Lokale Flask-basierte "Werkbank" mit mehreren KI-Apps hinter einer
gemeinsamen Oberfläche. Jede App läuft als eigener Prozess mit eigenem
venv, nur über HTTP (localhost) angesprochen — wegen Dependency-Konflikten
und GPU-Konkurrenz zwischen den Apps.

Diese Datei ist die technische Referenz für Betrieb und Erweiterung. Sie
setzt keine Kenntnis vorheriger Chat-Verläufe voraus — alle Angaben sind
gegen den aktuellen Code geprüft (Stand 04.08.2026).

Windows 11 Pro, CUDA 12.2 (Treiber), GPU: RTX 4080 Laptop 12GB VRAM,
Ryzen 9 7945HX, 32GB RAM.

## Ordnerstruktur

```
werkbank/
  start_werkbank.bat        Doppelklick-Start (ruft start_werkbank.ps1 auf)
  start_werkbank.ps1        Startet Hub + Sidecar in zwei Fenstern, Health-Checks

  hub/                      Hub-Prozess: Weboberfläche + Transkription
    app.py                  Flask-Server, Routen /process, /anonymize, /status, /download*
    transcribe.py           Whisper-Transkription (GPU), GPU-Sperre mit Wartelogik
    job_status.py           In-Memory-Fortschrittsstatus für /status (Transkription)
    protocol.py              Claude-API-Aufruf, Protokollstruktur
    docx_export.py          Markdown → Word
    sitzungsreihe.py        Sitzungsreihen-Verwaltung, Pendenzen-Abgleich
    templates/index.html    Dashboard (Transkription + PDF-Anonymisierung, Status-Polling)
    uploads/, output/       Laufzeit-Daten (nicht versioniert)
    venv/                   eigenes venv, INNERHALB des Projektordners
    requirements.txt
    .env / .env.example
    start.bat               Windows-Startskript (venv + CUDA-Pfade + app.py)

  apps/anonymisierung/      Sidecar: PDF-Anonymisierung
    anonymize_service.py    Flask-Service, Routen /health, /status, /process
    batch_pipeline.py       Kernlogik (OCR + PII-Erkennung/Anonymisierung),
                             auch als CLI nutzbar: python batch_pipeline.py <ordner>
    pdfs/, output/          Laufzeit-Daten
    (kein eigenes venv hier — siehe Setup unten)

  shared/                   gemeinsamer Zustand zwischen Hub und Sidecar
    gpu.lock                 GPU-Sperrdatei, zur Laufzeit angelegt/gelöscht
                             (kein Teil des Repos, entsteht automatisch)
```

**Sidecar-venv liegt bewusst außerhalb**: `C:\Users\thoma\ocr-env` (nicht
`apps/anonymisierung/venv`). Grund: andere, teils inkompatible
Abhängigkeiten als der Hub (PaddlePaddle, Presidio, GLiNER) — soll nicht
mit dem Hub-venv kollidieren und nicht versehentlich mitverschoben/gelöscht
werden, wenn `werkbank/` als Ganzes bewegt wird.

## Setup pro App

### Hub (`hub/`)

- Python 3.12, venv unter `hub/venv/` (Teil des Projektordners)
- Abhängigkeiten in `hub/requirements.txt`:
  `flask>=3.0`, `requests>=2.31`, `python-dotenv>=1.0`, `anthropic>=0.40`,
  `python-docx>=1.1`, `faster-whisper>=1.0`, `nvidia-cublas-cu12`,
  `nvidia-cudnn-cu12` (letztere beide für GPU-Transkription — ohne sie
  fällt `faster-whisper` automatisch, aber unbemerkt langsamer auf CPU
  zurück)

```powershell
cd hub
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# .env öffnen, ANTHROPIC_API_KEY eintragen
```

### Sidecar: PDF-Anonymisierung (`apps/anonymisierung/`)

- venv unter `C:\Users\thoma\ocr-env` (siehe oben — nicht verschieben)
- Kein `requirements.txt` im Repo für dieses venv; tatsächlich installierte
  Kernpakete (`pip freeze`, Stand heute):

  | Paket | Version |
  |---|---|
  | Flask | 3.1.3 |
  | paddleocr | 3.7.0 |
  | paddlepaddle-gpu | 3.2.2 (CUDA-11.8-Wheels — Treiber unterstützt max. CUDA 12.2) |
  | paddlex | 3.7.2 |
  | presidio_analyzer | 2.2.364 |
  | presidio_anonymizer | 2.2.364 |
  | gliner | 0.2.28 |
  | PyYAML | 6.0.3 |
  | torch | 2.13.0 |
  | transformers | 5.13.1 |

  **Achtung PyYAML:** muss laut Projekt-Vorgabe exakt auf `6.0.2` gepinnt
  sein (paddlex-Anforderung, Presidio-Installationen ziehen es gerne
  hoch). Aktuell installiert ist `6.0.3` — nach jeder Presidio-
  Neuinstallation mit `pip show pyyaml` prüfen und bei Bedarf
  `pip install pyyaml==6.0.2` erzwingen.

- GLiNER-Modell `urchade/gliner_multi_pii-v1` wird beim ersten
  Modell-Laden automatisch von HuggingFace heruntergeladen (danach lokal
  gecacht).
- Ohne bestehendes `requirements.txt` empfiehlt sich beim Neuaufsetzen
  sinngemäß: `pip install flask paddleocr paddlepaddle-gpu presidio-analyzer
  presidio-anonymizer gliner "pyyaml==6.0.2"` — Versionen wie oben
  gegenprüfen.

## Beide Prozesse starten

**Empfohlen:** `start_werkbank.bat` im Projekt-Root doppelklicken (ruft
`start_werkbank.ps1` mit `-ExecutionPolicy Bypass` auf). Prüft vorab, ob
Port 5000/5001 schon belegt sind (überspringt dann mit klarer Meldung statt
doppelt zu starten), öffnet Hub und Sidecar in zwei getrennten, sichtbaren
Fenstern, prüft danach aktiv per Health-Check, ob beide erreichbar sind.
Kein Autostart bei Windows-Login/-Boot — rein manuell auszuführen.

Alternativ manuell, zwei separate Fenster:

**Fenster 1 — Hub** (Transkription + Weboberfläche, immer nötig):

```powershell
cd hub
start.bat
```

→ `http://127.0.0.1:5000` (Port fix, nicht konfigurierbar)

**Fenster 2 — Sidecar** (nur nötig für die PDF-Anonymisierung im Hub):

```powershell
cd apps\anonymisierung
C:\Users\thoma\ocr-env\Scripts\activate
python anonymize_service.py
```

→ `http://127.0.0.1:5001` (Port über `ANONYMIZE_SERVICE_PORT`
konfigurierbar)

Reihenfolge ist egal, beide sind unabhängig startbar. Der Hub funktioniert
auch ohne laufenden Sidecar — `/anonymize` liefert dann klar 503 statt
eines generischen Fehlers.

## Umgebungsvariablen

### Hub (`hub/.env`, geladen via `python-dotenv`)

| Variable | Default | Bedeutung |
|---|---|---|
| `ANTHROPIC_API_KEY` | – (Pflicht) | Claude-API-Key für die Protokoll-Erstellung |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | Claude-Modell für die Protokoll-Generierung |
| `WHISPER_MODEL_SIZE` | `medium` | Whisper-Modellgröße: `tiny`/`base`/`small`/`medium`/`large-v3` |
| `WHISPER_DEVICE` | `cuda` | `cuda` oder `cpu` |
| `WHISPER_COMPUTE_TYPE` | `float16` | Compute-Typ, z.B. `int8` für CPU-Betrieb |
| `ANONYMIZE_SERVICE_URL` | `http://127.0.0.1:5001` | Basis-URL des Sidecars, für `/anonymize` |
| `GPU_LOCK_PATH` | `<projekt-root>/shared/gpu.lock` | Pfad zur GPU-Sperrdatei — **muss mit dem Sidecar identisch sein** |
| `GPU_LOCK_WAIT_SECONDS` | `60` | Wie lange der Hub bei belegter GPU-Sperre wartet, bevor er 503 zurückgibt |

### Sidecar (`apps/anonymisierung/`, keine `.env`-Datei — reine Prozess-Umgebungsvariablen)

| Variable | Default | Bedeutung |
|---|---|---|
| `ANONYMIZE_SERVICE_PORT` | `5001` | Port des Sidecars |
| `GPU_LOCK_PATH` | `<projekt-root>/shared/gpu.lock` | s.o., muss mit dem Hub übereinstimmen |
| `IDLE_TIMEOUT_SECONDS` | `600` | Nach dieser Inaktivität (Sekunden) seit der letzten `/process`-Anfrage beendet sich der Sidecar selbst (VRAM-Freigabe) |

### Fest codiert (nicht über Umgebungsvariablen konfigurierbar)

| Konstante | Wert | Wo | Bedeutung |
|---|---|---|---|
| `GPU_LOCK_STALE_SECONDS` | `600` | beide Prozesse, identisch | Sperrdatei älter als das gilt als "hängengeblieben" (z.B. nach Absturz) und wird ignoriert/überschrieben |
| `GPU_LOCK_RETRY_INTERVAL_SECONDS` | `5` | nur Hub | Retry-Intervall beim Warten auf die GPU-Sperre |
| `MAX_CONTENT_LENGTH` | 2 GB | Hub | maximale Upload-Größe |
| Hub-Port | `5000` | Hub, `app.py` | fest in `app.run(...)`, nicht konfigurierbar |

## GPU-Koordination

Beide Prozesse teilen sich eine GPU mit 12GB VRAM. Ohne Koordination
laufen Whisper (Hub) und PaddleOCR+GLiNER (Sidecar) gleichzeitig, der
VRAM wird knapp bis erschöpft — Ergebnis ist keine saubere Fehlermeldung,
sondern eine drastische, stille Verlangsamung.

- **`shared/gpu.lock`**: einfache dateibasierte Sperre (kein Redis/Celery
  — für den Einzelnutzer-Fall bewusst simpel). Exklusives Anlegen
  (`open(path, "x")`) ist atomar — wer die Datei zuerst anlegt, hat die
  GPU. Freigabe im `finally`-Block (Datei löschen), auch bei Fehlern.
- **Stale-Lock-Erkennung**: ist die Sperrdatei älter als
  `GPU_LOCK_STALE_SECONDS` (600s), gilt sie als hängengeblieben (z.B.
  nach einem Absturz ohne sauberes Aufräumen) und wird ignoriert/gelöscht.
- **Sidecar**: schlägt bei belegter Sperre **sofort** mit 503 fehl — der
  Sidecar selbst wartet nicht.
- **Hub**: wartet bei belegter Sperre bis zu `GPU_LOCK_WAIT_SECONDS`
  (Default 60s) mit Retry alle 5s, bevor er aufgibt und 503 zurückgibt —
  der Nutzer wartet beim Hochladen ohnehin schon, ein kurzes Warten ist
  sinnvoller als ein Sofortfehler. Läuft `WHISPER_DEVICE=cpu` (oder ist
  bereits ein GPU→CPU-Fallback passiert), wird die Sperre komplett
  übersprungen — reine CPU-Nutzung braucht keine Koordination.
- **Idle-Timeout im Sidecar**: PaddleOCR/GLiNER bleiben nach dem Laden
  dauerhaft resident (mehrere GB VRAM). Ohne neue `/process`-Anfrage
  innerhalb von `IDLE_TIMEOUT_SECONDS` (Default 600s) beendet sich der
  Sidecar-Prozess selbst (`os._exit(0)`) und gibt den VRAM frei. Einfach
  `python anonymize_service.py` neu starten — kein Datenverlust, Modelle
  laden beim nächsten Request neu (~60s).

## Verlaufsanzeige / Dashboard-Status

Beide Karten im Dashboard (`hub/templates/index.html`) pollen alle 3s
`GET /status` auf dem Hub und zeigen Phase + (nur bei der Transkription)
groben Fortschritt an. Grund für `threaded=True` bei beiden `app.run()`-
Aufrufen: ohne Threading könnte der Hub `/status` nicht beantworten,
während ein `/process`- oder `/anonymize`-Request noch läuft (Flasks
Dev-Server bedient sonst nur eine Anfrage gleichzeitig) — die eigentliche
GPU-Arbeit bleibt trotzdem durch `gpu_lock()` serialisiert, unabhängig
vom Threading.

- **Transkription** (`hub/job_status.py`, In-Memory, ein Job gleichzeitig):
  Phasen `idle` → `wartet_auf_gpu` → `modell_laden` → `transkribiert`
  (mit `current`/`total` in Sekunden, aktualisiert nach jedem
  faster-whisper-Segment) → `protokoll_wird_erstellt` (Claude-Aufruf) →
  zurück zu `idle`.
- **Anonymisierung** (in `anonymize_service.py`, eigener `GET /status`
  auf dem Sidecar, vom Hub abgefragt): nur grobe Phasen `idle` →
  `modelle_laden` → `ocr_laeuft` → `anonymisierung_laeuft` → `idle` —
  bewusst kein Seiten-Fortschritt (zu aufwendig für den Nutzen). Ist der
  Sidecar nicht erreichbar, meldet der Hub `nicht_erreichbar` statt
  abzustürzen.
- **GPU-Badge** im Dashboard-Header: `gpu.lock`-Existenz, gleicher Check
  wie beim eigentlichen Lock-Mechanismus.

## Endpunkt-Referenz

### Hub (Port 5000)

**`GET /`** — Weboberfläche (HTML).

**`GET /reihen`** — `{"reihen": [...]}`, bekannte Sitzungsreihen.

**`GET /status`** — Dashboard-Polling (siehe oben). Antwort:
`{"transkription": {"phase", "current", "total"}, "anonymisierung": {"phase"}, "gpu": {"belegt"}}`.

**`POST /process`** — Transkription (+ optional Protokoll). `multipart/form-data`:

| Feld | Pflicht | Bedeutung |
|---|---|---|
| `audio` | ja | Audiodatei: `.mp3`/`.wav`/`.m4a`/`.mp4`/`.ogg`/`.flac`/`.webm` |
| `nur_transkript` | nein | `"true"`/`"on"`/`"1"` → nur Transkript, sonst voller Protokoll-Modus |
| `title`, `date`, `time`, `participants`, `notes`, `reihe` | nein | nur im Protokoll-Modus relevant |

Antworten: `200` Erfolg · `400` keine/falsche Datei · `422` Transkript
leer/zu kurz · `503` GPU durch Sidecar belegt · `500` sonstiger Fehler.

**`POST /anonymize`** — PDF-Anonymisierung. `multipart/form-data`, Feld
`pdf` (Pflicht, nur `.pdf`). Ruft intern `POST <ANONYMIZE_SERVICE_URL>/process`
auf.

Antworten: `200 {"success": true, "roh_path", "anonymisiert_path", "n_hits"}`
· `400` keine/falsche Datei · `503` Sidecar nicht erreichbar ODER GPU
belegt (Meldung vom Sidecar unverändert durchgereicht) · `500` sonstiger
Fehler.

**`GET /download-anonymized?path=<absoluter Pfad>`** — liefert eine
Ergebnisdatei (`roh_path`/`anonymisiert_path` aus `/anonymize`) aus. Der
Pfad muss innerhalb von `apps/anonymisierung/output/` liegen (geprüft via
`Path.resolve()` + `relative_to()`), sonst `403` — bewusst nicht auf den
ganzen App-Ordner erweitert, damit über diese Route weder Quellcode noch
hochgeladene PDFs abrufbar sind.

Antworten: `200` Datei · `400` Parameter `path` fehlt · `403` Pfad
außerhalb des erlaubten Ordners · `404` Datei nicht gefunden.

**`GET /download/<reihe>/<filename>`** — liefert Protokoll-Dateien aus dem
Sitzungsreihen-Ordner (oder `Rohfassungen/` für den Nur-Transkript-Modus).

### Sidecar (Port 5001)

**`GET /health`** — `{"status": "ok", "models_loaded": bool}`.

**`GET /status`** — `{"phase": "idle"|"modelle_laden"|"ocr_laeuft"|"anonymisierung_laeuft"}`,
vom Hub für das Dashboard abgefragt (siehe "Verlaufsanzeige / Dashboard-Status" oben).

**`POST /process`** — JSON-Body:

```json
{"pdf_path": "<absoluter Pfad, Pflicht>", "output_dir": "<absoluter Pfad, optional>"}
```

Ohne `output_dir` wird `<Ordner von pdf_path>/<Dateiname ohne Endung>/`
verwendet. Erfolgsantwort:

```json
{"success": true, "roh_path": "...", "anonymisiert_path": "...", "n_hits": 0, "elapsed_seconds": 0.0}
```

Antworten: `200` Erfolg · `400` `pdf_path` fehlt · `404` PDF nicht
gefunden · `503` GPU belegt · `500` sonstiger Fehler.

## Troubleshooting

**venv lässt sich nicht einfach verschieben/kopieren.** Windows-venvs
speichern absolute Pfade an mehreren Stellen — in `activate.bat` /
`Activate.ps1` (`VIRTUAL_ENV=...`) und vor allem als feste Shebang-Zeile
in jedem pip-generierten `.exe`-Wrapper (`pip.exe`, `flask.exe`, ...).
Nach einem Ordner-Umzug zeigen diese noch auf den alten Pfad und
scheitern mit Exit-Code 1, meist ohne aussagekräftige Fehlermeldung im
Terminal. Einzig zuverlässige Lösung: venv komplett löschen und am neuen
Ort neu aufsetzen (`python -m venv venv` + `pip install -r
requirements.txt`). Ist beim Umzug von `hub/venv/` nach `werkbank/`
konkret so aufgetreten.

**"GPU aktuell durch PDF-Anonymisierung belegt" / "GPU ist gerade durch
einen anderen Prozess belegt".** Kein Fehler im eigentlichen Sinn —
beide Prozesse teilen sich eine GPU mit 12GB VRAM, und der jeweils
andere Prozess (Sidecar bzw. Hub) verarbeitet gerade etwas. Beim Hub
erscheint diese Meldung erst nach `GPU_LOCK_WAIT_SECONDS` (Default 60s)
Warten. Einfach etwas warten und erneut versuchen — eine mehrseitige
PDF-Anonymisierung kann mehrere Minuten dauern. Kein Neustart nötig.

**Code-Änderungen wirken nicht.** Beide Prozesse laden ihren Code (und,
beim Hub, die Jinja-Templates) einmal beim Start; `debug=False`, kein
Auto-Reload. Nach jeder Änderung an einer `.py`-Datei oder an
`hub/templates/index.html` muss der jeweils betroffene Prozess neu
gestartet werden (Fenster schließen bzw. Strg+C, dann neu starten). Hub
und Sidecar sind unabhängig — nur der tatsächlich geänderte Prozess muss
neu gestartet werden.

**Sidecar ist "einfach weg".** Kein Absturz — der Idle-Timeout (Default
10 Minuten Inaktivität) hat den Prozess selbst beendet, um VRAM
freizugeben. Die Konsole zeigt vorher "Idle-Timeout erreicht, beende mich
selbst zur VRAM-Freigabe". Einfach `python anonymize_service.py` erneut
starten — keine Daten gehen verloren, Modelle laden beim nächsten
`/process` neu (~60s).

**PyYAML-Version im `ocr-env`.** Aktuell `6.0.3` installiert, Vorgabe ist
exakt `6.0.2` (paddlex-Anforderung). Bislang ohne beobachtete Probleme,
aber bei unerklärlichen paddlex-/PaddleOCR-Fehlern zuerst hier prüfen
(`pip show pyyaml` im `ocr-env`).
