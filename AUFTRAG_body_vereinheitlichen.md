# Auftrag für Claude Code: Body-Hintergrund und -Padding vereinheitlichen

Direkter Fix, keine erneute Messung nötig — Werte stammen aus deinem eigenen
Bericht zum letzten Auftrag:

| | Tools (Referenz) | Projekte (aktuell) |
|---|---|---|
| `body` background-color | `#f7f8fa` | `#FAFAF8` |
| `body` padding | `32px 20px` | `0` |

## Ziel

`projektansicht.html` auf dieselben Werte wie `index.html` bringen — aber
diesmal nicht den Wert einfach kopieren, sondern **dieselbe Regel/Variable
referenzieren**, damit die beiden Seiten nicht beim nächsten Redesign
wieder auseinanderlaufen (das ist jetzt schon das dritte Mal, dass sich
zwei eigentlich gleiche Werte unbemerkt unterschieden haben — Titel-Gewicht,
Header-Padding, jetzt Body-Hintergrund/Padding).

## Schritte

1. Prüfen, wie `index.html` (Tools) `body { background-color: #f7f8fa;
   padding: 32px 20px; ... }` definiert — direkt im `<style>`-Block, oder
   über eine Variable in `typography.css` bzw. einer anderen gemeinsamen
   Datei?
2. Falls direkt im `<style>`-Block von `index.html` (nicht in der
   gemeinsamen `typography.css`): diese beiden Werte (Hintergrundfarbe,
   Padding) als neue Variablen in `typography.css` auslagern (z.B.
   `--bg-page` und `--page-padding` oder passende Namen nach bestehender
   Konvention), `index.html` darauf umstellen.
3. `projektansicht.html`s `body`-Regel auf dieselben Variablen umstellen,
   statt eigene Werte zu behalten.
4. Falls `index.html` bereits eine gemeinsame Variable nutzt: einfach
   dieselbe Variable in `projektansicht.html` referenzieren, kein neuer
   Schritt nötig.

## Test danach

- Computed Style von `body` in beiden Tabs vergleichen: background-color
  und padding müssen exakt übereinstimmen.
- Visueller Check: zwischen Tools und Projekte hin- und herwechseln, kein
  sichtbarer Sprung bei Seitenrand oder Hintergrund.
- Gantt-Bereich, KPI-Zeile, Filter-Chips, Legende, Kopfbereich (letzter
  Auftrag) bleiben unverändert — nur `body` selbst betroffen.
