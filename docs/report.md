# Evaluation report

Numbers here are appended per layer, not rewritten. Each block names the model, the
date, and the exact command to reproduce it. This file grows through D2 → D5; it is
not a final report until D5 says so.

## D2 — dense retrieval + structured output, baseline on dev

**Measured:** 13–14/09/2026. **Models:** `gemini-3.1-flash-lite` (generation),
`gemini-embedding-001` at 384 dimensions (embeddings), both pinned in `.env`.
**Reproduce:** `uv run python -m scripts.run_eval --report` (reads results already
on disk; add `uv run python -m scripts.run_eval` first to regenerate them — this
calls the real API).

### Corpus

16 chunks, 11 documents, 4 departments (`hr`, `finance`, `engineering`, `sales`), 3
access levels. Synthetic, written for this project — no real company documents. Two
chunks (`SAL-002`, effective through 2026-06-30) are deliberately superseded by a
later one (`SAL-009`, effective from 2026-07-01), so a question about "the current
discount rate" only resolves correctly if point-in-time filtering runs.

### Eval set

25 questions in `eval/dev.jsonl`, open and editable. `eval/final.jsonl` is
**empty by design** — see the note at the end of this section before assuming a
held-out set exists.

| | Count |
|---|---:|
| Total questions | 25 |
| Answerable (`should_abstain=false`) | 18 |
| Should abstain — access denied | 5 |
| Should abstain — no knowledge in corpus | 2 |

### Retrieval

| Metric | Result |
|---|---|
| recall@3 | 18/18 (100.0%) |
| recall@5 | 18/18 (100.0%) |
| recall@10 | 18/18 (100.0%) |
| MRR | 1.000 |

Recall is flat across k because the gold chunk ranked first for every answerable
question. **This is a small, synthetic corpus with clearly worded questions — it is
not evidence that dense retrieval always ranks first.** See "Not yet measured" below.

One retrieval comparison worth keeping: the equivalent question to *"what to do when
a release fails"* was used in the RAG_Evaluation teaching material (day 20) on a
different, smaller synthetic corpus, scored with a hand-written TF-IDF baseline. There
it ranked **5th** — the question describes the situation ("failure"), the answer chunk
describes the fix ("rollback"), and they share almost no vocabulary. The same kind of
question against this project's real corpus, using real Gemini embeddings, ranked
**1st** (cosine distance 0.208). That is the specific weakness dense embeddings are
expected to fix over lexical search, measured rather than assumed.

### Answer quality and error taxonomy

Eight categories, ported from RAG_Evaluation (day 20) into `src/eval_taxonomy.py`.

| Category | Count |
|---|---:|
| `correct` | 18 |
| `access_correct` (correctly refused — evidence existed above the asker's level) | 5 |
| `no_knowledge_correct` (correctly refused — corpus has no answer) | 2 |
| `access_violation`, `no_knowledge_hallucination`, `retrieval_error`, `generation_unnecessary_abstention`, `generation_fabricated_citation`, `generation_wrong_fact` | 0 each |

Zero in every failure category is a real result on this dataset, not a rounding of a
small mistake — but it should not be read as "the system is correct in general." It
is correct **on these 25 questions, on this corpus, at this model version, on this
date.** The two corrections below happened during measurement, not after; leaving
them in the record is part of reporting honestly, per this project's own convention.

**A rubric bug, caught before the full run finished.** One question's rubric required
the substring `"khong dung"` (no diacritics, matching the corpus's writing
convention). The model's real answer — *"không **được** dùng để báo cáo ra bên
ngoài"* — is fully correct, but does not contain that exact substring; it says
"không được dùng", not "không dùng". Fixed by widening the keyword list rather than
by declaring the model wrong.

**A diacritics bug, caught before any question ran.** `expected_answer_keywords` and
the corpus are written without Vietnamese diacritics, but Gemini answers with full,
correct diacritics — the right behaviour for a real user, and the wrong assumption for
a naive substring match. `khong duoc` is never a substring of `không được` at the byte
level. `src/eval_taxonomy.py` folds both sides (NFD decomposition, `đ`/`Đ` handled
separately since they are not decomposable diacritics) before comparing. Without this
fix, nearly every correct answer in this dataset would have been scored wrong.

### A process mistake, corrected in the record rather than hidden

`docs/architecture.md` states plainly: "Final report on held-out questions" is D5's
job, after hybrid retrieval (D3) and RBAC/audit (D4) exist. The system today is not
that system. `eval/final.jsonl` (5 questions) was scored anyway on 14/09 — a genuine
process slip, not a deliberate design choice.

Per the rule already recorded for this exact situation (day 19, section 4): a seen
held-out set is not deleted and not pretended unseen. It becomes dev data. The 5
questions were renamed `F0x_seen_at_d2` and folded into `eval/dev.jsonl`, which is why
the dev count above is 25 rather than 20. `eval/final.jsonl` is empty; D5 writes a
genuinely new held-out set once the system it is meant to evaluate actually exists.

### Not yet measured

- **Whether hybrid retrieval (the original D3 plan) has anything to improve.** Recall
  is already 100% at k=3 on this dev set. D3 should measure on harder or more numerous
  questions before assuming hybrid search is worth its added complexity — building it
  because it was planned, on a baseline that is already perfect, would not be a
  measured decision.
- **Cost and latency under load.** Every call so far has been sequential, one question
  at a time, with a fixed 1-second pause between them to stay polite to the free-tier
  rate limit. No number here describes concurrent behaviour.
- **The SQL business-data tool and agent routing.** Both are D3. `/ask` today only
  answers document questions; a revenue question is treated as "no evidence" and
  correctly abstains, which is accurate but not yet useful.
- **Audit logging and RBAC on the `/ask` response path.** The `audit_log` table exists
  (D1) but nothing writes to it yet — that is D4.

## D3 — hybrid retrieval, agent routing

Not started.

## D4 — RBAC completion, audit log, timeouts

Not started. Docs retrieval already enforces role-based scope and point-in-time
filtering (D1, D2); D4 adds the SQL tool's own scope rules and the audit trail.

## D5 — final report on a fresh held-out set

Not started. Requires a held-out set that has never been opened, drawn after D3 and
D4 land — not the eval/final.jsonl from D2, which is intentionally empty for exactly
this reason.
