# KI-Werkbank

Eine lokale, wachsende Sammlung von KI-gestützten Tools für wiederkehrende Büroaufgaben — läuft komplett auf dem eigenen Rechner, nicht in der Cloud.

## Die Idee

Statt eine einzelne KI-App zu bauen, ist die Werkbank als eigenes „Betriebssystem" mit mehreren Apps gedacht, die nach Bedarf dazukommen — jede für eine konkrete, wiederkehrende Aufgabe. Eine gemeinsame Weboberfläche bündelt sie; neue Apps werden nur gebaut, wenn ein echter Bedarf entsteht, nicht auf Vorrat.

## Architekturprinzip

Jede App läuft als eigener, unabhängiger Prozess mit eigener Softwareumgebung — nicht als ein einziges großes Programm. Das hat zwei Gründe:

- **Keine Konflikte zwischen App-Abhängigkeiten.** Verschiedene Apps brauchen teils inkompatible Softwareversionen; getrennte Umgebungen verhindern, dass sich das gegenseitig kaputtmacht.
- **Faire GPU-Nutzung.** Der Rechner hat eine einzelne Grafikkarte, aber mehrere Apps brauchen sie für KI-Berechnungen. Ein Koordinationsmechanismus sorgt dafür, dass immer nur eine App gleichzeitig rechnet, statt sich gegenseitig zu blockieren — und jede App gibt den Grafikspeicher automatisch wieder frei, sobald sie fertig ist.

## Aktuelle Apps

### 1. Besprechung → Protokoll
Audio hochladen → automatische Transkription (lokal, auf der eigenen Grafikkarte) → strukturiertes Protokoll im gewohnten Layout, als Word- und Markdown-Datei. Erkennt offene Pendenzen aus der letzten Sitzung derselben Sitzungsreihe automatisch mit.

### 2. PDF-Anonymisierung
PDF hochladen → Text wird extrahiert und automatisch von Namen, Adressen und Organisationen befreit (geschwärzt) → anonymisierte Fassung als Markdown zum Weiterverwenden. Komplett lokal, auch im Flugmodus getestet und bestätigt.

## Datenschutz

Die Verarbeitung selbst — Audiodaten, PDF-Inhalte — verlässt den Rechner nie. Einzige Ausnahme: Der letzte Schritt der Protokoll-Erstellung (aus dem fertigen Transkript ein strukturiertes Protokoll formulieren) nutzt die Anthropic-Cloud-API, da dort keine rohen Audiodaten übertragen werden, nur der bereits transkribierte Text.

## Technischer Rahmen

Windows 11, lokale GPU (RTX 4080, 12GB), Python/Flask. Jede App in eigener, isolierter Softwareumgebung.

## Stand

Beide Apps sind fertig gebaut, End-to-End getestet und produktiv nutzbar — inklusive robuster Koordination bei gleichzeitiger Nutzung mehrerer Apps. Weitere Apps kommen dazu, sobald ein konkreter Bedarf entsteht.
