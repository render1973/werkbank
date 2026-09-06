"""
OCR-Worker: konvertiert GENAU EINE PDF zu Markdown und beendet sich danach.

Grund für die Isolation als eigener Prozess: PaddleOCR-VL hat einen bekannten
Bug (bestätigt u.a. im Projekt paddle-vlm-editor) — eine PaddleOCRVL-Instanz
verträgt nur EINEN .predict()-Aufruf zuverlässig. Der zweite Aufruf crasht
deterministisch mit "int(Tensor) is not supported in static graph mode" und
korrumpiert danach den globalen GPU-Zustand des Prozesses (nicht mehr reparierbar,
ohne den Prozess neu zu starten). Darum: pro PDF ein frischer Python-Prozess.

Aufruf:
    python ocr_worker.py <pdf_pfad> <work_dir>

Schreibt <work_dir>/roh.md und beendet sich mit Exitcode 0 (Erfolg) oder 1 (Fehler).
"""

import sys
from pathlib import Path

from paddleocr import PaddleOCRVL


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


def main():
    if len(sys.argv) != 3:
        print("Nutzung: python ocr_worker.py <pdf_pfad> <work_dir>", file=sys.stderr)
        sys.exit(1)

    pdf_path = Path(sys.argv[1])
    work_dir = Path(sys.argv[2])
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        ocr_pipeline = PaddleOCRVL()
        merged_text = convert_pdf(pdf_path, work_dir, ocr_pipeline)
        (work_dir / "roh.md").write_text(merged_text, encoding="utf-8")
        sys.exit(0)
    except Exception as e:
        print(f"OCR-Worker-Fehler bei {pdf_path.name}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
