# Evaluation report

Numbers here are appended per layer, not rewritten. Each block names the model, the
date, and the exact command to reproduce it. This file grows as each layer lands; it
is not a final report until the held-out section says so.

## Retrieval baseline — dense retrieval + structured output, baseline on dev

**Measured:** 13–14/09/2026, **re-measured 15/09/2026** after the corpus and
`eval/dev.jsonl` were rewritten from non-diacritic to full-diacritic Vietnamese
(see ADR-022) — same corpus content, same questions, correct spelling. Numbers
below are the 15/09 re-run; they came back identical to the original run, which
is itself evidence the diacritics change was a spelling fix, not a behavior
change. **Models:** `gemini-3.1-flash-lite` (generation),
`gemini-embedding-001` at 384 dimensions (embeddings), both pinned in `.env`.
**Reproduce:** `uv run python -m scripts.run_eval --report` (reads results already
on disk; add `uv run python -m scripts.run_eval` first to regenerate them — this
calls the real API). The pre-diacritics evidence is kept, not deleted, at
`evidence/eval_results_dev_pre_diacritics.jsonl` /
`evidence/eval_summary_dev_pre_diacritics.json`.

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
a release fails"* was tried earlier on a different, smaller synthetic corpus, scored
with a hand-written TF-IDF baseline. There
it ranked **5th** — the question describes the situation ("failure"), the answer chunk
describes the fix ("rollback"), and they share almost no vocabulary. The same kind of
question against this project's real corpus, using real Gemini embeddings, ranked
**1st** (cosine distance 0.208 on the original non-diacritic corpus; re-measured at
0.2033 on the 15/09 diacritic corpus via `src.retrieval.retrieve()` — same rank,
small distance shift from the re-embedding). That is the specific weakness dense
embeddings are expected to fix over lexical search, measured rather than assumed.

### Answer quality and error taxonomy

Eight categories, in `src/eval_taxonomy.py`.

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

**A diacritics bug, caught before any question ran.** At the time of the 13–14/09
run, `expected_answer_keywords` and the corpus were written without Vietnamese
diacritics, but Gemini answers with full, correct diacritics — the right behaviour
for a real user, and the wrong assumption for a naive substring match. `khong duoc`
is never a substring of `không được` at the byte level. `src/eval_taxonomy.py` folds
both sides (NFD decomposition, `đ`/`Đ` handled separately since they are not
decomposable diacritics) before comparing. Without this fix, nearly every correct
answer in that run would have been scored wrong.

*Historical note (15/09):* the corpus and `eval/dev.jsonl` were later rewritten to
full-diacritic Vietnamese (ADR-022), which removes the original cause of this bug —
but the fold in `src/eval_taxonomy.py` is kept regardless, since it costs nothing
and makes the comparison robust to any future non-diacritic input rather than
correct only by construction.

### A process mistake, corrected in the record rather than hidden

`docs/architecture.md` states plainly: "Final report on held-out questions" is the
job of the final report layer, after hybrid retrieval and RBAC/audit exist. The
system today is not that system. `eval/final.jsonl` (5 questions) was scored anyway
on 14/09 — a genuine process slip, not a deliberate design choice.

Per the rule already recorded for this exact situation: a seen held-out set is not
deleted and not pretended unseen. It becomes dev data. The 5 questions were renamed
`F0x_seen_early` (originally `F0x_seen_at_d2`; renamed once this project dropped
day-numbered labels project-wide — see the ADR on replacing D0-D5 with named phases)
and folded into `eval/dev.jsonl`, which is why the dev count above is 25 rather
than 20.
`eval/final.jsonl` is empty; the final report layer writes a genuinely new held-out
set once the system it is meant to evaluate actually exists.

### Not yet measured

- **Whether hybrid retrieval (the original plan) has anything to improve.** Recall
  is already 100% at k=3 on this dev set. Measure on harder or more numerous
  questions before assuming hybrid search is worth its added complexity — building it
  because it was planned, on a baseline that is already perfect, would not be a
  measured decision.
- **Cost and latency under load.** Every call so far has been sequential, one question
  at a time, with a fixed 1-second pause between them to stay polite to the free-tier
  rate limit. No number here describes concurrent behaviour.
- **The SQL business-data tool and agent routing.** `/ask` today only
  answers document questions; a revenue question is treated as "no evidence" and
  correctly abstains, which is accurate but not yet useful.
