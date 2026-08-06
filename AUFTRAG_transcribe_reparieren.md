# Auftrag für Claude Code: hub/transcribe.py reparieren (Hub aktuell down)

## Kritisch — Hub startet gerade nicht

```
ImportError: cannot import name 'GPU_LOCK_PATH' from 'transcribe'
```

Ursache: `hub/transcribe.py` wurde versehentlich mit einer alten, nicht-
integrierten Version überschrieben (aus einer früheren Projektphase vor dem
Werkbank-Merge), die kein `GPU_LOCK_PATH` mehr definiert. `app.py` importiert
das aber (`from transcribe import transcribe_audio, GPU_LOCK_PATH`).

## Schritt 1 — Original-Struktur rekonstruieren

`hub/app.py` und `shared/` (bzw. wo auch immer die GPU-Lock-Koordination mit
der Anonymisierungs-App liegt, siehe `shared/gpu.lock`-Mechanismus) danach
durchsuchen, wie `GPU_LOCK_PATH` bisher verwendet wurde — vermutlich ein
Pfad-Konstante auf die gemeinsame Lock-Datei, analog zum GPU-Lock-Mechanismus
der PDF-Anonymisierung. Git-Historie prüfen, falls vorhanden (`git log -p --
hub/transcribe.py` bzw. `git show HEAD~1:hub/transcribe.py` o.ä.), das wäre
der zuverlässigste Weg, die vorherige Version wiederherzustellen. Falls kein
Git: anhand der Verwendungsstellen in `app.py` rekonstruieren, welchen Pfad/
Typ `GPU_LOCK_PATH` haben muss.

## Schritt 2 — Danach: EINE gezielte Ergänzung, keine weitere Ersetzung

Sobald `hub/transcribe.py` wieder lädt: in der `model.transcribe(...)`-
Aufruf-Stelle (Parameter `language=None, vad_filter=True, beam_size=5`)
folgenden Parameter ergänzen:

```python
condition_on_previous_text=False,
```

Grund: bekannter Whisper-Halluzinations-Bug (Wiederholungsschleifen bei
Stille/Rauschen, verlangsamt und verfälscht Transkription besonders bei
langen Aufnahmen) — war schon länger als offener Punkt notiert.

## Test danach

- Hub startet ohne ImportError.
- GPU-Lock-Koordination mit der Anonymisierungs-App weiterhin funktionsfähig
  (kurzer Test: PDF-Anonymisierung während einer laufenden Transkription
  anstossen, sollte auf die GPU warten statt zu kollidieren — falls das
  vorher schon getestet war, reicht ein Blick auf den Code statt Nachstellen).
- Kurze Testaufnahme (2-3 Min) durchlaufen lassen, Transkription sollte
  spürbar schneller als Echtzeit laufen.
