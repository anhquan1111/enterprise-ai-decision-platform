"""CER/WER — do chat luong trich xuat OCR bang khoang cach chinh sua (Levenshtein),
doi chieu voi ground truth. Viet tay, khong them dependency moi (jiwer/python-Levenshtein)
cho hai ham nho, don gian nay.

Xem vault D:/Documents/AI/Update/OCR_Ingestion/2. Tich_Hop_Chunking_Va_Danh_Gia.md
muc 4 cho cong thuc va ly do vi sao BAT BUOC do bang ground truth thay vi tin cam
giac "doc co ve dung" — Gemini vision khong co confidence score nhu OCR truyen thong.
"""


def _levenshtein(a: list[str], b: list[str]) -> int:
    """Số phép sửa tối thiểu (thêm/xoá/thay) để biến ``a`` thành ``b``."""
    if not a:
        return len(b)
    if not b:
        return len(a)

    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            current[j] = min(
                previous[j] + 1,  # xoá
                current[j - 1] + 1,  # thêm
                previous[j - 1] + cost,  # thay (hoặc giữ nguyên nếu ca == cb)
            )
        previous = current
    return previous[-1]


def cer(hypothesis: str, reference: str) -> float:
    """Character Error Rate: tỷ lệ lỗi theo ký tự so với độ dài văn bản đúng.

    0.0 = khớp hoàn toàn. Không chặn trên ở 1.0 — hypothesis dài hơn reference rất
    nhiều vẫn cho ra một số hợp lệ, phản ánh đúng mức sai lệch.
    """
    if not reference:
        raise ValueError("reference rỗng — không có mẫu số để tính CER")
    distance = _levenshtein(list(hypothesis), list(reference))
    return distance / len(reference)


def wer(hypothesis: str, reference: str) -> float:
    """Word Error Rate: giống CER nhưng đơn vị là từ (tách theo khoảng trắng)."""
    ref_words = reference.split()
    if not ref_words:
        raise ValueError("reference rỗng — không có mẫu số để tính WER")
    distance = _levenshtein(hypothesis.split(), ref_words)
    return distance / len(ref_words)
