"""
Stundenrapport-Parser für die Projektansicht der KI-Werkbank.

Liest das Auslastungs-Excel (Monats-Sheets, breite Projektmatrix) und liefert
eine flache Datenstruktur für das Dashboard. Es wird immer das NEUESTE Sheet
(letztes in der Mappe) gelesen — dort steht der vollständigste SAP-Block.

Labelbasiert statt fester Zeilennummern: die Zeilen werden über die
Beschriftungen in Spalte A gefunden ("Leistung", "Projekt", "Kalkuliert" ...),
damit Verschiebungen zwischen Sheets/Jahren nicht alles brechen.

Nutzung:
    from parser import parse_stundenrapport
    data = parse_stundenrapport(r"C:\\Pfad\\Stundenrapport_2026.xlsx")
"""

import re
from pathlib import Path

import openpyxl

# Spalte-A-Labels -> interne Schlüssel. Exakte Treffer (via ROW_LABELS_EXAKT)
# ODER — für Labels, die sich in der Praxis leicht anders schreiben lassen
# (umbenannt, gekürzt, "bis" ergänzt/weggelassen) — Präfix-Treffer via
# ROW_LABELS_PRAEFIX. Bei mehreren passenden Zeilen gewinnt die erste von
# oben — wichtig z.B. wenn eine neue "Laufzeit"-Zeile weiter oben ergänzt
# wurde, während eine alte "Laufzeit bis"-Zeile weiter unten stehen bleibt.
ROW_LABELS_EXAKT = {
    "leistung": "kategorie",
    "träger": "traeger",
    "projekt": "projekt",
    "kalkuliert": "kalk",
    "verbraucht": "verb",
    "verfügbar": "verfuegbar",
}
ROW_LABELS_PRAEFIX = {
    "laufzeit": "laufzeit",         # trifft "Laufzeit" UND "Laufzeit bis"
    "nummer": "nummer",             # altes Namensschema
    "kostenstelle": "nummer",       # neueres Namensschema, gleiche Bedeutung
}

MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]

# "TT.MM.JJ(JJ)-TT.MM.JJ(JJ)", toleriert einen optionalen Punkt direkt vor
# dem Bindestrich bzw. am Ende (kommt in der Praxis als Tippfehler vor).
ZEITRAUM_PATTERN = re.compile(
    r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})\.?\s*-\s*(\d{1,2})\.(\d{1,2})\.(\d{2,4})\.?"
)

# Namensfragmente, die auf reine Abwesenheits-Spalten ohne verwertbare
# Kalkuliert/Verbraucht-Struktur hindeuten (Substring-Check, nicht exakt --
# "Krank" und "Krankheit" sollen beide erkannt werden). "Ferien" bewusst
# NICHT hier drin: wird weiter unten gesondert behandelt, weil es je nach
# Rapport-Version entweder ein nackter Saldo ODER eine echte
# Kalkuliert/Verbraucht-Kategorie ist.
EXCLUDE_FRAGMENTE = {"krank", "summe"}

# Anzeige-Mapping der Leistungs-Kategorien
KATEGORIE_ANZEIGE = {"Projekte": "Forschung"}


def _norm(v) -> str:
    return str(v).strip() if v is not None else ""


def _find_rows(ws):
    """Findet die relevanten Zeilennummern über die Labels in Spalte A.
    Exakte Labels müssen 1:1 passen; Präfix-Labels reichen als Wortanfang.
    Bei mehreren Treffern für denselben Schlüssel gewinnt die oberste Zeile
    (Scan läuft top-down, 'target not in rows' verhindert Überschreiben).
    Gibt zusätzlich JEDEN Treffer pro Zielfeld zurück (nicht nur den ersten),
    damit fehlende oder mehrdeutige Felder als Warnung gemeldet werden
    können, statt still auf den falschen/leeren Wert zu laufen."""
    rows = {}
    treffer_je_ziel = {}
    for r in range(1, ws.max_row + 1):
        roh = _norm(ws.cell(row=r, column=1).value)
        label = roh.lower()
        for key, target in ROW_LABELS_EXAKT.items():
            if label == key:
                treffer_je_ziel.setdefault(target, []).append((roh, r))
                if target not in rows:
                    rows[target] = r
        for prefix, target in ROW_LABELS_PRAEFIX.items():
            if label.startswith(prefix):
                treffer_je_ziel.setdefault(target, []).append((roh, r))
                if target not in rows:
                    rows[target] = r
    return rows, treffer_je_ziel


ERWARTETE_FELDER = {"kategorie", "traeger", "projekt", "nummer", "laufzeit",
                     "kalk", "verb", "verfuegbar"}


