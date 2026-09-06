"""
Batch-Pipeline: verarbeitet ALLE PDFs in einem Ordner in einem einzigen Programmlauf.

WICHTIG (Stand 28.08.2026): Der OCR-Schritt (PaddleOCR-VL) läuft pro PDF in
einem eigenen Subprozess (ocr_worker.py), nicht mehr im Hauptprozess. Grund:
bekannter Paddle-Bug — eine PaddleOCRVL-Instanz verträgt nur einen einzigen
.predict()-Aufruf zuverlässig, der zweite crasht deterministisch mit
"int(Tensor) is not supported in static graph mode" und korrumpiert den
GPU-Zustand des Prozesses. Presidio + GLiNER sind von diesem Bug NICHT
betroffen und werden weiterhin nur einmal geladen.

Kostenpunkt dieser Änderung: PaddleOCR-VL wird jetzt pro PDF neu geladen
(vorher: einmal für den ganzen Batch). Bei vielen PDFs summiert sich das.

Nutzung:
    python batch_pipeline.py <ordner_mit_pdfs>

Ergebnis pro PDF:
    output/<dateiname>/roh.md
    output/<dateiname>/anonymisiert.md
"""

import re
import subprocess
import sys
import time
from pathlib import Path

from presidio_analyzer import AnalyzerEngine, PatternRecognizer
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.predefined_recognizers import GLiNERRecognizer
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

WORKER_SCRIPT = Path(__file__).parent / "ocr_worker.py"


def clean_markdown(text: str) -> str:
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    text = re.sub(r'<img[^>]*>', '', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n\n', text)
    return text.strip()


def convert_pdf_via_subprocess(pdf_path: Path, work_dir: Path) -> str:
    """Startet ocr_worker.py als frischen Prozess fuer GENAU diese eine PDF.
    So trifft der Paddle-Bug (2. predict()-Aufruf crasht) nie zu, weil jeder
    Prozess nur einen einzigen predict()-Aufruf macht."""

    result = subprocess.run(
        [sys.executable, str(WORKER_SCRIPT), str(pdf_path), str(work_dir)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"OCR-Worker fehlgeschlagen (Exitcode {result.returncode}): "
            f"{result.stderr.strip() or '(keine stderr-Ausgabe)'}"
        )

    roh_path = work_dir / "roh.md"
    if not roh_path.exists():
        raise RuntimeError("OCR-Worker lief durch, aber roh.md wurde nicht geschrieben.")
    return roh_path.read_text(encoding="utf-8")


def build_analyzer_and_anonymizer():
    """Baut den Presidio-Analyzer (deutsches spaCy fuer Tokenisierung + offizieller
    GLiNER-Recognizer fuer die Haupterkennung + Deny-List fuer bekannte
    Firmenkuerzel, die GLiNER ohne viel Kontext leicht uebersieht) und den
    Anonymizer."""

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

    print(f"Gefunden: {len(pdfs)} PDF(s). Lade Presidio/GLiNER (einmalig) ...")
    print("Hinweis: PaddleOCR-VL läuft pro PDF in einem eigenen Prozess (Bug-Workaround).")
    load_start = time.time()

    analyzer, anonymizer = build_analyzer_and_anonymizer()

    print(f"Presidio/GLiNER geladen in {time.time() - load_start:.1f}s.\n")

    for i, pdf_path in enumerate(pdfs, 1):
        print(f"[{i}/{len(pdfs)}] {pdf_path.name}")
        t0 = time.time()

        work_dir = Path("output") / pdf_path.stem
        work_dir.mkdir(parents=True, exist_ok=True)

        try:
            merged_text = convert_pdf_via_subprocess(pdf_path, work_dir)
            ocr_done = time.time()

            anonymized_text, n_hits = anonymize(merged_text, analyzer, anonymizer)
            out_path = work_dir / "anonymisiert.md"
            out_path.write_text(anonymized_text, encoding="utf-8")

            print(
                f"   OK - {n_hits} Treffer, OCR {ocr_done - t0:.1f}s / "
                f"gesamt {time.time() - t0:.1f}s -> {out_path}"
            )
        except Exception as e:
            print(f"   FEHLER bei {pdf_path.name}: {e}")

    print("\nAlle Dateien verarbeitet. Bitte jede anonymisiert.md manuell gegenlesen.")


if __name__ == "__main__":
    main()
