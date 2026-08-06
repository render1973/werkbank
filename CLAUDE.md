# KI-Werkbank — Projektkontext

Lokale Flask-basierte "Werkbank" mit mehreren KI-Apps hinter einer gemeinsamen
Oberfläche. Architekturprinzip: jede App läuft als eigener Prozess mit
eigenem venv, vom Hub-Prozess nur über HTTP (localhost) angesprochen — wegen
Dependency-Konflikten und GPU-Konkurrenz zwischen Apps.

Windows 11 Pro, CUDA 12.2 (Treiber), GPU: RTX 4080 Laptop 12GB VRAM,
Ryzen 9 7945HX, 32GB RAM.

## Architektur

- **Hub-Prozess** (`hub/`): Flask, Port 5000, eigenes venv (`hub/venv/`).
  Enthält die Weboberfläche + Transkription (faster-whisper, GPU, in-process,
  lazy geladen wie in `hub/transcribe.py`).
- **Sidecar: PDF-Anonymisierung** (`apps/anonymisierung/`): Flask, Port 5001,
  eigenes venv `C:\Users\thoma\ocr-env` (liegt bewusst AUSSERHALB des
  Projektordners — nicht verschieben). PaddleOCR-VL + Presidio/GLiNER, GPU,
  lazy geladen, bleibt resident.
- **GPU-Koordination**: einfache datei-basierte Sperre (`shared/gpu.lock`),
  kein Redis/Celery — für den Einzelnutzer-Fall bewusst simpel gehalten.
- **Kommunikation Hub <-> Sidecar**: HTTP + Dateipfade (kein Base64-Upload,
  beide Prozesse sehen dasselbe Dateisystem).

## Stand (04.08.2026)

- Sidecar (`apps/anonymisierung/anonymize_service.py`) gebaut, getestet,
  läuft: `/health` und `/process` funktionieren End-zu-Ende (399s für ein
  9-seitiges Dokument, 105 Treffer).
- `batch_pipeline.py` um LOCATION-Deny-List erweitert (analog zur
  bestehenden ORGANIZATION-Deny-List) — Ortsnamen in Titeln/Kopfzeilen ohne
  Satzkontext werden von GLiNER isoliert leicht übersehen, gleiche
  Fehlerklasse wie der ursprüngliche JLL-Fall. Recognizer wird nur erstellt/
  registriert, wenn `known_locations` tatsächlich Einträge hat (Presidio
  erlaubt keinen PatternRecognizer ohne patterns/deny_list) — Liste kann
  gefahrlos leer bleiben oder später ergänzt werden.
- `GPU_LOCK_PATH` in `anonymize_service.py` auf `shared/gpu.lock` (relativ
  zum Projekt-Root, `Path(__file__).resolve().parent.parent.parent`)
  umgestellt.
