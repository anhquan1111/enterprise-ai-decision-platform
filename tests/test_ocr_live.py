"""Test end-to-thuc: goi Gemini vision that tren PDF mau mo phong ban scan, ton quota
that.

    uv run python -m scripts.generate_ocr_sample   # neu chua co file mau
    uv run pytest tests/test_ocr_live.py -v -m live_llm

Khong chay mac dinh. Nguong CER/WER o day RONG (khong doi hoi hoan hao tuyet doi) vi
Gemini co the doi cach xuong dong tu nhien — do khong phai loi noi dung, xem
docs/decisions.md ADR ve OCR va evidence/ocr_quality_probe.json cho ket qua that.
"""

from pathlib import Path

import pytest

from src.config import Settings, get_settings
from src.ocr import extract_text
from src.ocr_metrics import cer, wer

pytestmark = [pytest.mark.integration, pytest.mark.live_llm]

DATA_DIR = Path(__file__).parent.parent / "data" / "ocr_samples"


@pytest.fixture(autouse=True)
def use_real_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(Settings.model_config, "env_file", ".env")
    get_settings.cache_clear()


def test_extracts_scanned_policy_page_within_low_error_rate() -> None:
    pdf_path = DATA_DIR / "policy_scan_sample.pdf"
    truth_path = DATA_DIR / "policy_scan_sample.ground_truth.txt"
    if not pdf_path.exists():
        pytest.skip("Chua co file mau — chay scripts.generate_ocr_sample truoc")

    ground_truth = truth_path.read_text(encoding="utf-8")
    extracted = extract_text(pdf_path.read_bytes(), mime_type="application/pdf")

    # WER la chi so co y nghia hon o day: CER co the bi nhieu boi cach xuong dong
    # khac nhau giua ground truth (ngat dong cung do dai) va Gemini (tu nhien, khong
    # ngat dong) — khong phai loi noi dung. Xem ADR trong docs/decisions.md.
    assert wer(extracted, ground_truth) < 0.05
    assert cer(extracted, ground_truth) < 0.05
