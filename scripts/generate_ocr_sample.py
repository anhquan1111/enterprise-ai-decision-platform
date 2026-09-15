"""Dung mot PDF mo phong ban scan, kem ground truth biet truoc, de do CER/WER that
cua src/ocr.py — khong dung tai lieu noi bo that cua cong ty nao (AGENTS.md muc 4).

Van ban nguon lay tu chinh cac chunk da co trong data/documents.csv (du lieu tong
hop cua du an), ghep thanh mot "trang chinh sach" hop ly, roi render thanh anh co
nhieu/nghieng nhe truoc khi luu thanh PDF — mo phong loi khong hoan hao that cua
mot ban scan, khong phai van ban so hoa sach se.

    uv sync --extra dev   # can pillow, xem pyproject.toml
    uv run python -m scripts.generate_ocr_sample
"""

import random
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = Path(__file__).parent.parent / "data" / "ocr_samples"
FONT_PATH = "C:/Windows/Fonts/arial.ttf"
PAGE_SIZE = (1240, 1754)  # ~A4 o 150 dpi

# Lay nguyen van tu data/documents.csv (HR-001, FIN-014) - khong bia noi dung moi,
# de ground truth phan anh dung du lieu tong hop da co cua du an.
GROUND_TRUTH = """CONG TY TNHH VI DU - SO TAY CHINH SACH NOI BO

Quy dinh nghi phep

Nhan vien chinh thuc duoc 12 ngay phep co luong moi nam. Phep duoc tinh theo
nam duong lich. Ngay phep khong dung het trong nam khong duoc chuyen sang nam
sau va khong duoc quy doi thanh tien.

Han muc phe duyet chi

Nhan vien duoc de xuat chi toi 5 trieu dong cho chi phi van hanh thong thuong.
Truong phong phe duyet de xuat chi toi 50 trieu dong trong pham vi ngan sach
phong. Khoan chi tren 50 trieu dong phai do Giam doc phe duyet va co bien ban
kem theo."""


def render_scanned_pdf(text: str, *, out_path: Path, seed: int = 7) -> None:
    random.seed(seed)
    image = Image.new("L", PAGE_SIZE, color=255)
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(FONT_PATH, size=28)

    margin = 90
    y = margin
    for paragraph in text.split("\n\n"):
        for line in textwrap.wrap(paragraph, width=64) or [""]:
            draw.text((margin, y), line, font=font, fill=0)
            y += 40
        y += 24  # khoang cach giua doan

    # Mo phong loi khong hoan hao cua mot ban scan that: nhieu ngau nhien + nghieng nhe.
    pixels = image.load()
    assert pixels is not None
    for _ in range(int(PAGE_SIZE[0] * PAGE_SIZE[1] * 0.01)):
        x = random.randrange(PAGE_SIZE[0])
        py = random.randrange(PAGE_SIZE[1])
        pixels[x, py] = random.choice([0, 80, 180, 255])
    image = image.rotate(1.2, resample=Image.Resampling.BICUBIC, fillcolor=255)

    image.convert("RGB").save(out_path, "PDF")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = OUT_DIR / "policy_scan_sample.pdf"
    truth_path = OUT_DIR / "policy_scan_sample.ground_truth.txt"

    render_scanned_pdf(GROUND_TRUTH, out_path=pdf_path)
    truth_path.write_text(GROUND_TRUTH, encoding="utf-8")

    print(f"da ghi: {pdf_path}")
    print(f"da ghi: {truth_path}")


if __name__ == "__main__":
    main()