- Ordnerstruktur-Umzug geprüft: `start.bat`/venv-Aktivierung waren danach
  kaputt (venv enthielt noch absolute Pfade zum alten Ordner
  `besprechung-pipeline`, u.a. in `activate.bat` und allen pip-generierten
  `.exe`-Wrappern) — `hub/venv` komplett neu aufgesetzt, inkl. GPU-Wheels
  (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`) für faster-whisper.
- Hub-Integration abgeschlossen und End-zu-Ende getestet (real, offline,
  echte Mausklicks im Browser): Route `/anonymize` in `hub/app.py` (Upload →
  `POST http://127.0.0.1:5001/process` → Ergebnis inkl. `n_hits`), Route
  `/download-anonymized` (Pfad-Traversal-Schutz via `Path.resolve()` +
  `relative_to()`, bewusst auf `apps/anonymisierung/output/` verengt statt
  auf den ganzen App-Ordner — kein Zugriff auf Quellcode oder `pdfs/`),
  Upload-Formular in `hub/templates/index.html` mit Fehler-Durchreichung
  (Sidecar nicht erreichbar → 503 mit klarer Meldung, GPU belegt → 503 vom
  Sidecar durchgereicht, nicht generisch).
- Idle-Timeout im Sidecar (`IDLE_TIMEOUT_SECONDS`, Default 600, env-
  konfigurierbar): Prozess beendet sich nach Inaktivität selbst
  (`os._exit(0)` in eigenem Thread) und gibt den VRAM frei. Aktiv erst nach
  dem ersten erfolgreich geladenen Modell, Reset nach jeder abgeschlossenen
  `/process`-Anfrage. Echt getestet (reale OCR-Verarbeitung, für den Test
  `IDLE_TIMEOUT_SECONDS=30`): VRAM sank von 10286 MiB auf 928 MiB nach
  Ablauf des Timeouts, Konsolen-Meldung dabei explizit mit `flush=True`
  (sonst geht sie bei `os._exit()` und in eine Datei umgeleitetem stdout
  verloren — gefunden und behoben).
- `gpu.lock` jetzt beidseitig genutzt: Sidecar hatte die Sperre bereits
  (Sofort-Fehlschlag bei Konflikt), jetzt auch die Hub-Transkription
  (`hub/transcribe.py`) — dort mit Wartelogik (`GPU_LOCK_WAIT_SECONDS`,
  Default 60, Retry alle 5s) statt Sofort-Fehler, da der Nutzer beim
  Hochladen ohnehin schon wartet. Wichtig: löst bei belegtem Lock NICHT
  den bestehenden CPU-Fallback aus (der bleibt für echte GPU-Hardware-
  probleme reserviert), sondern gibt nach Ablauf der Wartezeit eine klare
  503-Meldung zurück ("GPU aktuell durch PDF-Anonymisierung belegt...").
  Auslöser war ein realer Konflikt heute (Sidecar + Hub gleichzeitig auf
  der GPU, VRAM praktisch erschöpft, Whisper lief dadurch ungewöhnlich
  langsam statt sauber zu warten oder klar zu melden) — mit künstlich
  gehaltenem Lock end-to-end reproduziert und die neue Wartelogik/503-
  Meldung bestätigt.
- Damit ist der ursprüngliche Fahrplan vollständig umgesetzt, keine offenen
  Punkte mehr.

## Wörtlich unverzichtbar (nicht aus dem Gedächtnis rekonstruieren)

- GLiNER-Modell: `urchade/gliner_multi_pii-v1`
- Entity-Mapping: person/name→PERSON, organization→ORGANIZATION,
  address→ADDRESS, location→LOCATION, phone number→PHONE_NUMBER,
  email→EMAIL_ADDRESS
- Platzhalter: `<PERSON>`, `<ADRESSE>`, `<ORT>`, `<ORGANISATION>`,
  `<TELEFON>`, `<EMAIL>`
- PyYAML muss exakt auf `6.0.2` gepinnt bleiben (paddlex-Anforderung) — nach
  jeder Presidio-Installation erneut prüfen/pinnen.
- PaddlePaddle: CUDA-11.8-Wheels (Treiber unterstützt max. CUDA 12.2).

## Sackgassen — nicht erneut versuchen

- spaCy-NER als alleinige PII-Erkennung: unzuverlässig, bleibt nur
  Tokenisierungs-Engine im Presidio-Setup.
- Eigene GLiNER-Wrapper-Klasse: unnötig, offizieller Presidio-
  GLiNERRecognizer existiert und wird verwendet.
- `AnalyzerEngine()` ohne Sprachkonfiguration: lädt ungewollt Englisch,
  wirft Fehler bei language="de". Immer explizit deutsche NlpEngine +
  `supported_languages=["de"]`.
- Internes Wiki (Vision-Punkt): bewusst verworfen, nicht nur zurückgestellt
  — mangels aktuellem Bedarf. Nicht von selbst wieder vorschlagen.

## Arbeitspräferenzen

- Vor eigenem Code/eigener Lösung immer zuerst prüfen, ob bereits eine
  etablierte Fertiglösung existiert.
- Bei Skript-Änderungen komplette Datei liefern, keine "ersetze Zeile X"-
  Anweisungen.
- Schritt-für-Schritt mit jeweils einem Befehl + Ausgabe-Rückmeldung.
- Deutsch, direkt, knapp. Unsicherheiten kennzeichnen statt Vermutungen als
  Fakten darstellen.
- Inhalte von Testdokumenten (Namen, Adressen, Mieter-/Finanzdetails) NIE im
  Chat wiederholen oder speichern — nur Metadaten (Pfade, Trefferzahlen).