- **Audit logging and RBAC on the `/ask` response path.** The `audit_log` table exists
  but nothing writes to it yet.

## Agent routing — SQL + docs tools, RBAC for SQL, hybrid retrieval decision

**Measured:** 14/09/2026. **Model:** `gemini-3.1-flash-lite` for both the router
(`src/agent/router.py`) and docs generation, same pin as the retrieval baseline.

### Hybrid retrieval: measured, not built

The retrieval baseline section above asked this phase to check whether harder
questions expose a gap before assuming hybrid search is worth the added complexity.
`scripts/probe_retrieval_headroom.py`
ran 5 new questions against `retrieve()`, each a strong paraphrase of an existing dev
question for the same gold chunk, chosen to share as little vocabulary as possible
(e.g. gold `ENG-007#1` — the release-rollback chunk — re-asked as *"Khi mot phien ban
phan mem gap su co ngay sau khi phat hanh, quy trinh khac phuc la gi?"*, sharing neither
"release" nor "loi" with the original wording).

| Metric | Result |
|---|---|
| recall@3 on 5 hard paraphrases | **5/5 (100%)** — every gold chunk ranked 1st |

Raw results: [`evidence/hybrid_headroom_probe.json`](../evidence/hybrid_headroom_probe.json).
Decision and reasoning: ADR-011. `eval/dev.jsonl` was **not** modified for this check —
the probe is a separate, one-off script, so the 25-question baseline reported above
stays comparable.

### Agent: router + 2 tools, RBAC before execution

Architecture (ADR-013): a single Gemini call classifies each question into
`sql`, `docs`, or both — not a multi-step ReAct loop, since the tool set is fixed and
known in advance. RBAC is checked **after** the router proposes a plan but **before**
any tool executes, so a router fooled by the question text still cannot bypass access
control (ADR-012). SQL numbers are returned verbatim, never rephrased by an LLM.

| Behaviour | Result | Evidence |
|---|---|---|
| Router picks `docs` for a policy question | Correct, matches the retrieval-baseline pipeline exactly | `tests/test_ask_live.py::test_agent_routes_docs_question_to_docs_tool` (real Gemini) |
| Router picks `sql` for a revenue question, correct number returned | Correct — `"2026-01: 4,200,000,000 VND"` matches seed data exactly | Manual `/ask` run, 14/09/2026 |
| Employee tries to read another department's revenue via a crafted question | **Blocked** — `abstained=true`, `tool_used=none`, SQL query never executed | `tests/test_ask_live.py::test_agent_blocks_cross_department_revenue_even_if_router_complies` (real Gemini, real DB) — router proposed `department="finance"` exactly as asked; `can_query_department` rejected it anyway |
| Malformed router JSON | Retried once with the exact parse error, then succeeds; abstains (not a crash) if still malformed after retry | `tests/test_agent_router.py` |
| Transient network/DB error (`httpx`/`psycopg` connection errors) on a tool call | Retried up to `MAX_TOOL_RETRIES=2` with the exact same arguments, then propagated as a real error (502/503) — never silently treated as success | `tests/test_agent_loop.py::test_sql_tool_transient_error_is_retried_then_succeeds` |
| No data for a valid SQL query (wrong month) | Abstains — no data is a business outcome, not an error, not retried | `tests/test_agent_tools.py::test_no_data_raises_business_error_not_permission_error` |

96 unit + integration tests pass (`uv run pytest tests/ -v -m "not integration and not
live_llm"` → 81 passed; `-m integration` → 15 passed, including the two live-agent
tests above run against the real router and real database).

### Not yet measured

- **Combined sql+docs questions, systematically.** One manual test asked for both a
  revenue number and a discount policy in one sentence; the router chose only `sql`.
  This is a real, observed limitation — not yet covered by a dedicated eval set, so no
  rate is reported. Worth a small eval set before the final held-out report.
- **SQL query timeout.** `sql_tool` inherits the 5s *connection* timeout (ADR-005) but
  has no `statement_timeout` on the query itself. Not a realistic risk on this dataset
  size, but a real gap.
- **Cost/latency under concurrent load.** All calls so far are sequential, one request
  at a time.

## Auth & reliability — AuthN, audit log, Prometheus, connection pool, timeouts

**Measured:** 15/09/2026.

### A real vulnerability, found and closed

