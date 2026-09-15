# Enterprise AI Decision Platform

An internal question-answering API for a company: an employee asks in natural
language, the system decides whether the answer lives in **business data (SQL)**
or in **internal policy documents (retrieval)**, and answers **with citations**,
**only within the asker's access scope**, while **logging every request for
audit**.

> **Status: D5 — final report on a fresh held-out set.** A genuinely new 12-question
> held-out set (`eval/final.jsonl`) was run **once**, through the real, running
> `/ask` endpoint with real authentication — 9/12 correct, 2 infrastructure errors,
> 1 genuine router mistake, none patched afterward (that would defeat the point of a
> held-out set). Real p50/p95 latency and real per-request token cost, both read
> from `audit_log` for the first time (it existed since D1, `total_tokens` was
> always `NULL` until now — see ADR-018). Full results, the three real bugs the
> held-out run found, and why they were left unfixed rather than quietly patched and
> re-scored: [`docs/report.md`](docs/report.md) (D5 section) and ADR-019.
>
> `/ask` requires a real API key (`Authorization: Bearer <key>`, D4) — RBAC runs on
> the **authenticated** role/department, not a self-declared request field, closing a
> real vulnerability found by testing (ADR-015, exact `curl` before/after in
> `docs/report.md`). Every request is written to `audit_log` and exposed on
> `/metrics` (Prometheus). `/ask` routes each question (Gemini classifies `sql` /
> `docs` / both) and returns SQL figures verbatim, never rephrased by an LLM.
> D2 baseline: 18/18 answerable questions retrieved correctly, 0 fabricated
> citations, 0 access violations across 25 dev questions; hybrid retrieval was
> measured and **not built** — 5/5 recall on 5 deliberately hard paraphrases, no gap
> to fill (ADR-011). Build order and progress: [`AGENTS.md`](AGENTS.md#7-session-plan-d0--d5).
> A full, guided reading order for D0 through D5 is in
> [`docs/reading_order.md`](docs/reading_order.md).

## Why this project

Three properties decide whether an enterprise can actually use an LLM assistant,
and all three are usually missing from demos:

| Property | What it means here |
|---|---|
| **Verifiable answers** | Every claim carries a citation — a document chunk or the SQL statement that produced the number. An answer that cannot be traced is treated as a failure, not a success. |
| **Access control that holds** | Scope is applied as a filter in the SQL `WHERE` clause and the retrieval query, *before* any text reaches the model. The model never sees a chunk the caller may not read. Telling a model "do not reveal restricted documents" is an instruction, not a boundary. |
| **Measured, not asserted** | Retrieval changes are evaluated against a fixed question set with a baseline measured first. "Hybrid search is better" is only a claim if there is a number behind it. |

## Architecture

```mermaid
flowchart TB
    U["Caller: Authorization: Bearer API key"] --> API["POST /ask"]
    API --> AUTH["Authenticate: key -> real employee"]
    AUTH -->|invalid/missing| R401["401/403 — never reaches data"]
    AUTH --> AG["Router: which tool can answer? (authenticated role/department)"]
    AG -->|numbers| T1["SQL tool: parameterised, read-only"]
    AG -->|rules| T2["Docs tool: dense retrieval, scope-filtered"]
    T1 --> DB[("PostgreSQL 17 + pgvector, pooled")]
    T2 --> DB
    T1 --> GEN["Generation: structured output"]
    T2 --> GEN
    GEN --> VAL["Validator: schema + every claim cited"]
    VAL -->|no evidence| ABS["abstained = true"]
    VAL --> OUT["AskResponse JSON"]
    OUT --> AUD["Audit log + Prometheus metrics"]
```

Full detail in [`docs/architecture.md`](docs/architecture.md). Design choices and
the reasoning behind them are recorded in [`docs/decisions.md`](docs/decisions.md).

## Quick start

Requirements: Docker, [uv](https://docs.astral.sh/uv/), Python 3.12.

```bash
git clone https://github.com/anhquan1111/enterprise-ai-decision-platform.git
cd enterprise-ai-decision-platform
cp .env.example .env
# paste a Google AI Studio key into LLM_API_KEY — needed for embeddings and generation

uv sync --extra dev
docker compose up -d db

# Schema, business data, then the document corpus
docker compose exec -T db psql -U app -d enterprise_ai -f /sql/00_extensions.sql
docker compose exec -T db psql -U app -d enterprise_ai -f /sql/01_schema.sql
docker compose exec -T db psql -U app -d enterprise_ai -f /sql/02_seed.sql
docker compose exec -T db psql -U app -d enterprise_ai -f /sql/06_auth.sql
uv run python -m scripts.ingest
uv run python -m scripts.backfill_embeddings    # embeds the 16 chunks, idempotent
uv run python -m scripts.issue_api_keys         # prints one real key per employee, ONCE

uv run uvicorn src.api:app --reload --port 8010
# http://127.0.0.1:8010/docs
```

Ask it something (needs a real key from `issue_api_keys` — `/ask` requires
`Authorization: Bearer <key>` since D4; without it, or with a role that doesn't match
the key's real owner, the request is rejected before touching any data — see
[`docs/report.md`](docs/report.md) D4 for why):

```bash
KEY="<paste emp_006's key here — engineering/employee>"

curl -s -X POST http://127.0.0.1:8010/ask -H "Content-Type: application/json" \
  -H "Authorization: Bearer $KEY" -d '{
  "user_id": "emp_006", "role": "employee", "department": "engineering",
  "question": "Neu mot ban release bi loi thi phai lam gi?"
}'
# routes to the docs tool, cites ENG-007#1. Ask the same question about an
# executive-only expense limit and it abstains instead of guessing.

curl -s -X POST http://127.0.0.1:8010/ask -H "Content-Type: application/json" \
  -H "Authorization: Bearer $KEY" -d '{
  "user_id": "emp_006", "role": "executive", "department": "finance",
  "question": "Doanh thu phong finance thang 1 nam 2026 la bao nhieu?"
}'
# 403 — the key belongs to an "employee" in "engineering"; the body's self-declared
# role/department doesn't match, so the request never reaches the agent. Role and
# department for RBAC always come from the authenticated key, never the request body.
```

See how the contract rejects bad data, without touching the clean corpus:

```bash
uv run python -m scripts.ingest data/documents_dirty.csv
# 8 rows in, 0 accepted, 8 quarantined — each with a readable reject_reason
```

Verify:

```bash
curl http://127.0.0.1:8010/health    # liveness, no DB call
curl http://127.0.0.1:8010/ready     # readiness, checks PostgreSQL
curl http://127.0.0.1:8010/metrics   # Prometheus scrape endpoint (D4), no auth required
uv run pytest tests/ -v -m "not integration and not live_llm"   # fast, no network
uv run pytest tests/ -v -m integration                          # needs the db container
uv run pytest tests/ -v -m live_llm                              # calls real Gemini, spends quota
uv run python -m scripts.run_eval --report                       # baseline numbers, no calls
```

## Tech stack

Python 3.12 · FastAPI · PostgreSQL 17 + pgvector 0.8.6 · psycopg 3 (raw SQL, no
ORM, pooled connections via `psycopg_pool` since D4) · Pydantic 2 · Gemini
(`gemini-3.1-flash-lite` for generation and the agent router, `gemini-embedding-001`
at 384 dims) via plain `httpx` (no SDK, no function-calling API — the router uses
JSON mode, same pattern as generation) · prometheus-client (metrics, D4) · pytest ·
ruff · mypy · Docker Compose · GitHub Actions. MLflow is declared as an extra for
later layers; not used yet. BM25/hybrid retrieval was evaluated at D3 and
deliberately not built — see ADR-011 in [`docs/decisions.md`](docs/decisions.md).

## Project layout

```text
src/
├── api.py             # FastAPI app: /health, /ready, /metrics, /ask
├── config.py          # Settings from env/.env
├── contracts.py       # Data contract: rules, severity, role visibility
├── db.py              # psycopg helpers, pooled connections + statement timeout (D4)
├── auth.py             # D4: API key -> authenticated employee (real AuthN)
├── audit.py             # D4: writes audit_log (table since D1, unused before now)
├── metrics.py            # D4: Prometheus counters/histogram for /ask
├── embeddings.py       # Gemini embedding calls, one function for ingest and query
├── retrieval.py         # Dense retrieval: scope + point-in-time filter, then cosine rank
├── generation.py       # Structured output: JSON mode, retry-with-error, two gates
├── eval_taxonomy.py     # 8-label error classifier (access / knowledge / retrieval / generation)
├── scope.py            # Role -> visible access levels (docs); role+dept -> SQL access
├── agent/               # D3: router + 2 tools + bounded orchestration pipeline
│   ├── router.py          # Gemini JSON mode: classifies sql / docs / both
│   ├── tools.py            # sql_tool (RBAC before query), docs_tool (wraps retrieval.py)
│   ├── schema.py            # ToolPlan / SqlArgs, two-layer validation
│   └── loop.py               # route -> RBAC -> execute (retry/timeout) -> summarize
└── schemas.py           # Request/response contracts

scripts/
├── ingest.py                     # read -> validate -> quarantine -> upsert -> manifest
├── backfill_embeddings.py        # embeds chunks with embedding IS NULL, idempotent
├── issue_api_keys.py             # D4: issues one real API key per employee, once
├── run_eval.py                   # scores eval/dev.jsonl (docs-only D2 pipeline), resumable
├── run_held_out_eval.py          # D5: scores eval/final.jsonl through the real /ask HTTP API, once
└── probe_retrieval_headroom.py   # one-off: checked for a hybrid-retrieval gap (ADR-011)

sql/                # 00 extensions, 01 schema, 02 seed, 03-05 queries/EXPLAIN, 06 auth (D4)
data/               # Synthetic corpus (16 chunks) + a deliberately dirty batch
eval/               # dev.jsonl (25 questions, open); final.jsonl (12 questions, sealed — D5)
evidence/           # Raw outputs behind every number quoted here
docs/               # architecture.md, decisions.md, query_plan.md, report.md, runbook.md,
                    # demo_script.md, cv_bullets.md, reading_order.md
tests/              # Fast unit tests (mocked); `integration` needs Postgres;
                    # `live_llm` calls real Gemini — neither runs in CI
```

### What the data layer enforces

| Layer | Catches |
|---|---|
| `src/contracts.py` | Duplicate keys, missing required fields, values outside the allowed set, reversed validity intervals, `available_at` before `published_at`. Rejected rows go to `doc_chunks_quarantine` with a readable reason. |
| PostgreSQL constraints | The same rules again, so a migration script or a manual fix during an incident cannot bypass them. |
| `ingest_run` table | One manifest row per run: counts per rule, and a `CHECK` that accepted + quarantined equals rows in file. |

Query plans for the retrieval path, measured at 16 and ~20k rows, are in
[`docs/query_plan.md`](docs/query_plan.md).

## Evaluation

Full numbers, the model name, the date, and two measurement bugs found while
getting them: [`docs/report.md`](docs/report.md). Summary:

| Metric | D2 baseline (25 questions, `gemini-3.1-flash-lite`) |
|---|---|
| recall@3 / @5 / @10 | 18/18 (100%) — flat because gold ranked first every time |
| MRR | 1.000 |
| Correct answers | 18/18 |
| Correctly refused (access / no-knowledge) | 5/5, 2/2 |
| Fabricated citations, access violations, retrieval misses | 0 |

Reproduce: `uv run python -m scripts.run_eval --report` (reads results already
on disk) or `uv run python -m scripts.run_eval` (calls the real API).

`eval/final.jsonl` is deliberately empty. It held 5 questions that were scored
too early — before the agent (D3) and RBAC/audit (D4) existed, so the
result would not describe the finished system. They were folded into
`eval/dev.jsonl` instead of deleted or silently rerun; see ADR-010 in
`docs/decisions.md`. D5 draws a fresh held-out set once D3 and D4 land.

D3 also measured whether hybrid retrieval had anything to improve before building it:
5 deliberately hard paraphrases, chosen to share as little vocabulary as possible with
existing dev questions, still resolved with 100% recall@3. Hybrid was not built — see
ADR-011 and [`evidence/hybrid_headroom_probe.json`](evidence/hybrid_headroom_probe.json).

### D5 — held-out set, run once

| Metric | Result |
|---|---|
| Held-out questions | 12 (`eval/final.jsonl`), genuinely new — see ADR-019 |
| Correct | 9/12 |
| Infrastructure errors (502/503, retried by the app, still failed) | 2/12 |
| Router picked the wrong tool for a combined sql+docs question | 1/12 |
| Latency p50 / p95 (real HTTP, 10 completed requests) | 2,807 ms / 7,848 ms |
| Token cost, real (`audit_log.total_tokens`, first real numbers since D1) | 618.9 mean / request |

Reproduce: `uv run python -m scripts.run_held_out_eval --report` (the run itself
cannot be repeated — it is sealed; see `docs/report.md`). The three real bugs this
run found were deliberately **not** fixed-and-rerun on the spot — doing so on the
same held-out set would defeat its purpose. A later session fixed all three without
touching the sealed set or these numbers; see ADR-020 and "Follow-up" in
`docs/report.md`.

## Limits

- The corpus is **synthetic**, written for this project. No real company documents.
- Exact vector search, no ANN index. Correct at a few hundred chunks; not a claim
  about scale.
- 25 questions on a 16-chunk corpus is a learning-scale evaluation. Zero failures
  in every error category is a real result on this dataset, not evidence the
  system is reliable in general — see "Not yet measured" in `docs/report.md` for
  what this baseline does not tell you.
- A question asking for both a number and a policy in one sentence used to be
  routed to only one tool sometimes (D3, confirmed by the D5 held-out set). The
  router prompt was strengthened afterward and measured 6/6 on a fresh probe
  (`evidence/router_combined_tools_probe.json`) — a real improvement on a small
  sample, not a guarantee at scale. See ADR-020.
- A self-contradictory model response (`abstained: true` with a non-empty
  `citations` list) used to 502 after exhausting retries — fixed to degrade to a
  plain abstain instead (citations dropped, logged in `grounding_problems`). See
  ADR-020.
- A raw network timeout talking to Gemini (`httpx.TimeoutException`/`ConnectError`)
  used to skip the retry loop entirely — fixed to retry the same as an HTTP 503.
  See ADR-020.
- AuthN (D4) is a possession-based API key, not JWT/OAuth2 — no built-in expiry or
  instant revocation, only manual deletion of `api_key_hash`. See ADR-015.
- Retry jitter (D4) was added for the exact mechanism measured causing concurrent
  `503`s (vault, ngày 25) but has not been re-measured under that same scenario —
  see ADR-016.
- Token cost (D5) is reported in tokens, not currency — no reliable per-token
  pricing lookup was available at measurement time; see `docs/report.md`.
- Not deployed to any cloud provider. It runs locally via Docker Compose.

## Demo and CV material

- [`docs/demo_script.md`](docs/demo_script.md) — a 2-3 minute walkthrough script (D5),
  built entirely from commands and outputs already reproducible above.
- [`docs/cv_bullets.md`](docs/cv_bullets.md) — CV bullets, each traceable to a file or
  ADR in this repo, no number written that isn't measured somewhere in `evidence/`.

## License

MIT
