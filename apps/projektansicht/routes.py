"""
Projektansicht — Flask-Blueprint für die KI-Werkbank.

Liest bei jedem Aufruf das Stundenrapport-xlsx frisch vom konfigurierten Pfad
(kein Hintergrunddienst nötig: die Datei ändert sich nur beim Rapportieren,
und Parsen dauert < 1s). Läuft in-process im Hub, braucht keine GPU und
keinen gpu.lock.

Einbindung im Hub:
    from apps.projektansicht.routes import bp as projektansicht_bp
    app.register_blueprint(projektansicht_bp)

Konfiguration: Pfad zum xlsx via Umgebungsvariable STUNDENRAPPORT_PATH
oder direkt in der Konstante unten.
"""

import os
from pathlib import Path

from flask import Blueprint, jsonify, render_template

from .parser import parse_stundenrapport

# Pfad zum Stundenrapport — anpassen oder via .env setzen
STUNDENRAPPORT_PATH = os.getenv(
    "STUNDENRAPPORT_PATH",
    r"C:\Users\thoma\Documents\Stundenrapport_2026.xlsx",  # TODO: echten Pfad eintragen
)

bp = Blueprint(
    "projektansicht",
    __name__,
    url_prefix="/projekte",
    template_folder=str(Path(__file__).parent / "templates"),
)


@bp.route("/")
def dashboard():
    """Dashboard-Seite. Die Daten werden serverseitig eingebettet —
    ein Reload der Seite = frische Daten aus dem xlsx."""
    data = parse_stundenrapport(STUNDENRAPPORT_PATH)
    return render_template("projektansicht.html", data=data)


@bp.route("/daten")
def daten():
    """Rohdaten als JSON — für spätere Erweiterungen (Auto-Refresh,
    Export, Team-Varianten)."""
    return jsonify(parse_stundenrapport(STUNDENRAPPORT_PATH))