Agent routing shipped correct RBAC (`can_query_department`, `visible_access_levels`)
but no authentication — `AskRequest.role`/`department` were trusted as submitted. Measured
with a real `curl` request, no `Authorization` header, `user_id` set to an obviously
fake identity, `role` self-declared as `executive`:

```text
curl -X POST /ask -d '{"user_id":"khach_la_hoac_ke_gia_mao","role":"executive",
  "department":"finance","question":"Khoan chi tren 50 trieu dong thi ai duyet?"}'
-> 200 OK, returned FIN-014#2 (the executive-only approval-limit chunk)
```

Fixed with a real API key mechanism (ADR-015): `sql/06_auth.sql` adds
`employees.api_key_hash` (SHA-256, never plaintext); `scripts/issue_api_keys.py`
issued one real key per seeded employee, printed once; `src/auth.py::authenticate()`
verifies `Authorization: Bearer <key>` against the hash. **RBAC/the agent now use
the role/department looked up from the authenticated employee record — never the
request body.** Re-running the exact same attack after the fix:

```text
Same request, now WITH a real key for emp_001 (employee/sales), body still
self-declares role=executive -> 403, and run_agent() is provably never called
(tests/test_auth_integration.py asserts on this)

Same request with NO Authorization header at all -> 401
```

| Behaviour | Result | Evidence |
|---|---|---|
| Unauthenticated forged-role request | **Blocked**, 403 | Manual `curl`, 15/09/2026; automated in `tests/test_auth_integration.py::test_ask_end_to_end_blocks_forged_role_with_real_key_and_real_db` |
| Missing `Authorization` header | 401 | `tests/test_api.py::test_ask_returns_401_without_authorization_header` |
| Valid key, matching role | 200, correct answer | Manual `curl` with emp_001's real key, 15/09/2026 |
| Real DB round-trip (issue key → hash → authenticate) | Correct employee returned | `tests/test_auth_integration.py::test_authenticate_finds_employee_by_real_key_round_trip` |

### RBAC isolation — systematic, not sampled

`tests/test_rbac_isolation.py`: full matrix, not a handful of examples — 9
role×access_level combinations for docs, 48 role×department×department
combinations for SQL (3 roles × 4 × 4 departments), plus two real `retrieve()`
calls against the live corpus confirming no employee/manager ever receives a chunk
above their access level. 61/61 pass.

### Audit log and Prometheus — both real, not stubs

`audit_log` (a table that existed unused for a while) now receives one row per successful
`/ask` call — confirmed by a real request through a live server, then reading the
row back:

```text
{'request_id': ..., 'user_id': 'emp_001', 'role': 'employee', 'department': 'sales',
 'tool_used': 'docs', 'abstained': False, 'latency_ms': 5994,
 'llm_model': 'gemini-3.1-flash-lite', 'created_at': ...}
```

`/metrics` (Prometheus, `prometheus-client` was a dependency from the very start of the project, unused until now)
confirmed live after 3 real requests (401, 200, 403):

```text
ask_requests_total{status="401",tool_used="none"} 1.0
ask_requests_total{status="200",tool_used="docs"} 1.0
ask_requests_total{status="403",tool_used="none"} 1.0
ask_auth_failures_total{reason="invalid_credentials"} 1.0
ask_auth_failures_total{reason="role_mismatch"} 1.0
```

### Reliability fixes from a dedicated measurement pass

| Finding | Fix | Measured result |
|---|---|---|
| New DB connection per request: ~15ms/call vs ~1.7ms reused | `psycopg_pool.ConnectionPool` in `src/db.py` | ~5.5ms/call through the pool — real improvement (~3×), not the theoretical best (pool checkout has its own small cost) |
| No `statement_timeout` — only connection has a timeout (ADR-005) | `postgres_statement_timeout_ms=5000`, wired into `database_url` | `SHOW statement_timeout` confirms `5s` on a real connection |
| 2/3 concurrent `/ask` requests got `503` — root cause: retry backoff shared an identical schedule across requests, colliding on Gemini's rate limit again | Added `random.uniform(0, 0.5)` jitter to backoff in `generation.py`, `router.py`, `ocr.py` | Fix targets the exact mechanism identified; **not yet re-measured** under the same 3-concurrent-request scenario (ADR-016) |

### Not yet measured

- Retry jitter's actual effect on the concurrent-503 rate (ADR-016) — the original
  scenario has not been re-run post-fix.