def _diagnose_warnungen(treffer_je_ziel: dict) -> list:
    """Baut verständliche Warnzeilen aus den Zeilen-Treffern: ein Feld ganz
    ohne Treffer wurde vermutlich umbenannt; mehrere Treffer für dasselbe
    Feld bedeuten, dass eine alte und eine neue Zeile gleichzeitig existieren
    (wie 'Laufzeit' + 'Laufzeit bis') — die oberste gewinnt automatisch,
    aber das soll sichtbar sein statt sich still einzuschleichen."""
    warnungen = []
    for feld in sorted(ERWARTETE_FELDER):
        treffer = treffer_je_ziel.get(feld, [])
        if not treffer:
            warnungen.append(
                f"Feld „{feld}“ in keiner Zeile gefunden — "
                f"Zeilenbeschriftung in Excel evtl. geändert oder gelöscht."
            )
        elif len(treffer) > 1:
            namen = "; ".join(f"„{label}“ (Zeile {zeile})" for label, zeile in treffer)
            warnungen.append(
                f"Feld „{feld}“ mehrdeutig: {len(treffer)} passende Zeilen "
                f"gefunden — {namen}. Verwendet wird die oberste (Zeile "
                f"{treffer[0][1]})."
            )
    return warnungen


def _monthly_rows(ws):
    """Monatszeilen des LAUFENDEN Jahres: die ganze Spalte A wird nach
    Monatsnamen durchsucht (kein Anker-Label wie 'SAP' mehr nötig — das
    gab es in älteren Sheet-Versionen, aktuelle Sheets haben oft nur noch
    einen sauberen 12-Zeilen-Block ohne Überschrift davor). Falls mehrere
    Jahre hintereinander aufgelistet sind (älteres Format), markiert der
    letzte 'Januar'-Auftakt den Beginn des aktuellen Jahres."""
    labeled = []
    for r in range(1, ws.max_row + 1):
        label = _norm(ws.cell(row=r, column=1).value)
        if label in MONATE:
            labeled.append((label, r))
    if not labeled:
        return []
    last_jan = max((i for i, (l, _) in enumerate(labeled) if l == "Januar"),
                   default=0)
    return labeled[last_jan:]


def _jahr4(y: int) -> int:
    return 2000 + y if y < 100 else y


def _parse_laufzeit(v, default_jahr: int):
    """Erkennt drei Formate in der Spalte 'Laufzeit bis':
    - Zeitraum 'TT.MM.JJ-TT.MM.JJJJ' (Start UND Ende explizit)
      -> {typ: zeitraum, start_monat, start_jahr, end_monat, end_jahr}
    - Einzelmonat 'August 26' (Altformat, nur Ende, Start wird weiter aus
      den ersten rapportierten Stunden abgeleitet)
      -> {typ: monat, monat, jahr}
    - 'fortlaufend' -> {typ: fortlaufend}
    - alles andere -> {typ: unbekannt, roh: <Originaltext>} — der Originaltext
      wird mitgegeben, damit sichtbar bleibt, was genau nicht erkannt wurde,
      statt es stillschweigend zu verwerfen.
    """
    s = _norm(v)
    if not s:
        return {"typ": "unbekannt", "roh": s}
    if s.lower().startswith("fortlaufend"):
        return {"typ": "fortlaufend"}

    m = ZEITRAUM_PATTERN.fullmatch(s)
    if m:
        sd, sm, sy, ed, em, ey = m.groups()
        return {
            "typ": "zeitraum",
            "start_monat": int(sm), "start_jahr": _jahr4(int(sy)),
            "end_monat": int(em), "end_jahr": _jahr4(int(ey)),
        }

    parts = s.replace("/", " ").split()
    for p in parts:
        if p.capitalize() in MONATE:
            monat = MONATE.index(p.capitalize()) + 1
            jahr = default_jahr
            for q in parts:
                if q.isdigit():
                    jahr = _jahr4(int(q))
            return {"typ": "monat", "monat": monat, "jahr": jahr}

    return {"typ": "unbekannt", "roh": s}


def _num(v):
    try:
        return round(float(v), 1)
    except (TypeError, ValueError):
        return None


def _find_latest_monats_sheet(wb):
    """Sucht unter ALLEN Sheet-Namen der Mappe diejenigen, die einem
    Monatsnamen + Jahr entsprechen ("August 2026"), und gibt das späteste
    zurück - unabhängig von der Position in der Mappe. Damit bricht es
    nicht mehr, wenn ein Nicht-Monats-Sheet (z.B. eine Stundenlohn/Geko-
    Hilfstabelle namens "Tabelle1") ans Ende der Mappe verschoben oder neu
    angehängt wird - das war frueher implizit die Annahme hinter
    'letztes Sheet = neuestes Monatsblatt', die diese Aenderung bricht.
    Fallback auf das alte Verhalten (letztes Sheet), falls gar kein
    Sheet-Name als Monat+Jahr erkannt wird - z.B. bei komplett anderem
    Namensschema."""
    kandidaten = []
    for name in wb.sheetnames:
        jahr = None
        monat = None
        for token in name.split():
            if token.isdigit() and len(token) == 4:
                jahr = int(token)
            elif token.capitalize() in MONATE:
                monat = MONATE.index(token.capitalize()) + 1
        if jahr is not None and monat is not None:
            kandidaten.append((jahr, monat, name))
    if kandidaten:
        kandidaten.sort()
        return wb[kandidaten[-1][2]]
    return wb[wb.sheetnames[-1]]  # Fallback: altes Verhalten


