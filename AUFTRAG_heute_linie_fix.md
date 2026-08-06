# Auftrag für Claude Code: "Heute"-Linie korrekt aus stand_monat berechnen

Ein-Zeilen-Fix in `apps/projektansicht/templates/projektansicht.html`.

## Hintergrund

`parser.py` liefert jetzt zusätzlich `"stand_monat": <1-12>` — den
tatsächlichen aktuellen Monat, direkt aus dem Excel-Sheet-Namen (z.B.
"August 2026" -> 8) statt aus der Länge der Monatsliste geraten. Grund:
seit der Excel-Umstellung listet das Sheet immer alle 12 Monate (Jan-Dez),
auch wenn erst August erreicht ist — die bisherige Berechnung
`heuteIdx = DATA.monate.length - 1` ergab dadurch fälschlich Dezember
statt August.

## Änderung

Suchen:
```js
const nRapportiert = DATA.monate.length;         // Jan..letzter rapportierter Monat
const heuteIdx = nRapportiert - 1;
```

Ersetzen durch:
```js
const heuteIdx = (DATA.stand_monat || DATA.monate.length) - 1;
```

(Fallback auf die alte Berechnung bleibt erhalten, falls `stand_monat`
in einer älteren Antwort mal fehlen sollte — schadet nicht, ist aber mit
aktuellem `parser.py` nicht mehr der Regelfall.)

## Test danach

- Rote "Heute"-Linie steht bei Aug 26, nicht bei Dez 26.
- KPI "laufende Projekte" und alle Balken-Berechnungen, die `heuteIdx`
  nutzen, entsprechend neu geprüft (sollten sich automatisch mit anpassen,
  da sie alle von dieser einen Variable ausgehen).