- Connection pool behaviour under real concurrent load (only measured sequentially).
- AuthN is possession-based (API key), not JWT/OAuth2 — no expiry, no instant
  revocation. See ADR-015 for upgrade conditions.

## Final report on a fresh held-out set

**Measured:** 15/09/2026. **Model:** `gemini-3.1-flash-lite` (router + generation),
`gemini-embedding-001` at 384 dimensions — same pins as every earlier section,
unchanged for this report. **Reproduce:**
`uv run python -m scripts.run_held_out_eval --report` (reads
the sealed results on disk; the run itself cannot be repeated — see below).

### The held-out set

`eval/final.jsonl` was empty from early on by design (ADR-010): the original 5
held-out questions were scored too early and folded into dev instead. This report
writes a **genuinely new** 12-question set, only once agent routing and
auth/RBAC/audit both exist, so it can test the system it is actually meant to
evaluate — not just retrieval.

The 12 questions were chosen to close two specific gaps earlier sections of this
report already named as unmeasured, not to repeat what `eval/dev.jsonl` (25
questions, docs-only) already covers:

| Coverage | Questions | Why |
|---|---|---|
| SQL-only (own department, cross-department via executive, RBAC-blocked, provisional/non-final month) | H01–H04 | `eval/dev.jsonl` never exercises the SQL tool at all — it predates the agent |
| Combined SQL+docs in one question | H07, H08 | the agent-routing section flagged this as "observed but not in a dedicated eval set" |
| Docs, fresh RBAC combination not in dev | H05, H06 | new role×chunk-access-level pairs not seen in dev |
| No-knowledge abstain, and SQL "no data for this month" abstain | H09, H10 | two different abstain *reasons* that look identical to the caller but are different code paths |
| Docs, strong paraphrase (low vocabulary overlap with the source chunk) | H11, H12 | same style as ADR-011's hybrid-retrieval probe, applied to the full agent |

Every question was run through the **real, running `/ask` HTTP endpoint** — not
`run_agent()` called in-process — specifically so latency and token cost are measured
at the same boundary a real caller would hit, with real authentication
(`src/auth.py`) and a real `audit_log` row per request. Eight dedicated employee
records (`emp_101`–`emp_108`, one per role×department combination needed) were added
for this run so the eight *original* seeded employees' API keys — issued in an
earlier session and known only as a hash — never had to be touched or reissued
(`AGENTS.md` forbids re-running `issue_api_keys.py` in a way that could invalidate a
key already in use). The plaintext keys for the new eval-only employees live outside
the repo and were never committed.

**Run once, as designed — and it actually held.** `scripts/run_held_out_eval.py`
refuses to run again once `evidence/eval_results_final_agent.jsonl` has a result for
every question, and does not retry a question that already has a result (an
infrastructure error counts as a result, not a reason to try again — see below). The
harness itself had a real bug on the first attempt — it only wrote results to disk
after *all 12* questions finished, so when question 8 hit a real server error the
first 7 real, already-answered questions were lost with it. That bug (not the system
under test) was fixed to append one result per question immediately, exactly the
same pattern `run_eval.py` already used for the dev set, and the run was started
over from zero — nothing had been persisted by the failed attempt, so this is
completing the one intended run, not a second look at scored results.

### Results

9/12 correct, 2 infrastructure errors, 1 genuine wrong answer:

| Q | Expected | Actual | Result |
|---|---|---|---|
| H01 | sql, correct | sql, correct | OK |
| H02 | sql, correct | **502/503 after retries** | infra error |
| H03 | blocked (RBAC) | blocked | OK |
| H04 | sql, provisional-month | sql, correct incl. "tạm tính" | OK |
| H05 | docs, access_denied | abstained | OK |
| H06 | docs, access_denied | abstained | OK |
| H07 | **both** (sql+docs) | sql only | **wrong** |
| H08 | both (sql+docs) | **502 after retries** | infra error |
| H09 | no_knowledge | abstained | OK |
| H10 | no data (business abstain) | abstained | OK |
| H11 | docs, paraphrase | docs, correct | OK |
| H12 | docs, paraphrase | docs, correct | OK |

Router tool-selection matched the labelled expectation on 6/9 checked questions (3
questions have no single "right" tool label — the two no-knowledge/RBAC-block cases
and one abstain — and are excluded from this specific count, not from correctness).

