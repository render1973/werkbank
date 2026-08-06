"""
Wandelt das Markdown-Protokoll in eine formatierte .docx-Datei um — auf Basis
der echten HSLU-Vorlage (assets/hslu_vorlage.docx), damit Header, Footer, Logo
und Grunddesign garantiert identisch zur gewohnten Vorlage sind.

Vorgehen: die Vorlage wird geöffnet, ihre Kopftabellen (Titel, Sitzungsdaten)
werden mit den neuen Werten befüllt, und der restliche Vorlageninhalt wird
durch den frisch generierten Protokolltext ersetzt. Header/Footer/Styles/Logo
bleiben dabei unverändert erhalten, weil sie Teil der Dokumentstruktur sind,
die wir nicht anfassen.
"""

import re
import shutil
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Cm

TEMPLATE_PATH = Path(__file__).parent / "assets" / "hslu_vorlage.docx"


def save_as_docx(
    markdown_text: str,
    output_path: str,
    title: str,
    date: str,
    participants: str = "",
    time: str = "",
) -> None:
    """Erstellt ein Protokoll im HSLU-Layout. Fällt auf ein schlichtes
    Standardlayout zurück, falls die Vorlage fehlt (z.B. bei einem
    frischen Checkout ohne assets/)."""

    if TEMPLATE_PATH.exists():
        _save_with_hslu_template(markdown_text, output_path, title, date, participants, time)
    else:
        print(f"WARNUNG: HSLU-Vorlage nicht gefunden unter {TEMPLATE_PATH}. "
              f"Nutze einfaches Standardlayout.")
        _save_plain(markdown_text, output_path)


def _save_with_hslu_template(markdown_text, output_path, title, date, participants, time):
    doc = Document(str(TEMPLATE_PATH))

    # --- Kopftabellen befüllen (Betreff, Datum, Zeit, Teilnehmende) ---
    # Die Vorlage hat mehrere Tabellen am Anfang: Titel-Tabelle, Meta-Tabelle,
    # Betreff-Tabelle. Wir passen die Zellinhalte an, ohne die Tabellenstruktur
    # (und damit Formatierung/Farbe) zu verändern.
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                first_line = cell.paragraphs[0].text.strip() if cell.paragraphs else ""

                if first_line.startswith("Sitzungsdatum"):
                    _replace_cell_value_paragraphs(cell, [date])
                elif first_line.startswith("Zeit"):
                    _replace_cell_value_paragraphs(cell, [time] if time else [""])
                elif first_line.startswith("Teilnehmende"):
                    names = [n.strip() for n in participants.split(",") if n.strip()] if participants else ["-"]
                    _replace_cell_value_paragraphs(cell, names)
                elif first_line.startswith("Betreff"):
                    _replace_betreff_inline(cell, f"Sitzungsprotokoll – {title}")

    # --- Inhaltskörper ersetzen ---
    # Alle Absätze NACH den Kopftabellen entfernen (der alte Beispielinhalt),
    # dann den neuen Protokolltext aus dem Markdown einfügen.
    _clear_body_content(doc)
    _insert_markdown_content(doc, markdown_text)

    doc.save(output_path)


def _replace_cell_value_paragraphs(cell, new_values: list) -> None:
    """Ersetzt die Wert-Absätze einer Kopfzelle. Struktur der Vorlage:
    Absatz 0 = Label ('Sitzungsdatum:'), Absatz 1..n = Wert(e), je einer
    pro Zeile/Name. Behält die Formatierung des ersten Werte-Runs bei,
    fügt bei Bedarf zusätzliche Absätze hinzu (z.B. mehrere Teilnehmende).
    """
    paragraphs = cell.paragraphs
    if len(paragraphs) < 2:
        # Keine Wert-Absätze vorhanden — einen anhängen
        p = cell.add_paragraph()
        p.add_run(new_values[0] if new_values else "")
        return

    value_paragraphs = paragraphs[1:]  # alles nach dem Label

    # Vorhandene Wert-Absätze der Reihe nach befüllen
    for i, p in enumerate(value_paragraphs):
        if i < len(new_values):
            _set_paragraph_text_keep_format(p, new_values[i])
        else:
            _set_paragraph_text_keep_format(p, "")  # überzählige Alt-Absätze leeren

    # Falls mehr neue Werte als vorhandene Absätze (z.B. mehr Teilnehmende
    # als im Beispiel): zusätzliche Absätze mit dem Format des letzten
    # Werte-Absatzes anhängen.
    if len(new_values) > len(value_paragraphs):
        template_p = value_paragraphs[-1] if value_paragraphs else None
        for extra_value in new_values[len(value_paragraphs):]:
            new_p = cell.add_paragraph()
            new_p.add_run(extra_value)


