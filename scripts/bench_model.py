"""Đo một model sinh: tốc độ, độ tuân schema, và có bịa nguồn không.

Dùng để chốt ADR-002 bằng số đo thay vì cảm giác. Chạy:

    docker compose up -d db
    uv run python -m scripts.bench_model                       # mặc định: Ollama local
    uv run python -m scripts.bench_model qwen2.5:7b-instruct   # chỉ định model

Chunk lấy trực tiếp từ bảng doc_chunks, trong phạm vi quyền của một role cụ thể —
tức đúng dữ liệu và đúng giới hạn mà hệ thống thật sẽ dùng.

Ba số đo, và mỗi số trả lời một câu hỏi khác nhau:

* **tokens/giây** — một vòng eval 40 câu mất bao lâu, có chạy lại được nhiều lần không.
* **tuân schema** — bao nhiêu lần trả về JSON đúng hình dạng ngay lần đầu.
* **bịa nguồn** — bao nhiêu lần citation trỏ tới chunk không có trong context.

Script này KHÔNG đo chất lượng câu trả lời. Việc đó cần ground truth, và đó là D2.
"""

import json
import pathlib
import sys
import time
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError, model_validator

from src.config import get_settings
from src.db import fetch_all
from src.scope import visible_access_levels

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
DEFAULT_MODEL = "gemini-3.6-flash"

# Timeout cho mỗi request. Model local sinh chậm hơn API nhiều, nên con số này lớn —
# nhưng vẫn phải có, theo đúng ADR-005: thiếu timeout thì lỗi thành treo.
REQUEST_TIMEOUT = 180.0

SYSTEM = (
    "Ban la tro ly noi bo cua cong ty. Chi tra loi dua tren cac doan tai lieu duoc "
    "cung cap duoi day. Moi khang dinh phai kem chunk_id lam nguon. Neu cac doan "
    "khong chua dap an, tra ve abstained=true va citations rong.\n"
    'Chi tra ve DUNG MOT JSON object dang: {"answer": "...", '
    '"citations": [{"chunk_id": "...", "quote": "..."}], "abstained": false}'
)

# Câu hỏi viết có dấu, vì người dùng thật gõ có dấu. Corpus hiện tại không dấu — đây
# cũng là một phép thử nhỏ xem model có bắc cầu được qua khác biệt đó.
QUESTIONS: tuple[tuple[str, str], ...] = (
    ("finance", "Khoản chi 80 triệu đồng thì ai duyệt?"),
    ("finance", "Trưởng phòng được phê duyệt tối đa bao nhiêu?"),
    ("hr", "Nhân viên được bao nhiêu ngày phép một năm?"),
    ("engineering", "Release cần qua những bước nào trước khi lên production?"),
    # Câu này corpus KHÔNG có đáp án: model phải abstain, không được bịa.
    ("hr", "Công ty có chính sách xe đưa rước nhân viên không?"),
)


class Citation(BaseModel):
    chunk_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class Answer(BaseModel):
    answer: str = Field(min_length=1)
    citations: list[Citation]
    abstained: bool

    @model_validator(mode="after")
    def abstain_means_no_citation(self) -> "Answer":
        if self.abstained and self.citations:
            raise ValueError("abstained=true nhưng vẫn có citations")
        return self


def load_scope_chunks(department: str, role: str, limit: int = 4) -> list[dict[str, Any]]:
    """Lấy chunk trong phạm vi quyền của role, giống đường đi của hệ thống thật."""
    return fetch_all(
        """
        SELECT doc_id, chunk_index, chunk_text
        FROM doc_chunks
        WHERE department = %(dept)s
          AND access_level = ANY(%(levels)s)
        ORDER BY doc_id, chunk_index
        LIMIT %(limit)s
        """,
        {"dept": department, "levels": visible_access_levels(role), "limit": limit},
    )


def build_prompt(question: str, chunks: list[dict[str, Any]]) -> tuple[str, set[str]]:
    lines = []
    ids: set[str] = set()
    for c in chunks:
        cid = f"{c['doc_id']}#{c['chunk_index']}"
        ids.add(cid)
        lines.append(f"[{cid}] {c['chunk_text']}")
    return "Cac doan tai lieu:\n" + "\n".join(lines) + f"\n\nCau hoi: {question}", ids


def ask_ollama(model: str, prompt: str) -> dict[str, Any]:
    """Gọi Ollama và trả về cả nội dung lẫn số đo tốc độ do server báo."""
    response = httpx.post(
        OLLAMA_URL,
        timeout=REQUEST_TIMEOUT,
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            # format=json bật JSON mode của Ollama: nó ép đầu ra là JSON hợp lệ,
            # nhưng KHÔNG ép đúng schema — thiếu trường vẫn là JSON hợp lệ.
            "format": "json",
            "options": {"temperature": 0.1, "num_predict": 400},
        },
    )
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    return payload


GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def ask_gemini(model: str, prompt: str) -> dict[str, Any]:
    """Gọi Gemini và trả về payload đã chuẩn hóa giống ask_ollama.

    responseMimeType=application/json là JSON mode: ép đầu ra là JSON hợp lệ, nhưng
    KHÔNG ép đúng schema — thiếu trường vẫn là JSON hợp lệ. Cố ý không dùng
    responseSchema ở đây, vì mục đích là đo xem model tự tuân schema tới đâu.
    """
    key = get_settings().llm_api_key
    if not key:
        raise RuntimeError("LLM_API_KEY rỗng — kiểm .env")

    started = time.perf_counter()
    response = httpx.post(
        GEMINI_URL.format(model=model),
        # Key đi trong header, KHÔNG đi trong query string: httpx đưa URL vào thông báo
        # lỗi, nên key trong query sẽ lọt vào log và stack trace.
        headers={"x-goog-api-key": key},
        timeout=REQUEST_TIMEOUT,
        json={
            "systemInstruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.1,
                # Gemini 3.x bật "thinking" mặc định, và thinking token TRỪ VÀO
                # maxOutputTokens. Đặt 400 thì thinking ăn hết và response rỗng với
                # finishReason=MAX_TOKENS. 1200 để có chỗ cho cả suy nghĩ lẫn câu trả
                # lời. Đây đúng là bài học reserve_output, chỉ khác là phần dự trữ còn
                # phải nuôi một người tiêu thụ vô hình.
                "maxOutputTokens": 1200,
            },
        },
    )
    response.raise_for_status()
    body = response.json()
    elapsed = time.perf_counter() - started

    candidate = body["candidates"][0]
    text = "".join(p.get("text", "") for p in candidate["content"]["parts"])
    usage = body.get("usageMetadata", {})
    out_tokens = usage.get("candidatesTokenCount", 0) or 0
    return {
        "message": {"content": text},
        "prompt_eval_count": usage.get("promptTokenCount"),
        "eval_count": out_tokens,
        "thinking_tokens": usage.get("thoughtsTokenCount", 0),
        # Gemini không báo thời gian sinh riêng, nên suy từ thời gian thực của request.
        "eval_duration": int(elapsed * 1e9),
        "finish_reason": candidate.get("finishReason"),
    }


def ask(model: str, prompt: str) -> dict[str, Any]:
    """Chọn provider theo tên model. Interface giống nhau nên phần đo không đổi."""
    return ask_gemini(model, prompt) if model.startswith("gemini") else ask_ollama(model, prompt)


def main(argv: list[str]) -> int:
    model = argv[1] if len(argv) > 1 else DEFAULT_MODEL
    print(f"model: {model}\n")

    results: list[dict[str, Any]] = []
    for department, question in QUESTIONS:
        chunks = load_scope_chunks(department, role="manager")
        prompt, allowed_ids = build_prompt(question, chunks)

        started = time.perf_counter()
        try:
            payload = ask(model, prompt)
        except (httpx.HTTPError, RuntimeError, KeyError) as exc:
            print(f"[LỖI] {question[:45]} -> {type(exc).__name__}: {exc}")
            results.append({"question": question, "error": str(exc)})
            continue
        wall = time.perf_counter() - started

        raw = payload["message"]["content"]
        # Ollama báo thời gian bằng nanosecond.
        out_tokens = payload.get("eval_count", 0)
        out_ns = payload.get("eval_duration", 1)
        tok_per_s = out_tokens / (out_ns / 1e9) if out_ns else 0.0

        schema_ok, schema_err, grounding = True, None, []
        if not raw.strip():
            # Xảy ra khi thinking ăn hết maxOutputTokens: finishReason=MAX_TOKENS và
            # content rỗng. Gọi đúng tên thay vì để nó thành JSONDecodeError.
            schema_ok = False
            schema_err = f"response rong (finish={payload.get('finish_reason')})"
        try:
            answer = Answer.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValidationError) as exc:
            schema_ok, schema_err = False, schema_err or type(exc).__name__
        else:
            grounding = [c.chunk_id for c in answer.citations if c.chunk_id not in allowed_ids]

        results.append(
            {
                "department": department,
                "question": question,
                "wall_s": round(wall, 2),
                "prompt_tokens": payload.get("prompt_eval_count"),
                "output_tokens": out_tokens,
                "thinking_tokens": payload.get("thinking_tokens", 0),
                "finish_reason": payload.get("finish_reason"),
                "tok_per_s": round(tok_per_s, 1),
                "schema_ok": schema_ok,
                "schema_error": schema_err,
                "fabricated_citations": grounding,
                "raw": raw[:300],
            }
        )

        mark = "OK " if schema_ok and not grounding else "XX "
        print(
            f"{mark}{question[:42]:44s} {wall:5.1f}s  {tok_per_s:5.1f} tok/s  "
            f"schema={'dat' if schema_ok else schema_err}  nguon_bia={grounding or '-'}"
        )

    ok = [r for r in results if r.get("schema_ok")]
    speeds = [r["tok_per_s"] for r in ok if r.get("tok_per_s")]
    summary = {
        "model": model,
        "so_cau": len(QUESTIONS),
        "schema_dat": f"{len(ok)}/{len(QUESTIONS)}",
        "co_bia_nguon": sum(1 for r in results if r.get("fabricated_citations")),
        "tok_per_s_trung_binh": round(sum(speeds) / len(speeds), 1) if speeds else None,
        "uoc_tinh_40_cau_phut": (
            round(sum(r["wall_s"] for r in ok) / len(ok) * 40 / 60, 1) if ok else None
        ),
    }
    print("\n" + json.dumps(summary, indent=2, ensure_ascii=False))

    # Ghi ra file thay vì chỉ in: console Windows là cp1252 nên tiếng Việt hỏng
    # khi đi qua pipe, và số đo dùng để chốt ADR thì phải lưu lại được.
    out_dir = pathlib.Path("evidence/bench")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{model.replace(chr(58), chr(95))}.json"
    report = {"summary": summary, "results": results}
    out_file.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"da ghi: {out_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
