# Auftrag für Claude Code: Dreier-Schalter "Verarbeitung" einbauen

## WICHTIG — Ausgangslage korrigiert

Es gibt keinen eigenständigen `besprechung-pipeline/`-Ordner mehr. Die
Besprechungs-Pipeline läuft in `werkbank/hub/` (`hub/app.py`), zusammen mit
Job-Status-Tracking, GPU-Lock-Koordination mit der Anonymisierungs-App und
der Tab-Navigation inkl. Projektansicht. Das mitgelieferte `app.py` (siehe
unten) ist die ALTE, eigenständige Version aus einer früheren Session —
**sie darf `hub/app.py` NICHT überschreiben**, sonst gehen GPU-Badge,
Job-Status-Polling, Projektansicht-Tab und die Anonymisierungs-Routen
verloren. Sie dient nur als Referenz für die Verzweigungslogik, die manuell
in das echte, aktuelle `hub/app.py` eingebaut werden soll.

## Was mitgeliefert wird

- `app.py` (Referenz, NICHT kopieren/überschreiben!) — zeigt den gewünschten
  Ablauf: Whisper läuft immer lokal, danach Verzweigung in drei Modi über
  das Formularfeld `verarbeitung`:
  - `"transkript"` — nur .txt, KEIN Cloud-Zugriff, `generate_protocol()`
    und `generate_protocol_local()` werden nicht aufgerufen (per Test
    verifiziert)
  - `"protokoll_cloud"` — bisheriges Verhalten (Claude API), + Provenienz-
    Vermerk am Ende des Protokolls
  - `"protokoll_lokal"` — neu, via Ollama, ebenfalls + Provenienz-Vermerk
  Alle 5 Testfälle (3 Modi + Ollama-down-Fehlerfall + ungültiger Modus)
  liefen grün gegen Stub-Abhängigkeiten (Whisper/Cloud/Docx wegisoliert),
  nicht gegen die echte Hub-Umgebung mit GPU-Lock/Job-Status — das bitte
  nach dem Einbau nochmal end-to-end verifizieren.

- `protocol_local.py` — neues, eigenständiges Modul, lokale Protokoll-
  Erstellung via Ollama. Kann direkt und gefahrlos nach `hub/` kopiert
  werden (keine Überschneidung mit Bestehendem). Importiert **nur**
  `PROTOCOL_STRUCTURE` aus `protocol.py` (sonst keine Berührung von
  protocol.py). Modell-Default: `ministral-3:14b` (14B, Apache-2.0,
  explizit Deutsch, ~9.1GB — passt in 12GB VRAM). Über `OLLAMA_MODEL` in
  `.env` umstellbar, z.B. auf `qwen3:14b` zum Vergleich.

## Schritte

1. `protocol_local.py` nach `werkbank/hub/` kopieren.

2. In `hub/app.py`: die Verzweigungslogik aus dem mitgelieferten
   Referenz-`app.py` (Abschnitt `/process`) von Hand in die bestehende
   `/process`-Route (bzw. wie auch immer die Besprechungs-Verarbeitung dort
   heisst) einbauen — als Ergänzung, nicht als Ersatz der Datei. Bestehende
   Logik (GPU-Lock, Job-Status-Reporting, Pfade, Fehlerbehandlung der
   anderen Apps) unverändert lassen. Insbesondere:
   - Formularfeld `verarbeitung` mit den drei Werten einlesen
   - Bei `"transkript"`: nach der Transkription abbrechen, nur .txt
     schreiben, weder `generate_protocol()` noch `generate_protocol_local()`
     aufrufen
   - Bei `"protokoll_lokal"`: `generate_protocol_local()` aus
     `protocol_local.py` aufrufen, `OllamaNichtErreichbar` gezielt als
     HTTP 503 mit der Fehlermeldung durchreichen
   - Provenienz-Zeile am Ende von Protokoll-Markdown ergänzen (siehe
     Referenzdatei, Konstante `ENGINE_LABEL`)