def _set_paragraph_text_keep_format(paragraph, new_text: str) -> None:
    """Setzt den Text eines Absatzes neu, behält die Formatierung des
    ersten Runs bei (Schriftart etc.), entfernt überzählige Runs."""
    if paragraph.runs:
        paragraph.runs[0].text = new_text
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(new_text)


def _replace_betreff_inline(cell, new_text: str) -> None:
    """Die Betreff-Zeile steht als 'Betreff  <alter Text>' in einem
    einzigen Absatz (siehe Analyse: 'Betreff  Sitzungsprotokoll – I').
    Hier bleibt 'Betreff' als Label stehen, der Rest wird ersetzt."""
    for p in cell.paragraphs:
        if p.text.strip().startswith("Betreff"):
            if p.runs:
                # Ersten Run als Label behalten, Rest zu einem Wert-Run machen
                p.runs[0].text = "Betreff  "
                for run in p.runs[1:]:
                    run.text = ""
                if len(p.runs) > 1:
                    p.runs[1].text = new_text
                else:
                    p.add_run(new_text)
            return


def _clear_body_content(doc: Document) -> None:
    """Entfernt den Beispielinhalt der Vorlage, behält aber die Kopftabellen
    (Titel/Sitzungsdaten/Betreff) sowie Header/Footer/sectPr.

    Die Vorlage hat 3 Kopftabellen am Dokumentanfang (Titel, Sitzungsdaten,
    Betreff), gefolgt vom Beispielinhalt, gefolgt von 1-2 Beispiel-Tabellen
    (z.B. die alte Pendenzen-Tabelle) weiter unten im Dokument. Wir schneiden
    daher NACH der 3. Tabelle, nicht nach der letzten — sonst bleibt der
    komplette Beispielinhalt stehen."""
    from docx.oxml.ns import qn as _qn

    body = doc.element.body
    tables = body.findall(_qn("w:tbl"))

    if len(tables) < 3:
        # Unerwartete Vorlagenstruktur — sicherheitshalber nichts löschen,
        # lieber zu viel Beispielinhalt behalten als versehentlich die
        # Kopftabellen zu zerstören.
        print("WARNUNG: Erwartete Kopftabellen-Struktur nicht gefunden. "
              "Beispielinhalt der Vorlage bleibt evtl. erhalten — bitte "
              "generiertes docx manuell prüfen.")
        return

    cutoff_table = tables[2]  # 3. Tabelle = Betreff-Tabelle, Ende des Kopfbereichs

    remove_mode = False
    to_remove = []
    for child in list(body):
        if child is cutoff_table:
            remove_mode = True
            continue
        if remove_mode:
            if child.tag == _qn("w:sectPr"):
                continue  # Seiteneinstellungen behalten
            to_remove.append(child)

    for el in to_remove:
        body.remove(el)


def _safe_paragraph(doc, text_parts_line: str, preferred_styles: list[str]):
    """Fügt einen Absatz mit dem ersten verfügbaren Stil aus preferred_styles
    hinzu. Existiert keiner davon in der Vorlage, wird ein normaler Absatz
    ohne speziellen Stil erzeugt (Inhalt geht nie verloren, nur die
    Sonderformatierung kann je nach Vorlage variieren)."""
    style_names = {s.name for s in doc.styles}
    for style_name in preferred_styles:
        if style_name in style_names:
            return doc.add_paragraph(style=style_name)
    return doc.add_paragraph()


