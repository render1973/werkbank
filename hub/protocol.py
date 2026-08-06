"""
Protokollgenerierung: schickt das Transkript an die Claude API und lässt
ein strukturiertes Protokoll daraus bauen — nach dem Muster deiner echten
HSLU-Sitzungsprotokolle (Traktanden, Themen & Diskussion, Beschlüsse, To-dos).

Unterstützt Pendenzen-Abgleich mit dem letzten Protokoll derselben Sitzungsreihe
und schlägt Traktanden für die nächste Sitzung vor.
"""

import os
from dotenv import load_dotenv

load_dotenv(override=True)

from anthropic import Anthropic

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# ---------------------------------------------------------------------------
# Struktur nach dem Muster deiner echten HSLU-Protokolle (Vorlage 260610_Protokoll).
# Felder in {geschweiften Klammern} werden automatisch befüllt.
# ---------------------------------------------------------------------------
PROTOCOL_STRUCTURE = """
### Traktanden
[Liste der behandelten Themen, als Kurztitel, in der besprochenen Reihenfolge]

### Themen & Diskussion
[Pro Traktandum ein ## Heading mit dem Thema als Titel, darunter die Diskussionspunkte
als Aufzählung. Positionen einzelner Personen mit Namen kennzeichnen, wo im Transkript
klar erkennbar (z.B. "Reto Ineichen stellte vor..."). Bei mehreren Varianten/Optionen
diese als benannte Unterpunkte (Variante 1, Variante 2, ...) mit Vor-/Nachteilen.
Am Ende eines Themenblocks, falls ein Konsens erkennbar ist: "Konsens: ..." explizit
als eigene Zeile.]

### Beschlüsse
[Nur tatsächlich getroffene Entscheidungen — nicht diskutierte Optionen. Jeder Beschluss
ein eigener Punkt, knapp und konkret formuliert.]

### To-dos / Pendenzen
[Tabelle mit Spalten: # | Aufgabe | Verantwortlich | Termin.
Nur Aufgaben mit erkennbarer Verantwortlichkeit aufnehmen. Termin nennen, wenn im
Transkript erwähnt, sonst "offen".]
"""

PENDENZEN_ABGLEICH_INSTRUCTION = """
### Pendenzen-Abgleich zum Vorprotokoll

Vor der eigentlichen Struktur oben: Vergleiche die folgenden Pendenzen aus dem letzten
Protokoll dieser Sitzungsreihe mit dem neuen Transkript. Für jede alte Pendenz:

- ERLEDIGT — wenn im Transkript klar bestätigt (z.B. "das haben wir gemacht", "ist erledigt")
- WEITERHIN OFFEN — wenn nicht erwähnt oder explizit als noch offen bestätigt
- NEU KONTEXTUALISIERT — wenn im Transkript erwähnt, aber mit neuem Stand/Verantwortlichkeit

Erfinde keine Bestätigung — wenn das Transkript eine Pendenz nicht erwähnt, ist sie
WEITERHIN OFFEN, nicht automatisch erledigt.

Alte Pendenzen aus dem letzten Protokoll:
{previous_pendenzen}

Gib diesen Abgleich als eigenen Abschnitt VOR "### Traktanden" aus, in diesem Format:

### Pendenzen-Abgleich (Stand aus {previous_date})
| # | Aufgabe (aus letztem Protokoll) | Status | Kommentar |
|---|---|---|---|
[eine Zeile pro alter Pendenz]
"""

TRAKTANDEN_VORSCHLAG_INSTRUCTION = """
Erstelle am ENDE des Protokolls, nach "### To-dos / Pendenzen", einen letzten Abschnitt:

### Traktandenvorschlag nächste Sitzung
[Liste ausschliesslich der Pendenzen, die im obigen Abschnitt "To-dos / Pendenzen" als
weiterhin offen erfasst sind — als kurze Themenpunkte formuliert, nicht als Aufgaben-Tabelle.
Wenn keine Pendenz offen ist, diesen Abschnitt weglassen.]
"""

SYSTEM_PROMPT = """Du erstellst Besprechungsprotokolle aus Transkripten für einen \
Senior Wissenschaftlichen Mitarbeiter an einer Schweizer Hochschule (HSLU).

Regeln:
- Schreib auf Deutsch, sachlich, knapp. Keine Füllwörter, keine KI-Floskeln.
- Unterscheide strikt zwischen tatsächlichen Entscheidungen/Beschlüssen und bloß \
diskutierten Optionen. Nur weil etwas erwähnt wurde, ist es kein Beschluss.
- Pendenzen nur aufnehmen, wenn im Transkript eine konkrete Aufgabe und wenn möglich \
eine verantwortliche Person genannt wurde. Erfinde keine Verantwortlichkeiten.
- Wenn das Transkript unklar oder lückenhaft ist (z.B. wegen Transkriptionsfehlern), \
kennzeichne die entsprechende Stelle mit [unklar] statt zu raten.
- Halte dich an die vorgegebene Struktur. Lass leere Abschnitte weg, statt sie mit \
Platzhaltern zu füllen.
- Bei Positionen einzelner Personen: nur Namen zuordnen, die im Transkript klar \
erkennbar mit einer Aussage verknüpft sind. Bei Unsicherheit neutral formulieren.
- Gib NUR das fertige Protokoll in Markdown zurück, ohne Vorbemerkung oder Nachfrage."""


def generate_protocol(
    transcript: str,
    meeting_title: str,
    meeting_date: str,
    participants: str = "",
    custom_notes: str = "",
    previous_pendenzen=None,
    previous_date: str = "",
) -> str:
    """Erstellt ein strukturiertes Protokoll aus einem rohen Transkript.

    previous_pendenzen: Liste von Dicts mit Keys 'aufgabe', 'verantwortlich', 'termin' —
    aus dem letzten Protokoll derselben Sitzungsreihe. None/leer beim ersten Protokoll
    einer neuen Reihe.
    """

    structure_filled = PROTOCOL_STRUCTURE

    pendenzen_block = ""
    if previous_pendenzen:
        pendenzen_text = "\n".join(
            f"- {p['aufgabe']} (Verantwortlich: {p['verantwortlich']}, Termin: {p['termin']})"
            for p in previous_pendenzen
        )
        pendenzen_block = PENDENZEN_ABGLEICH_INSTRUCTION.format(
            previous_pendenzen=pendenzen_text,
            previous_date=previous_date or "letzte Sitzung",
        )

    kopfdaten_hinweis = (
        f"(Kontext, NICHT im Protokolltext wiederholen — steht bereits in der "
        f"Word-Kopftabelle: Titel '{meeting_title}', Datum {meeting_date}, "
        f"Teilnehmende: {participants or '[nicht angegeben]'}.)"
    )

    user_prompt = f"""{kopfdaten_hinweis}

Erstelle ein Protokoll nach genau dieser Struktur — beginne direkt mit "### Traktanden",
ohne Titel, Datum oder Teilnehmende nochmal aufzuführen:

{structure_filled}

---
{pendenzen_block}
---
{TRAKTANDEN_VORSCHLAG_INSTRUCTION}
---

Zusätzlicher Kontext vom Nutzer (falls vorhanden, berücksichtigen):
{custom_notes or "(keiner)"}

---

Transkript der Besprechung:

{transcript}
"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    protocol_text = "".join(
        block.text for block in response.content if hasattr(block, "text")
    )

    return protocol_text.strip()
