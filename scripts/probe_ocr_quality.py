"""Do that hieu qua cua src/ocr.py (Gemini vision) tren PDF mo phong ban scan da tao
o scripts/generate_ocr_sample.py. Khong bia so - chay Gemini that mot lan, tinh
CER/WER doi chieu voi ground truth, ghi bang chung.

    uv run python -m scripts.generate_ocr_sample   # neu chua co file mau
    uv run python -m scripts.probe_ocr_quality
"""

import json
import time
from pathlib import Path

from src.ocr import extract_text
from src.ocr_metrics import cer, wer

DATA_DIR = Path(__file__).parent.parent / "data" / "ocr_samples"
EVIDENCE = Path(__file__).parent.parent / "evidence" / "ocr_quality_probe.json"


def main() -> None:
    pdf_path = DATA_DIR / "policy_scan_sample.pdf"
    truth_path = DATA_DIR / "policy_scan_sample.ground_truth.txt"
    if not pdf_path.exists() or not truth_path.exists():
        raise SystemExit(
            "Chua co file mau. Chay truoc: uv run python -m scripts.generate_ocr_sample"
        )

    ground_truth = truth_path.read_text(encoding="utf-8")
    file_bytes = pdf_path.read_bytes()

    start = time.perf_counter()
    extracted = extract_text(file_bytes, mime_type="application/pdf")
    elapsed_s = time.perf_counter() - start

    result = {
        "sample": pdf_path.name,
        "ground_truth_chars": len(ground_truth),
        "extracted_chars": len(extracted),
        "cer": round(cer(extracted, ground_truth), 4),
        "wer": round(wer(extracted, ground_truth), 4),
        "latency_s": round(elapsed_s, 2),
        "ground_truth": ground_truth,
        "extracted": extracted,
    }

    print(f"CER: {result['cer']:.2%}   WER: {result['wer']:.2%}   latency: {elapsed_s:.2f}s")
    print("--- ground truth ---")
    print(ground_truth)
    print("--- extracted ---")
    print(extracted)

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nda ghi: {EVIDENCE}")


if __name__ == "__main__":
    main()
