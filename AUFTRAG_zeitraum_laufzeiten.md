# Auftrag für Claude Code: Zeitraum-Laufzeiten im Gantt-Chart darstellen

Reiner JS-Logik-Patch in `apps/projektansicht/templates/projektansicht.html`.
**CSS/Typografie NICHT anfassen** — die wurden in einem früheren Auftrag
bereits korrekt gemergt und gefixt (u.a. `h1`-Weight/Letter-Spacing,
`.legende`-Grösse). Nur die vier unten genannten JS-Stellen ändern.

## Hintergrund

`parser.py` liefert jetzt zusätzlich zum bisherigen `{typ: "monat", monat,
jahr}` (nur Ende) und `{typ: "fortlaufend"}` einen neuen Typ:
`{typ: "zeitraum", start_monat, start_jahr, end_monat, end_jahr}` — mit
explizitem Start UND Ende, weil der Nutzer die Excel-Spalte "Laufzeit bis"
auf Zeiträume ("01.06.26-30.08.2026") statt Einzelmonate umgestellt hat.

Alle vier Änderungen wurden isoliert in Node getestet (6 Testfälle inkl.
Rückwärtskompatibilität zu "monat"/"fortlaufend"/"unbekannt"), alle grün.

## Änderung 1 — Achsenende-Berechnung

Alt:
```js
let endIdx = 11;
for (const p of DATA.projekte) {
  if (p.laufzeit.typ === "monat") {
    const i = (p.laufzeit.jahr - jahr) * 12 + p.laufzeit.monat - 1;
    if (i > endIdx) endIdx = i;
  }
}
```

Neu:
```js
let endIdx = 11;
for (const p of DATA.projekte) {
  if (p.laufzeit.typ === "monat") {
    const i = (p.laufzeit.jahr - jahr) * 12 + p.laufzeit.monat - 1;
    if (i > endIdx) endIdx = i;
  } else if (p.laufzeit.typ === "zeitraum") {
    const i = (p.laufzeit.end_jahr - jahr) * 12 + p.laufzeit.end_monat - 1;
    if (i > endIdx) endIdx = i;
  }
}
```

## Änderung 2 — "laufende Projekte"-KPI

Alt:
```js
const laufend = projekte.filter(p =>
  p.laufzeit.typ !== "monat" ||
  (p.laufzeit.jahr - jahr) * 12 + p.laufzeit.monat - 1 >= heuteIdx).length;
```

Neu:
```js
const laufend = projekte.filter(p => {
  if (p.laufzeit.typ === "monat")
    return (p.laufzeit.jahr - jahr) * 12 + p.laufzeit.monat - 1 >= heuteIdx;
  if (p.laufzeit.typ === "zeitraum")
    return (p.laufzeit.end_jahr - jahr) * 12 + p.laufzeit.end_monat - 1 >= heuteIdx;
  return true; // fortlaufend/unbekannt zaehlen weiterhin als laufend
}).length;
```

## Änderung 3 — Balken-Start/Ende-Logik (Kernstück)

Alt:
```js
      // Balkenstart: erster Monat mit Stunden; ohne Stunden -> nach heute (geplant)
      let start = p.stunden.findIndex(h => h > 0);
      if (start < 0) start = heuteIdx + 1;
      let ende, offen = false, unklar = false;
      if (p.laufzeit.typ === "monat") {
        ende = (p.laufzeit.jahr - jahr) * 12 + p.laufzeit.monat - 1;
      } else if (p.laufzeit.typ === "fortlaufend") {
        ende = achse.length - 1; offen = true;
      } else { ende = heuteIdx; unklar = true; }
      if (ende < start) start = Math.max(0, ende);
```

