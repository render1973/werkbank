"""
Pipeline: PDF -> Markdown (PaddleOCR-VL) -> HTML-Bereinigung -> Anonymisierung
(Presidio + offizieller GLiNER-Recognizer aus presidio-analyzer[gliner]).

Voraussetzungen (im aktiven venv):
    pip install "paddleocr[doc-parser]>=3.6.0"
    pip install "presidio-analyzer[gliner]" presidio-anonymizer
    python -m spacy download de_core_news_lg   (wird nur fuer Tokenisierung geladen,
                                                  die eigentliche Erkennung macht GLiNER)

Nutzung:
    python pipeline.py <pfad_zur_datei.pdf>

Ergebnis:
    output/<dateiname>/roh.md            -- unbereinigtes OCR-Ergebnis
    output/<dateiname>/anonymisiert.md   -- anonymisiertes Ergebnis (BITTE GEGENLESEN)
"""

import re
import sys
from pathlib import Path

from paddleocr import PaddleOCRVL
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.predefined_recognizers import GLiNERRecognizer
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig


def clean_markdown(text: str) -> str:
    """Entfernt HTML-Tags, Style-Attribute und Bildverweise, die die NER-Erkennung
    stoeren (rohe Tabellen-HTML im Markdown fuehrt sonst zu vielen Fehltreffern)."""
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)       # Markdown-Bilder
    text = re.sub(r'<img[^>]*>', '', text)              # HTML-Bilder
    text = re.sub(r'<[^>]+>', ' ', text)                # uebrige HTML-Tags, Text bleibt
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n\n', text)
    return text.strip()


def convert_pdf(pdf_path: Path, work_dir: Path) -> str:
    """PDF -> Markdown (pro Seite), zu einem String zusammengefuehrt."""
    print(f"1/4 Konvertiere PDF: {pdf_path.name} ...")
    pipeline = PaddleOCRVL()
    output = pipeline.predict(str(pdf_path))

    page_dir = work_dir / "pages"
    page_dir.mkdir(parents=True, exist_ok=True)
    for res in output:
        res.save_to_markdown(save_path=str(page_dir))

    md_files = sorted(
        page_dir.glob(f"{pdf_path.stem}_*.md"),
        key=lambda f: int(f.stem.rsplit("_", 1)[-1]),
    )
    if not md_files:
        raise RuntimeError("Keine Markdown-Seiten erzeugt - Konvertierung pruefen.")

    return "\n\n---\n\n".join(f.read_text(encoding="utf-8") for f in md_files)


def anonymize(text: str) -> str:
    """HTML bereinigen, mit dem offiziellen Presidio-GLiNER-Recognizer erkennen,
    dann anonymisieren."""
    print("2/4 Bereinige Text (HTML/Bildverweise entfernen) ...")
    cleaned = clean_markdown(text)

    print("3/4 Analysiere mit GLiNER (offizieller Presidio-Recognizer) ...")
    analyzer = AnalyzerEngine()

    entity_mapping = {
        "person": "PERSON",
        "name": "PERSON",
        "organization": "ORGANIZATION",
        "address": "ADDRESS",
        "location": "LOCATION",
        "phone number": "PHONE_NUMBER",
        "email": "EMAIL_ADDRESS",
    }

    gliner_recognizer = GLiNERRecognizer(
        model_name="urchade/gliner_multi_pii-v1",
        entity_mapping=entity_mapping,
        flat_ner=False,
        multi_label=True,
        map_location="cpu",
    )

    analyzer.registry.add_recognizer(gliner_recognizer)
    analyzer.registry.remove_recognizer("SpacyRecognizer")  # nur GLiNER soll erkennen

    results = analyzer.analyze(text=cleaned, language="de")
    print(f"   {len(results)} Treffer gefunden.")

    print("4/4 Anonymisiere ...")
    anonymizer = AnonymizerEngine()
    operators = {
        "PERSON": OperatorConfig("replace", {"new_value": "<PERSON>"}),
        "ADDRESS": OperatorConfig("replace", {"new_value": "<ADRESSE>"}),
        "LOCATION": OperatorConfig("replace", {"new_value": "<ORT>"}),
        "ORGANIZATION": OperatorConfig("replace", {"new_value": "<ORGANISATION>"}),
        "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "<TELEFON>"}),
        "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "<EMAIL>"}),
    }
    result = anonymizer.anonymize(text=cleaned, analyzer_results=results, operators=operators)
    return result.text


def main():
    if len(sys.argv) != 2:
        print("Nutzung: python pipeline.py <pfad_zur_datei.pdf>")
        sys.exit(1)

    pdf_path = Path(sys.argv[1])
    if not pdf_path.exists():
        print(f"Nicht gefunden: {pdf_path}")
        sys.exit(1)

    work_dir = Path("output") / pdf_path.stem
    work_dir.mkdir(parents=True, exist_ok=True)

    merged_text = convert_pdf(pdf_path, work_dir)
    (work_dir / "roh.md").write_text(merged_text, encoding="utf-8")

    anonymized_text = anonymize(merged_text)
    out_path = work_dir / "anonymisiert.md"
    out_path.write_text(anonymized_text, encoding="utf-8")

    print(f"\nFertig. Anonymisiertes Ergebnis: {out_path}")
    print("Bitte manuell gegenlesen, bevor du es weiterverwendest.")


if __name__ == "__main__":
    main()
