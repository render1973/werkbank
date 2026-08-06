"""
Verwaltung von Sitzungsreihen: legt pro Reihe einen eigenen Output-Ordner an,
findet das letzte Protokoll einer Reihe, und extrahiert dessen offene Pendenzen
für den Abgleich im nächsten Protokoll.

Speicherung: rein lokal im Dateisystem, keine Datenbank.

    output/
      <Reihen-Name>/
        2026-06-10_Protokoll.docx
        2026-06-10_Protokoll.md
        2026-06-10_transkript.txt
        2026-07-08_Protokoll.docx
        ...
  reihen.json   <- Liste bekannter Reihen, fürs Dropdown im Formular
"""

import json
import re
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"
REIHEN_FILE = Path(__file__).parent / "reihen.json"


def _safe_reihe_name(name: str) -> str:
    """Macht aus einem Reihennamen einen sicheren Ordnernamen."""
    name = name.strip()
    safe = "".join(c for c in name if c.isalnum() or c in " -_").strip()
    safe = re.sub(r"\s+", "-", safe)
    return safe or "Unbenannt"


def list_reihen() -> list[str]:
    """Liste aller bekannten Sitzungsreihen fürs Dropdown."""
    if REIHEN_FILE.exists():
        try:
            return json.loads(REIHEN_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    # Fallback: aus vorhandenen Ordnern ableiten, falls reihen.json fehlt/kaputt ist
    if OUTPUT_DIR.exists():
        return sorted(d.name for d in OUTPUT_DIR.iterdir() if d.is_dir())
    return []


def register_reihe(name: str) -> str:
    """Trägt eine neue Reihe ein (falls noch nicht bekannt) und gibt den
    sicheren Ordnernamen zurück."""
    safe_name = _safe_reihe_name(name)
    reihen = list_reihen()
    if safe_name not in reihen:
        reihen.append(safe_name)
        reihen.sort()
        REIHEN_FILE.write_text(
            json.dumps(reihen, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    reihe_dir = OUTPUT_DIR / safe_name
    reihe_dir.mkdir(parents=True, exist_ok=True)
    return safe_name


def get_reihe_dir(reihe_name: str) -> Path:
    safe_name = _safe_reihe_name(reihe_name)
    return OUTPUT_DIR / safe_name


def find_latest_protocol(reihe_name: str) -> Path | None:
    """Findet die zuletzt erstellte .md-Protokolldatei einer Reihe.
    None, wenn es die erste Sitzung dieser Reihe ist."""
    reihe_dir = get_reihe_dir(reihe_name)
    if not reihe_dir.exists():
        return None

    md_files = list(reihe_dir.glob("*.md"))
    # Transkript-Dateien ausschliessen, nur echte Protokolle
    md_files = [f for f in md_files if not f.stem.endswith("_transkript")]
    if not md_files:
        return None

    # Neuestes nach Änderungsdatum der Datei (robuster als Namens-Parsing)
    return max(md_files, key=lambda f: f.stat().st_mtime)


def extract_pendenzen_from_protocol(protocol_path: Path) -> list[dict]:
    """Extrahiert die Zeilen der 'To-dos / Pendenzen'-Tabelle aus einem
    Markdown-Protokoll. Gibt eine Liste von Dicts zurück:
    [{'aufgabe': ..., 'verantwortlich': ..., 'termin': ...}, ...]

    Robuster Zeilen-Parser für Markdown-Tabellen — kein vollständiger
    Markdown-Parser, reicht aber für das von uns selbst erzeugte Format.
    """
    if not protocol_path or not protocol_path.exists():
        return []

    text = protocol_path.read_text(encoding="utf-8")

    # Abschnitt "To-dos / Pendenzen" finden
    match = re.search(
        r"###\s*To-dos\s*/\s*Pendenzen(.*?)(?=\n###|\n##|\Z)",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return []

    section = match.group(1)
    rows = []
    for line in section.strip().split("\n"):
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        # Header- und Trennzeile überspringen
        if not cells or cells[0].lower() in ("#", "---", "") or set(cells[0]) <= {"-"}:
            continue
        if len(cells) >= 4:
            rows.append({
                "aufgabe": cells[1],
                "verantwortlich": cells[2],
                "termin": cells[3],
            })

    return rows


def extract_date_from_protocol(protocol_path: Path) -> str:
    """Liest das Sitzungsdatum aus einem Protokoll (für die Anzeige im Abgleich)."""
    if not protocol_path or not protocol_path.exists():
        return ""
    text = protocol_path.read_text(encoding="utf-8")
    match = re.search(r"\*\*Sitzungsdatum:\*\*\s*(.+)", text)
    return match.group(1).strip() if match else ""
