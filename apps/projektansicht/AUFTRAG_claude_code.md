# Auftrag für Claude Code: Projektansicht in die Werkbank integrieren

## Was mitgeliefert wird (fertig, getestet)

- `parser.py` — liest das Stundenrapport-xlsx (labelbasiert, robust gegen
  Zeilenverschiebungen), getestet gegen Stundenrapport_2026.xlsx (20 Projekte)
- `routes.py` — Flask-Blueprint, URL-Prefix `/projekte`, liest das xlsx bei
  jedem Seitenaufruf frisch (kein Hintergrunddienst, kein GPU-Bezug, kein gpu.lock)
- `templates/projektansicht.html` — Dashboard (Gantt-Timeline, Kategorie-Filter,
  KPIs inkl. «Stunden verfügbar», Vanilla-JS, keine Build-Tools)

## Schritte

1. Ordner `projektansicht/` nach `werkbank/apps/projektansicht/` kopieren
   (Struktur: `parser.py`, `routes.py`, `templates/projektansicht.html`).
   Leere `__init__.py` ergänzen, falls das Import-Schema des Hubs sie braucht.

2. Im Hub (Port 5000) den Blueprint registrieren:
   ```python
   from apps.projektansicht.routes import bp as projektansicht_bp
   app.register_blueprint(projektansicht_bp)
   ```
   An das bestehende Import-/Pfadschema des Hubs anpassen (sys.path prüfen).

3. `openpyxl` ins Hub-venv installieren, falls nicht vorhanden:
   `pip install openpyxl`

4. Pfad zum Stundenrapport konfigurieren: `STUNDENRAPPORT_PATH` in der
   `.env` des Hubs setzen (oder Konstante in `routes.py` anpassen).
   Den echten Pfad beim Nutzer erfragen.

5. **Tab-Navigation im Hub-Dashboard (`index.html`):** oben eine Tab-Leiste
   mit zwei Tabs einbauen — «Tools» (bestehende Ansicht: Transkription,
   Anonymisierung, GPU-Badge, Jobs) und «Projekte» (Link auf `/projekte`).
   Bestehende Statuslogik (GPU-Badge, Progress-Polling via GET /status)
   nicht anfassen. Einfachste robuste Variante: Tabs als Links, `/projekte`
   ist eine eigene Seite; dort denselben Tab-Kopf einfügen mit Rücklink auf `/`.
   Optik an das bestehende Hub-Design angleichen.

6. Test: Hub starten, `/projekte` aufrufen — Dashboard muss die Projekte aus
   dem xlsx zeigen. Danach xlsx-Datei kurz ändern (z. B. eine Stunde eintragen,
   speichern), Seite neu laden → Änderung muss sichtbar sein.
   Fehlerfall testen: falschen Pfad setzen → rote Fehlerbox statt Absturz.

## Nicht tun

- Keinen Watcher/Hintergrunddienst bauen — Parse-on-Request ist bewusst so
  entschieden (Datei ändert sich nur beim Rapportieren, Parsen < 1 s).
- Keine Änderungen an Transkriptions- oder Anonymisierungs-App.
- Das xlsx nie schreiben, nur lesen. Inhalte des Rapports nicht in Logs kippen.
