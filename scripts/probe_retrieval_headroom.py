"""D3: kiem tra truoc khi quyet dinh co lam hybrid retrieval hay khong.

Khong sua eval/dev.jsonl (so baseline 25 cau da bao o D2 phai giu nguyen, xem AGENTS.md
muc 4). Day la mot probe dung MOT LAN, khong phai bo eval chinh thuc: 5 cau hoi moi,
paraphrase manh (tranh chia se tu vung voi gold chunk) de kiem xem dense retrieval con
lo hong nao khong, truoc khi ket luan co dang lam hybrid o D3 hay khong.

    uv run python -m scripts.probe_retrieval_headroom
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.retrieval import retrieve

EVIDENCE = Path(__file__).parent.parent / "evidence" / "hybrid_headroom_probe.json"


@dataclass(frozen=True)
class Probe:
    question: str
    role: str
    gold_chunk_id: str
    existing_similar: str


@dataclass
class ProbeResult:
    probe: Probe
    top_ids: list[str] = field(default_factory=list)
    rank_of_gold: int | None = None


# Moi cau paraphrase manh so voi cau da co trong eval/dev.jsonl cho cung gold chunk,
# tranh tu vung chung nhat co the - dung de kiem hoc lech tu vung con ton dong hay khong.
PROBES = [
    Probe(
        question=(
            "Khi mot phien ban phan mem gap su co ngay sau khi phat hanh, "
            "quy trinh khac phuc la gi?"
        ),
        role="employee",
        gold_chunk_id="ENG-007#1",
        existing_similar="Q09/F01_seen_at_d2 (dung chung 'release', 'loi')",
    ),
    Probe(
        question=(
            "Truoc khi mot nguoi duoc nhan vao lam, "
            "ho can trai qua bao nhieu buoc danh gia chuyen mon?"
        ),
        role="manager",
        gold_chunk_id="HR-002#1",
        existing_similar="Q13/F03_seen_at_d2 (dung chung 'vong phong van ky thuat')",
    ),
    Probe(
        question=(
            "So lieu doanh thu khi chua duoc xac nhan chinh thuc "
            "thi co the chia se voi doi tac ben ngoai khong?"
        ),
        role="manager",
        gold_chunk_id="FIN-020#1",
        existing_similar="Q07 (dung chung 'tam tinh')",
    ),
    Probe(
        question=(
            "Cong ty co dinh dua san pham ra kinh doanh o quoc gia khac trong tuong lai gan khong?"
        ),
        role="executive",
        gold_chunk_id="SAL-011#0",
        existing_similar="Q16 (dung chung 'ke hoach mo rong thi truong 2027')",
    ),
    Probe(
        question=(
            "Khi mot nhan su ngung tham gia mot cong viec, "
            "ho con duoc phep xem thong tin cua khach hang lien quan khong?"
        ),
        role="manager",
        gold_chunk_id="ENG-012#0",
        existing_similar="Q10/Q11 (dung chung 'quyen truy cap du lieu khach hang')",
    ),
]


def main() -> None:
    results: list[ProbeResult] = []
    for probe in PROBES:
        chunks = retrieve(probe.question, role=probe.role, k=5)
        top_ids = [c.chunk_id for c in chunks]
        rank = top_ids.index(probe.gold_chunk_id) + 1 if probe.gold_chunk_id in top_ids else None
        results.append(ProbeResult(probe=probe, top_ids=top_ids, rank_of_gold=rank))
        print(f"{probe.gold_chunk_id:14} rank={rank}  top1={top_ids[0] if top_ids else None}")

    n_answerable = len(results)
    n_recall_at_3 = sum(1 for r in results if r.rank_of_gold is not None and r.rank_of_gold <= 3)
    summary = {
        "n_probes": n_answerable,
        "recall_at_3": f"{n_recall_at_3}/{n_answerable}",
        "results": [asdict(r) for r in results],
    }
    print(json.dumps({"recall_at_3": summary["recall_at_3"]}, ensure_ascii=False))

    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"da ghi: {EVIDENCE}")


if __name__ == "__main__":
    main()
