# Auftrag für Claude Code: Git-Versionierung für werkbank/ einrichten

Hintergrund: Heute Abend wurde `hub/transcribe.py` versehentlich mit einer
alten Version überschrieben, ohne Möglichkeit zur Wiederherstellung — musste
mühsam aus Code-Referenzen rekonstruiert werden. Git soll das künftig auf
einen einzigen `git checkout`-Befehl reduzieren.

## Schritte

1. Prüfen, ob Git installiert ist: `git --version`. Falls nicht vorhanden,
   Nutzer informieren, dass Git für Windows nötig ist (git-scm.com/download/win
   oder `winget install --id Git.Git -e`) — nicht selbst installieren, das ist
   eine Nutzer-Aktion.

2. Im Ordner `werkbank/` (nicht in `hub/` oder `apps/` einzeln):
   ```
   git init
   ```

3. `.gitignore` im Wurzelverzeichnis `werkbank/` anlegen mit folgendem
   Inhalt (Pfade ggf. an die tatsächliche Struktur anpassen, falls sie von
   der Annahme unten abweicht):

   ```
   # Virtuelle Umgebungen -- gross, reproduzierbar aus requirements.txt
   venv/
   */venv/
   */*/venv/

   # Python-Cache
   __pycache__/
   */__pycache__/
   */*/__pycache__/
   *.pyc

   # Geheimnisse -- NIEMALS committen (API-Keys, echte Pfade)
   .env
   !.env.example

   # Laufzeit-/Nutzerdaten -- Audiodateien, generierte Protokolle,
   # anonymisierte PDFs koennen echte, teils sensible Besprechungs- und
   # Kundendaten enthalten. Gehoeren NICHT in die Versionsgeschichte,
   # auch nicht lokal -- falls das Repo je geteilt oder gepusht wird,
   # waere das ein Datenleck.
   hub/uploads/
   hub/output/
   apps/*/uploads/
   apps/*/output/
   shared/gpu.lock

   # Betriebssystem
   .DS_Store
   Thumbs.db
   ```

   Vor dem Commit prüfen: gibt es weitere Ordner mit Nutzerdaten (z.B. in
   `apps/anonymisierung/`), die noch fehlen? Falls ja, ergänzen.

4. Ersten Commit erstellen:
   ```
   git add .
   git status   # VOR dem Commit anschauen -- sicherstellen, dass keine
                # .env, keine Uploads/Outputs, keine venv-Ordner auftauchen
   git commit -m "Initialer Stand der Werkbank"
   ```

5. Kurzer Bericht: wie viele Dateien wurden committet, und explizit
   bestätigen, dass `.env`, `uploads/`, `output/` NICHT dabei sind (per
   `git status` bzw. `git ls-files | grep -E "\.env$|uploads/|output/"`
   sollte leer sein).

## Für die Zukunft (nur kurz erwähnen, nicht jetzt umsetzen)

Ab jetzt lohnt sich ein `git commit` nach jeder grösseren Änderung,
besonders bevor eine Datei komplett ersetzt statt ergänzt wird — macht
genau den heutigen Vorfall trivial rückgängig machbar.
