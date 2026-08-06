# Auftrag für Claude Code: Kopfbereich "Projekte" an "Tools" angleichen

Reiner Kopfbereich-Fix in `apps/projektansicht/templates/projektansicht.html`.
Gantt-Bereich, KPI-Zeile, Filter-Chips, Legende: unangetastet.

## Teil 1 — Titel zusammenlegen

Aktuell zwei Zeilen übereinander: eine kleine graue Label-Zeile
("AUSLASTUNG · STAND AUGUST 2026 · QUELLE: STUNDENRAPPORT_2026.XLSX",
per JS aus `DATA.stand`/`DATA.quelle` gefüllt) und darunter der grosse
statische Titel `<h1>Projektprogramm</h1>`.

Gewünscht: nur noch EINE Titelzeile, analog zu `index.html` (Tools), wo es
nur einen einzelnen `<h1>KI-Werkbank</h1>` gibt, keine zusätzliche Label-
Zeile darüber. Die kleine Zeile fällt weg, ihr Inhalt wandert in den `<h1>`:

- `<h1>` zeigt künftig dynamisch: `Auslastung · Stand ${DATA.stand} · Quelle: ${DATA.quelle}`
- Das bisherige `<div class="eyebrow" id="eyebrow">...</div>`-Element und die
  zugehörige JS-Zeile (`document.getElementById("eyebrow").textContent = ...`)
  entfernen bzw. so umbauen, dass derselbe Text stattdessen in den `<h1>`
  geschrieben wird.
- Die CSS-Klasse des `<h1>` (Grösse/Gewicht) bleibt wie sie ist — nur der
  Inhalt und die Quelle des Inhalts ändern sich, keine neuen Typografie-Werte.

## Teil 2 — Kopfbereich-Layout angleichen (erst messen, dann fixen)

1. In `index.html` (Tools) den `<header>`-Bereich (bzw. das Element, das den
   sichtbaren Kopf nach der Tab-Leiste umschliesst) per Computed Style
   prüfen: `background-color`, `padding-top` (bzw. `margin-top` des ersten
   Kind-Elements), damit der tatsächlich gerenderte Abstand zur Tab-Leiste
   bekannt ist, nicht nur der Code-Wert.
2. Dasselbe in `projektansicht.html` für den entsprechenden Kopfbereich
   ermitteln.
3. Abweichungen feststellen und benennen (z.B. "Tools: padding-top 26px,
   background transparent; Projekte: padding-top 16px, background #FAFAF8 —
   Unterschied X px / Y").
4. `projektansicht.html` auf die in `index.html` gemessenen Werte anpassen
   (Tools ist die Referenz, nicht umgekehrt).

## Bericht

Kurz: welche Werte vorher/nachher bei Schritt 2–4, damit nachvollziehbar
bleibt, was sich geändert hat — wie beim früheren Typografie-Audit.

## Test danach

- Beide Tabs direkt nacheinander aufrufen (Tab wechseln, nicht neu laden),
  prüfen dass Hintergrund und oberer Abstand beim Wechsel nicht sichtbar
  "springen".
- Projekte-Titel zeigt jetzt einzeilig "Auslastung · Stand August 2026 ·
  Quelle: Stundenrapport_2026.xlsx" statt "Projektprogramm" mit Label-Zeile
  darüber.