3. **Prüfen, ob `protocol.py` wirklich `PROTOCOL_STRUCTURE` als Modul-Level-
   Konstante exportiert** (README der alten Pipeline sagt ja, aber bitte an
   der echten Datei in `hub/` verifizieren — falls der Name abweicht, den
   Import in `protocol_local.py` anpassen, sonst schlägt der Start fehl).

4. `requests` zu `requirements.txt` des Hub-venv hinzufügen und installieren
   (wird von `protocol_local.py` gebraucht, war bisher keine explizite
   Abhängigkeit):
   ```
   pip install requests
   ```

5. **Ollama lokal einrichten** (einmalig, Nutzer-Aktion):
   ```
   ollama pull ministral-3:14b
   ```
   Hinweis: dieses Modell verlangte bei Erscheinen Ollama >= 0.13.1 —
   falls der Pull fehlschlägt, zuerst `ollama --version` prüfen und ggf.
   Ollama aktualisieren.

6. **Frontend (`templates/index.html` bzw. deren Äquivalent im Hub):** vor dem Upload-Formular einen
   Dreier-Schalter einbauen (Radio-Buttons oder Segmented Control), der
   `verarbeitung` als Formularfeld mit einem der drei Werte sendet:
   - `transkript` — Label z.B. "Nur Transkript (lokal, kein Cloud-Zugriff)"
   - `protokoll_cloud` — Label z.B. "Protokoll erstellen (Cloud, Claude API)"
   - `protokoll_lokal` — Label z.B. "Protokoll erstellen (lokal, Ollama)"

   Default: `protokoll_cloud`, um bestehendes Verhalten nicht überraschend
   zu ändern — das ist eine bewusste Annahme von mir, gerne mit dem Nutzer
   absprechen, ob "nur Transkript" nicht der sinnvollere Default wäre
   (Datenlokalität als Grundhaltung).

   Die Antwort von `/process` liefert jetzt `text_typ` (`"protokoll"` oder
   `"transkript"`) und `text_preview` statt des bisherigen
   `protocol_preview` — das JS, das die Vorschau rendert, entsprechend
   anpassen. Bei `text_typ == "transkript"` gibt es kein `downloads.docx`
   und kein `downloads.md`, nur `downloads.transcript` — UI muss damit
   umgehen können (z.B. Download-Buttons für docx/md ausblenden).

   Bei HTTP 503 (Ollama nicht erreichbar/Modell fehlt) die `error`-Message
   direkt anzeigen — sie ist bereits nutzerverständlich formuliert
   ("Läuft der Dienst? ...", "Zuerst ausführen: ollama pull ...").

7. **Test:**
   - Alle drei Modi einmal durchklicken, prüfen dass die Downloads wie
     spezifiziert erscheinen (nur .txt bei "transkript"; .txt+.md+.docx
     bei den beiden Protokoll-Modi).
   - Provenienz-Zeile am Ende von .md/.docx prüfen ("Protokoll erstellt:
     lokal (ministral-3:14b), ...").
   - Ollama absichtlich stoppen, "Protokoll lokal" wählen → muss die
     503-Fehlermeldung sauber zeigen, kein Absturz.
   - Qualität des lokalen Protokolls an 2-3 echten Transkripten mit der
     Cloud-Variante vergleichen, besonders den Pendenzen-Abgleich (das ist
     laut Analyse der wahrscheinlichste Schwachpunkt lokaler 14B-Modelle).

## Nicht tun

- `protocol.py` nicht umschreiben — `protocol_local.py` ist bewusst so
  gebaut, dass es nur die Konstante importiert, nicht die Cloud-Logik
  anfasst.
- Keine automatische Modus-Erkennung einbauen (z.B. "wenn Ollama läuft,
  automatisch lokal nehmen") — die Wahl soll bewusst beim Nutzer bleiben,
  das ist der ganze Punkt des Schalters.