def parse_stundenrapport(xlsx_path: str) -> dict:
    path = Path(xlsx_path)
    if not path.exists():
        return {"fehler": f"Datei nicht gefunden: {path}"}

    try:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
    except PermissionError:
        return {"fehler": f"Datei ist gerade gesperrt (vermutlich in Excel "
                          f"geöffnet): {path.name}. Datei schliessen und "
                          f"Seite neu laden."}
    except Exception as exc:
        return {"fehler": f"Datei '{path.name}' konnte nicht gelesen werden: {exc}"}
    ws = _find_latest_monats_sheet(wb)  # spätestes erkanntes Monats-Sheet

    # Jahr UND Monat aus dem Sheetnamen ("August 2026") lesen. Der Monat wird
    # separat gebraucht, um die "Heute"-Linie im Dashboard zu platzieren --
    # das geht NICHT mehr aus der Länge von monat_rows hervor, seit das
    # Excel-Sheet immer alle 12 Monate auflistet (frueher endete die Zeile
    # exakt beim aktuellen Monat, jetzt nicht mehr).
    jahr = None
    stand_monat = None
    titel_tokens = ws.title.split() + path.stem.split("_")
    for token in titel_tokens:
        if token.isdigit() and len(token) == 4:
            jahr = int(token)
        elif token.capitalize() in MONATE and stand_monat is None:
            stand_monat = MONATE.index(token.capitalize()) + 1
    jahr = jahr or 2026

    rows, treffer_je_ziel = _find_rows(ws)
    if "projekt" not in rows:
        return {"fehler": f"Sheet '{ws.title}': Zeile „Projekt“ nicht "
                          f"gefunden — Zeilenbeschriftung in Excel evtl. "
                          f"geändert."}

    warnungen = _diagnose_warnungen(treffer_je_ziel)

    monat_rows = _monthly_rows(ws)
    if not monat_rows:
        return {"fehler": f"Sheet '{ws.title}': keine Monats-Zeilen "
                          f"(Januar…Dezember) in Spalte A gefunden."}
    monate = [l for l, _ in monat_rows]

    # Kategorien (Zeile "Leistung") sind nur am Blockanfang gesetzt -> forward fill
    projekte = []
    kategorie = None
    ferien_verfuegbar = 0.0
    for c in range(2, ws.max_column + 1):
        kat_raw = _norm(ws.cell(row=rows["kategorie"], column=c).value) \
            if "kategorie" in rows else ""
        if kat_raw:
            kategorie = kat_raw

        name = _norm(ws.cell(row=rows["projekt"], column=c).value)
        name_lc = name.lower()

        if not name:
            continue

        def cell(key):
            return ws.cell(row=rows[key], column=c).value if key in rows else None

        # "Ferien"-artige Spalte: je nach Rapport-Version entweder ein
        # nackter Saldo (kein Kalkuliert-Wert -> fliesst nur in die KPI ein,
        # keine eigene Zeile, da keine sinnvolle Balken-Darstellung möglich)
        # ODER inzwischen eine echte Kalkuliert/Verbraucht-Kategorie (dann
        # wie ein normales Projekt behandeln, z.B. "Ferien/ Mehrstunden/
        # Minderstunden" mit echtem Budget statt nur einem Saldo).
        if "ferien" in name_lc:
            kalk_wert = _num(cell("kalk"))
            if kalk_wert is None:
                fv = _num(cell("verfuegbar")) if "verfuegbar" in rows else None
                if fv is not None:
                    ferien_verfuegbar = fv
                continue
            # sonst: durchfallen lassen, unten als normales Projekt geführt

        if any(frag in name_lc for frag in EXCLUDE_FRAGMENTE):
            continue

        stunden = [_num(ws.cell(row=r, column=c).value) or 0
                   for _, r in monat_rows]

        projekte.append({
            "projekt": name.replace("\n", " "),
            "kategorie": KATEGORIE_ANZEIGE.get(kategorie, kategorie or "Übrig"),
            "traeger": _norm(cell("traeger")),
            "nummer": _norm(cell("nummer")),
            "laufzeit": _parse_laufzeit(cell("laufzeit"), jahr),
            "kalk": _num(cell("kalk")),
            "verb": _num(cell("verb")),
            "stunden": stunden,
        })

    wb.close()
    return {
        "stand": ws.title,
        "jahr": jahr,
        "stand_monat": stand_monat or len(monate),  # Fallback: altes Verhalten
        "monate": monate,
        "projekte": projekte,
        "ferien_verfuegbar": ferien_verfuegbar,
        "warnungen": warnungen,
        "quelle": path.name,
    }


if __name__ == "__main__":
    import json
    import sys
    result = parse_stundenrapport(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=1))
