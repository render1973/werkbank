"""
Batch-Pipeline: verarbeitet ALLE PDFs in einem Ordner in einem einzigen Programmlauf.
Die Modelle (PaddleOCR-VL, GLiNER) werden nur EINMAL geladen, nicht pro Datei.

Nutzung:
    python batch_pipeline.py <ordner_mit_pdfs>

Ergebnis pro PDF:
    output/<dateiname>/roh.md
    output/<dateiname>/anonymisiert.md
"""

import re
import sys
import time
from pathlib import Path

from paddleocr import PaddleOCRVL
from presidio_analyzer import AnalyzerEngine, PatternRecognizer
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.predefined_recognizers import GLiNERRecognizer
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig


def clean_markdown(text: str) -> str:
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    text = re.sub(r'<img[^>]*>', '', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n\n', text)
    return text.strip()


def convert_pdf(pdf_path: Path, work_dir: Path, ocr_pipeline: PaddleOCRVL) -> str:
    output = ocr_pipeline.predict(str(pdf_path))
    page_dir = work_dir / "pages"
    page_dir.mkdir(parents=True, exist_ok=True)
    for res in output:
        res.save_to_markdown(save_path=str(page_dir))

    md_files = sorted(
        page_dir.glob(f"{pdf_path.stem}_*.md"),
        key=lambda f: int(f.stem.rsplit("_", 1)[-1]),
    )
    if not md_files:
        raise RuntimeError("Keine Markdown-Seiten erzeugt.")
    return "\n\n---\n\n".join(f.read_text(encoding="utf-8") for f in md_files)


def build_analyzer_and_anonymizer():
    """Baut den Presidio-Analyzer (deutsches spaCy fuer Tokenisierung + offizieller
    GLiNER-Recognizer fuer die Haupterkennung + Deny-Lists fuer bekannte
    Firmenkuerzel/Ortsnamen, die GLiNER ohne viel Kontext leicht uebersieht,
    z.B. wenn sie isoliert in Titeln/Kopfzeilen stehen) und den Anonymizer."""

    nlp_engine = NlpEngineProvider(
        nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "de", "model_name": "de_core_news_lg"}],
        }
    ).create_engine()

    analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["de"])

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
        supported_language="de",
    )
    analyzer.registry.add_recognizer(gliner_recognizer)
    analyzer.registry.remove_recognizer("SpacyRecognizer")

    # Bekannte Firmenkuerzel, die zusaetzlich zur GLiNER-Erkennung IMMER
    # als ORGANIZATION gelten sollen - hier bei Bedarf weitere ergaenzen.
    known_organizations = ["JLL", "PFM"]
    org_deny_list_recognizer = PatternRecognizer(
        supported_entity="ORGANIZATION",
        deny_list=known_organizations,
        supported_language="de",
    )
    analyzer.registry.add_recognizer(org_deny_list_recognizer)

    # Bekannte Ortsnamen, die GLiNER isoliert (z.B. in Projekttiteln oder
    # Kopfzeilen ohne umgebenden Satzkontext) leicht uebersieht - analog zur
    # Firmenkuerzel-Deny-List oben. Hier eigene wiederkehrende Projektorte
    # ergaenzen, z.B. known_locations = ["Oberengstringen"]
    known_locations = []
    if known_locations:
        location_deny_list_recognizer = PatternRecognizer(
            supported_entity="LOCATION",
            deny_list=known_locations,
            supported_language="de",
        )
        analyzer.registry.add_recognizer(location_deny_list_recognizer)

    anonymizer = AnonymizerEngine()
    return analyzer, anonymizer


def anonymize(text: str, analyzer: AnalyzerEngine, anonymizer: AnonymizerEngine) -> tuple[str, int]:
    cleaned = clean_markdown(text)
    results = analyzer.analyze(text=cleaned, language="de")

    operators = {
        "PERSON": OperatorConfig("replace", {"new_value": "<PERSON>"}),
        "ADDRESS": OperatorConfig("replace", {"new_value": "<ADRESSE>"}),
        "LOCATION": OperatorConfig("replace", {"new_value": "<ORT>"}),
        "ORGANIZATION": OperatorConfig("replace", {"new_value": "<ORGANISATION>"}),
        "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "<TELEFON>"}),
        "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "<EMAIL>"}),
    }
    result = anonymizer.anonymize(text=cleaned, analyzer_results=results, operators=operators)
    return result.text, len(results)


def main():
    if len(sys.argv) != 2:
        print("Nutzung: python batch_pipeline.py <ordner_mit_pdfs>")
        sys.exit(1)

    input_dir = Path(sys.argv[1])
    if not input_dir.is_dir():
        print(f"Kein Ordner: {input_dir}")
        sys.exit(1)

    pdfs = sorted(input_dir.glob("*.pdf"))
    if not pdfs:
        print(f"Keine PDFs in {input_dir} gefunden.")
        sys.exit(1)

    print(f"Gefunden: {len(pdfs)} PDF(s). Lade Modelle (einmalig) ...")
    load_start = time.time()

    ocr_pipeline = PaddleOCRVL()
    analyzer, anonymizer = build_analyzer_and_anonymizer()

    print(f"Modelle geladen in {time.time() - load_start:.1f}s.\n")

    for i, pdf_path in enumerate(pdfs, 1):
        print(f"[{i}/{len(pdfs)}] {pdf_path.name}")
        t0 = time.time()

        work_dir = Path("output") / pdf_path.stem
        work_dir.mkdir(parents=True, exist_ok=True)

        try:
            merged_text = convert_pdf(pdf_path, work_dir, ocr_pipeline)
            (work_dir / "roh.md").write_text(merged_text, encoding="utf-8")

            anonymized_text, n_hits = anonymize(merged_text, analyzer, anonymizer)
            out_path = work_dir / "anonymisiert.md"
            out_path.write_text(anonymized_text, encoding="utf-8")

            print(f"   OK - {n_hits} Treffer, {time.time() - t0:.1f}s -> {out_path}")
        except Exception as e:
            print(f"   FEHLER bei {pdf_path.name}: {e}")

    print("\nAlle Dateien verarbeitet. Bitte jede anonymisiert.md manuell gegenlesen.")


if __name__ == "__main__":
    main()