Neu:
```js
      // Bei "zeitraum": Start UND Ende kommen direkt aus dem Rapport, nicht
      // mehr aus den ersten rapportierten Stunden abgeleitet. Liegt der
      // echte Start vor Achsenbeginn (Projekt startete vor dem aktuellen
      // Berichtsjahr), wird der Balken bei Index 0 abgeschnitten und links
      // markiert statt mit negativem Index zu rechnen.
      let start, ende, offen = false, unklar = false, startAbgeschnitten = false;
      if (p.laufzeit.typ === "zeitraum") {
        const startIdx = (p.laufzeit.start_jahr - jahr) * 12 + p.laufzeit.start_monat - 1;
        const endeIdx = (p.laufzeit.end_jahr - jahr) * 12 + p.laufzeit.end_monat - 1;
        if (startIdx < 0) { start = 0; startAbgeschnitten = true; } else { start = startIdx; }
        ende = endeIdx;
      } else {
        // Balkenstart: erster Monat mit Stunden; ohne Stunden -> nach heute (geplant)
        start = p.stunden.findIndex(h => h > 0);
        if (start < 0) start = heuteIdx + 1;
        if (p.laufzeit.typ === "monat") {
          ende = (p.laufzeit.jahr - jahr) * 12 + p.laufzeit.monat - 1;
        } else if (p.laufzeit.typ === "fortlaufend") {
          ende = achse.length - 1; offen = true;
        } else { ende = heuteIdx; unklar = true; }
      }
      if (ende < start) start = Math.max(0, ende);
```

## Änderung 4 — Zellen-Rendering (Eckenrundung + linke Markierung)

Alt (innerhalb der `achse.forEach((m, i) => { ... })`-Schleife):
```js
        if (im) {
          const op = h ? (0.25 + 0.75 * Math.min(1, h / maxH)) : 1;
          const bg = h ? farbe : farbe + "26";
          const r = (i === start ? "3px 0 0 3px" : (i === ende && !offen ? "0 3px 3px 0" : "0"));
          inner += `<div class="balken" style="background:${bg};opacity:${h ? op : 1};border-radius:${r}"></div>`;
        }
        if (unklar && i === ende)
          inner += `<span class="mono" style="position:absolute;top:50%;right:3px;transform:translateY(-50%);font-size:10px;color:var(--grau)">?</span>`;
```

Neu:
```js
        if (im) {
          const op = h ? (0.25 + 0.75 * Math.min(1, h / maxH)) : 1;
          const bg = h ? farbe : farbe + "26";
          const rl = (i === start && !startAbgeschnitten) ? "3px" : "0";
          const rr = (i === ende && !offen) ? "3px" : "0";
          const r = `${i===start?rl:"0"} ${i===ende?rr:"0"} ${i===ende?rr:"0"} ${i===start?rl:"0"}`;
          inner += `<div class="balken" style="background:${bg};opacity:${h ? op : 1};border-radius:${r}"></div>`;
        }
        if (unklar && i === ende)
          inner += `<span class="mono" style="position:absolute;top:50%;right:3px;transform:translateY(-50%);font-size:10px;color:var(--grau)">?</span>`;
        if (startAbgeschnitten && i === start)
          inner += `<span class="mono" style="position:absolute;top:50%;left:3px;transform:translateY(-50%);font-size:10px;color:var(--grau)">←</span>`;
```

## Änderung 5 — Legendentext ergänzen

In der `.legende`-Zeile den bestehenden Satz zu Balken/«?» um einen Halbsatz
zum Pfeil ergänzen, z.B. direkt nach "«?» = Laufzeit im Rapport unklar).":
`«←» = Projektstart liegt vor Januar ${jahr}, Balken ist links abgeschnitten.`

## Test danach

- Seite neu laden, prüfen dass "«Elektrifizierung städtischer Baustellen»"
  (Start 30.08.2024 laut Rapport) jetzt ab Achsenbeginn (Jan 2026) mit
  "←"-Marker startet statt wie bisher erst im Monat der ersten rapportierten
  Stunden.
- "ISA-Module Blockwoche" (Zeitraum 15.02.27-19.02.27, eine reine Blockwoche)
  sollte jetzt als sehr kurzer Balken im Feb 2027 erscheinen statt "?" bis
  heute.
- "FS26 BIM Grundlagen" zeigt weiterhin "?" (Laufzeit-Zelle im Rapport ist
  aktuell `17.08-26-20.08.26`, ein Tippfehler — der Nutzer korrigiert das
  selbst in Excel, kein Code-Fix nötig).