**Latency** (`latency_ms` from the real HTTP response, 10 completed requests — the 2
infra errors have no latency to report):

| Percentile | ms |
|---|---:|
| p50 | 2,807 |
| p95 | 7,848 |
| min | 1,419 |
| max | 7,848 |

**Token cost** (real `usageMetadata.totalTokenCount`, read from `audit_log` — see
ADR-018; this is the first time this project has a real number here instead of `NULL`
in every row):

| | |
|---|---:|
| Sum, 10 completed requests | 6,189 tokens |
| Mean per request | 618.9 tokens |

**Not converted to a VND/USD figure.** Google AI Studio does not expose a
pricing-lookup API, and writing a fixed per-token rate into this report risks it
going stale silently. Convert `mean tokens/request × <current published rate for
gemini-3.1-flash-lite>` at the public pricing page, dated to when you read it,
instead of trusting a number frozen here.

### Three real findings, left as findings — not patched and re-run

Per `AGENTS.md`: "seeing a held-out score and continuing to tune, then reporting
again on the same set" is explicitly forbidden. All three issues below are real,
reproduced with a server log line, and **left unfixed** — they are backlog items for
whichever session picks this project up next, not silently absorbed into a better
final number.

1. **Router sometimes drops one tool from a combined question (H07).** Asked in one
   sentence for both a revenue figure and a related policy fact, the router chose
   `sql` only — the exact failure mode the agent-routing section already flagged from
   one manual test, now confirmed on a second, independent question. Sample size is tiny (2
   combined questions in this set, 1 failed) — not a rate, a confirmed existence
   proof of the gap.
2. **A self-contradictory model response has no graceful fallback (H08).** Server
   log: `generation gave up: van sai schema sau 2 lan: sai schema: : Value error,
   abstained=true nhung van co citations`. Gemini occasionally returns
   `abstained: true` with a non-empty `citations` array — `generation.py`'s Pydantic
   validator correctly rejects this as self-contradictory, retries once, and if the
   retry repeats the contradiction, raises `SchemaFailure` → the caller gets a bare
   502 instead of a degraded-but-honest answer (e.g. treat it as abstained and drop
   the citations, rather than fail the whole request).
3. **A raw network timeout to Gemini is not retried, unlike a tool-level infra
   error (H02).** Server log: `upstream call failed: The read operation timed out` →
   503. `router.py::_call_gemini` and `generation.py::_call_gemini` both retry HTTP
   *status* codes in `_RETRYABLE_STATUS` (429/500/502/503/504), but neither catches
   `httpx.TimeoutException`/`httpx.ConnectError` — those propagate immediately. This
   is inconsistent with `loop.py`'s tool-level `_retry()` wrapper, which does retry
   those exact exception types for `sql_tool`/`docs_tool`. ADR-016's jitter work
   assumed the retry loop was reached; here it never was.

### What this report did not attempt

- Fixing the three findings above (see previous section for why).
- A held-out rerun after fixing them — would need a **new** held-out set, since this
  one is now spent (`AGENTS.md`, `eval/final.jsonl` note).
- Converting token counts to a currency figure (see above).
- Load/concurrency testing — this run, like every eval run before it, was
  sequential, one request at a time.

### Follow-up: all three findings fixed in a later session (ADR-020)

Fixing them does not touch this section's numbers or `eval/final.jsonl` — that set
stays sealed, and these fixes were **not** verified by rerunning it (doing so would
be exactly the "tune, then rescore the same held-out set" this report already
declined to do). Summary; full detail in ADR-020:

- **H02 (network timeout not retried):** fixed — `_call_gemini` in both
  `router.py` and `generation.py` now retries `httpx.TimeoutException`/
  `ConnectError` the same way it already retried a 503.
- **H08 (self-contradictory response, 502):** fixed — an `abstained: true`
  response with leftover `citations` now degrades to a plain abstain (citations
  dropped, logged in `grounding_problems`) instead of failing schema validation.
- **H07 (router drops a tool on a combined question):** the router prompt was
  strengthened (an explicit two-condition checklist plus a worked example).
  Measured on 6 **new** combined questions, not `eval/dev.jsonl` or
  `eval/final.jsonl` (`scripts/probe_router_combined_tools.py`,
  `evidence/router_combined_tools_probe.json`): 6/6 selected both tools. Small
  sample — evidence of a real improvement, not a guarantee at scale.
