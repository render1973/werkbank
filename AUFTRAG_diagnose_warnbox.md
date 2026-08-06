# Auftrag für Claude Code: Warnbox für Diagnose-Meldungen anzeigen

Rein additiver Patch in `apps/projektansicht/templates/projektansicht.html`.
Nichts Bestehendes ändern oder entfernen — nur neue CSS-Regel + neues
HTML-Element + kleine JS-Ergänzung.

## Hintergrund

`parser.py` liefert jetzt zusätzlich `"warnungen": [...]` (Liste von
Strings, meist leer). Grund: Excel-Label-Änderungen (umbenannte oder
doppelt vorhandene Zeilen wie zuletzt "Laufzeit" + "Laufzeit bis"
gleichzeitig) führten bisher dazu, dass der Parser still auf die falsche
oder eine leere Zeile griff — sichtbar erst im Dashboard, nicht vorher.
Die Warnbox macht das sofort sichtbar, blockiert aber nichts (anders als
die rote `.fehler`-Box, die nur bei echten Abstürzen erscheint).

## Schritt 1 — CSS ergänzen (neue Regel, nichts ändern)

Direkt nach der bestehenden `.fehler`-Regel einfügen:

```css
.warnung { margin:12px 24px 0; padding:10px 16px; border:1.5px solid #C7871B;
           border-radius:6px; color:#8A5A00; background:#FDF6E8;
           font-size:12.5px; line-height:1.5; }
.warnung + .warnung { margin-top:6px; }
```

## Schritt 2 — HTML ergänzen

Im `<body>`, zwischen `</header>` und `<div id="inhalt"></div>`, neues
leeres Element einfügen:

```html
<div id="warnungen"></div>
```

## Schritt 3 — JS ergänzen

Direkt nach dem bestehenden Block

```js
if (DATA.fehler) {
  document.getElementById("inhalt").innerHTML = ...
} else {
  bauen();
}
```

ergänzen (vor oder nach diesem Block, aber unabhängig davon — Warnungen
und Dashboard schliessen sich nicht gegenseitig aus):

```js
if (DATA.warnungen && DATA.warnungen.length) {
  document.getElementById("warnungen").innerHTML = DATA.warnungen
    .map(w => `<div class="warnung">⚠ ${w}</div>`).join("");
}
```

## Test danach

- Mit der aktuellen echten Datei (die noch die alte "Laufzeit bis"-Zeile
  neben der neuen "Laufzeit"-Zeile hat): eine gelb/amber Warnbox sollte
  zwischen Kopfbereich und Gantt-Chart erscheinen, Text ungefähr:
  "Feld „laufzeit" mehrdeutig: 2 passende Zeilen gefunden — „Laufzeit"
  (Zeile 8); „Laufzeit bis" (Zeile 70). Verwendet wird die oberste
  (Zeile 8)."
- Dashboard darunter muss trotz Warnung normal weiter funktionieren (keine
  Blockade, nur Hinweis).
- Kurzer Test mit einer Kopie, bei der kein Label-Problem besteht (z.B.
  Zeile 70 versuchsweise umbenennen/löschen): Warnbox verschwindet, keine
  Restspuren im DOM.