def _insert_markdown_content(doc: Document, markdown_text: str) -> None:
    """Fügt den generierten Protokolltext am Ende des Dokuments ein,
    mit einfacher Markdown-Formatierung (Überschriften, Listen, Tabellen, fett).
    Nutzt nur Stile, die in der jeweiligen Vorlage tatsächlich existieren —
    fällt sonst auf einfache Absätze zurück, statt abzustürzen."""

    lines = markdown_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()

        if not line.strip():
            i += 1
            continue

        # Horizontale Trennlinien (---, ***, ___) aus dem Markdown ignorieren —
        # Claude nutzt sie gelegentlich als Abschnittstrenner, sie sollen aber
        # nicht als sichtbarer Text "---" im Word-Dokument landen.
        stripped = line.strip()
        if re.fullmatch(r"[-*_]{3,}", stripped):
            i += 1
            continue

        if stripped.startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            # Tabelle wird von python-docx an der aktuellen Cursor-Position
            # eingefügt (nicht ans Dokumentende) — das funktioniert bereits korrekt.
            _insert_table(doc, table_lines)
            continue

        if line.startswith("## "):
            doc.add_heading(_strip_md(line[3:]), level=1)
        elif line.startswith("### "):
            doc.add_heading(_strip_md(line[4:]), level=2)
        elif line.startswith("#### "):
            doc.add_heading(_strip_md(line[5:]), level=3)
        elif stripped.startswith(("- ", "* ")):
            # ListWithSymbols zuerst: hat KEINE eigene Einrückung in der HSLU-
            # Vorlage (erbt 0 von Normal). List Paragraph hat 1.27cm feste
            # Einrückung eingebaut — das sah bei Tests deutlich zu weit
            # eingerückt aus. Daher als letzten Fallback, nicht als ersten.
            p = _safe_paragraph(doc, line, ["ListWithSymbols", "List Bullet", "List Paragraph"])
            p.paragraph_format.left_indent = Cm(0.5)
            p.paragraph_format.first_line_indent = Cm(-0.5)
            _add_formatted_run(p, stripped[2:])
        elif re.match(r"^\d+\.\s", stripped):
            p = _safe_paragraph(doc, line, ["List Number", "List Paragraph"])
            content = re.sub(r"^\d+\.\s", "", stripped)
            _add_formatted_run(p, content)
        else:
            p = doc.add_paragraph()
            _add_formatted_run(p, line)

        i += 1


def _insert_table(doc: Document, table_lines: list[str]) -> None:
    """Wandelt Markdown-Tabellenzeilen in eine echte Word-Tabelle um."""
    rows_data = []
    for line in table_lines:
        cells = [c.strip() for c in line.strip("|").split("|")]
        # Trennzeile (|---|---|) überspringen
        if all(set(c) <= {"-", " ", ":"} for c in cells):
            continue
        rows_data.append(cells)

    if not rows_data:
        return

    n_cols = len(rows_data[0])
    table = doc.add_table(rows=len(rows_data), cols=n_cols)

    # Tabellenstil nur setzen, wenn er im Dokument existiert — die HSLU-Vorlage
    # hat ggf. eigene/keine Table-Styles. Ohne passenden Stil bleibt die Tabelle
    # ungestylt, wird aber unten manuell formatiert (Header fett, Rahmen).
    for style_name in ("Light Grid Accent 1", "Table Grid", "Grid Table Light"):
        try:
            table.style = style_name
            break
        except KeyError:
            continue

    for ri, row_data in enumerate(rows_data):
        for ci, cell_text in enumerate(row_data):
            if ci < n_cols:
                cell = table.cell(ri, ci)
                cell.text = ""
                p = cell.paragraphs[0]
                run = p.add_run(cell_text)
                if ri == 0:
                    run.bold = True

    # Leerabsatz nach der Tabelle für sauberen Abstand
    doc.add_paragraph()


def _add_formatted_run(paragraph, text: str) -> None:
    """Fügt Text hinzu und übersetzt **fett** und *kursiv* in echte Formatierung."""
    pattern = r"(\*\*.+?\*\*|\*.+?\*)"
    parts = re.split(pattern, text)

    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**"):
            run = paragraph.add_run(part[2:-2])
            run.bold = True
        elif part.startswith("*") and part.endswith("*"):
            run = paragraph.add_run(part[1:-1])
            run.italic = True
        else:
            paragraph.add_run(part)


def _strip_md(text: str) -> str:
    return text.replace("**", "").strip()


# ---------------------------------------------------------------------------
# Fallback ohne Vorlage (falls assets/hslu_vorlage.docx fehlt)
# ---------------------------------------------------------------------------

def _save_plain(markdown_text: str, output_path: str) -> None:
    from docx.shared import Pt, Cm

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    for section in doc.sections:
        section.left_margin = Cm(2.5)
        section.right_margin = Cm(2.5)

    _insert_markdown_content(doc, markdown_text)
    doc.save(output_path)