# Auftrag für Claude Code: Typografie-Abgleich "Tools" vs. "Projekte" prüfen

Reiner Prüfauftrag, keine Design-Entscheidung — nur Ist-Zustand feststellen
und Abweichungen konkret benennen, damit der Nutzer entscheiden kann, ob
etwas angepasst werden soll.

## Hintergrund

Nach dem Merge der gemeinsamen `typography.css` (Archivo/IBM Plex Mono aus
`projektansicht.html` entfernt, gemeinsamer Typo-Scale mit `hub/templates`
eingeführt) ist auf Screenshots nicht sicher erkennbar, ob beide Tabs
("Tools" = `index.html`, "Projekte" = `projektansicht.html`) wirklich
dieselbe Schrift/Grösse für vergleichbare Elemente zeigen. Auffällig: die
grossen KPI-Zahlen und die Kopfzeile ("AUSLASTUNG · STAND AUGUST 2026 · ...")
in "Projekte" sehen wie eine schmale Monospace-Schrift aus — dafür gibt's
in "Tools" kein direkt vergleichbares Element.

## Schritte

1. Bestätigen, dass beide Templates `typography.css` über denselben Pfad
   einbinden (identischer `<link>`, kein zweiter, abweichender Include).

2. Beide Templates nach lokalen `font-family`- / `font-size`-Deklarationen
   durchsuchen (grep im `<style>`-Block bzw. in eingebundenen CSS-Dateien),
   die die gemeinsame Datei überschreiben könnten — insbesondere Reste von
   `Archivo` oder `IBM Plex Mono`, die beim Merge evtl. nicht vollständig
   entfernt wurden.

3. Konkret klären: Ist die Monospace-Schrift bei den KPI-Zahlen und der
   Kopfzeile in "Projekte" (a) bewusst in `typography.css` als Stil für
   Zahlen/Meta-Labels definiert und dort konsistent verwendet — dann ist
   das Absicht, kein Fehler — oder (b) ein Rest aus einer früheren, nicht
   vollständig gemergten Version?

4. Für drei vergleichbare Elementpaare den tatsächlich gerenderten
   ("Computed", per DevTools oder durch Nachvollziehen der CSS-Kaskade)
   `font-family`- und `font-size`-Wert ermitteln und gegenüberstellen:
   - Seitentitel (`<h1>`: "KI-Werkbank" vs. "Projektprogramm")
   - Fliesstext/Beschreibung (z.B. Tool-Beschreibungstext vs. Legende
     unten in "Projekte")
   - Kleine Labels (z.B. Feld-Label "Verarbeitung" vs. Spaltenkopf
     "PROJEKT / TRÄGER")

5. Kurzer Bericht: Stimmen die drei Paare überein? Falls nicht — welche
   Datei, welche Zeile/Regel weicht ab, und ein Vorschlag, wie es
   vereinheitlicht würde (ohne die Änderung selbst schon vorzunehmen,
   ausser der Nutzer bestätigt das nach dem Bericht).

## Nicht tun

- Keine Font-Änderungen selbst vornehmen, bevor der Bericht steht und der
  Nutzer grünes Licht gibt — auch wenn eine Abweichung offensichtlich
  unbeabsichtigt wirkt.
