# Architecture

## The question this system answers

An employee asks a question in natural language. It may need a **number** ("what
was Sales revenue last quarter?"), a **rule** ("what is my expense approval
limit?"), or **both**. The system must answer only from evidence the asker is
allowed to see, show where the answer came from, and refuse when the evidence
does not support an answer.

## Request flow

```mermaid
flowchart TB
    U["Caller: Authorization: Bearer API key"] --> API["POST /ask"]
    API --> AUTH["Authenticate: key -> real employee"]
    AUTH -->|"missing/invalid key"| R401["401 — never reaches data"]
    AUTH --> MATCH{"body role/department == authenticated identity?"}
    MATCH -->|no| R403["403 — never reaches data"]
    MATCH --> V["Contract validation (Pydantic)"]
    V -->|"invalid role / empty question"| R422["422 — never reaches data"]
    V --> AG["Router: which tool can answer this? (identity's role/department, not body)"]
    AG -->|numbers| T1["SQL tool: parameterised, read-only"]
    AG -->|rules| T2["Docs tool: dense retrieval, scope-filtered"]
    AG -->|both| T3["Both tools"]
    T1 --> DB[("PostgreSQL 17 + pgvector, pooled connections")]
    T2 --> DB
    T1 --> GEN["Generation: structured output (docs only — SQL numbers verbatim)"]
    T2 --> GEN
    T3 --> GEN
    GEN --> VAL["Validator: schema + every claim cited"]
    VAL -->|"no supporting evidence"| ABS["abstained = true"]
    VAL --> OUT["AskResponse JSON"]
    OUT --> AUD["Audit log row + Prometheus metrics"]
```

## Why the scope is resolved before the router, not inside the prompt

Access control is applied as a filter in the SQL `WHERE` clause and in the
retrieval query, before any text reaches the language model. The model never sees
a chunk the caller may not read.

The alternative — telling the model "do not reveal documents above the caller's
level" — is an instruction, not a boundary. Instructions in a prompt can be
overridden by text that arrives later, including text inside a retrieved
document. That is the prompt-injection path this design removes rather than
mitigates.

## Why role/department come from the authenticated identity, not the request body

Before this was fixed, `AskRequest.role`/`department` were trusted at face value —
nothing verified the caller actually held that role. Measured proof this was
exploitable: an unauthenticated request self-declaring `role=executive` received an
executive-only document (see ADR-015). The fix requires a real API key
(`Authorization: Bearer <key>`, `src/auth.py`); the RBAC/agent layer uses the
role/department looked up from the authenticated employee record, never the
request body's fields. The body fields are still validated against the
authenticated identity (mismatch → `403`) as a defense-in-depth signal for client
bugs, but they are not the source of truth for access control.

## Module layout

```text
src/
├── api.py          # FastAPI app: /health, /ready, /metrics, /ask
├── config.py       # Settings from env/.env, single source of truth
├── db.py           # psycopg helpers; pooled connections, statement timeout
├── auth.py         # API key -> authenticated employee (real AuthN, ADR-015)
├── audit.py        # writes audit_log (table existed a while before this was wired up)
├── metrics.py      # Prometheus counters/histogram for /ask
├── scope.py        # visible_access_levels (docs), can_query_department (SQL)
├── retrieval.py    # Dense retrieval for docs
├── generation.py   # Structured output for docs answers
├── agent/          # router (Gemini) + 2 tools (SQL, docs) + orchestration loop
│   ├── router.py   # Classifies a question into sql/docs/both
│   ├── tools.py    # sql_tool (RBAC before query), docs_tool (wraps retrieval.py)
│   ├── schema.py   # ToolPlan / SqlArgs — two-layer validation
│   └── loop.py     # Bounded pipeline: route -> RBAC -> execute -> summarize (ADR-013)
└── schemas.py      # Request/response contracts (Role, Department, Citation)

sql/                # Schema and seed, applied with psql; 06_auth.sql adds AuthN
eval/               # Evaluation questions with ground truth
evidence/           # Raw outputs behind every number in the README
scripts/            # One-purpose CLI entry points (ingestion, eval runs, probes,
                    # issue_api_keys.py)
docs/               # architecture.md, decisions.md, report.md, runbook.md
```

## Build order

Each phase adds one layer and leaves the previous layers working. The
evaluation harness comes **before** the retrieval improvements on purpose: without
a baseline measured first, "hybrid search is better" is an opinion.

| Phase | Layer | Depends on | Status |
|---|---|---|---|
| Skeleton | config, DB access, contracts, health/ready, CI | — | done |
| Data layer | Schema + contract-validated ingestion | Skeleton | done |
| Retrieval baseline | Dense retrieval, structured output, **eval set + baseline numbers** | Data layer | done — `docs/report.md` |
| Agent routing | SQL + docs tools, RBAC for SQL, retry/timeout | Retrieval baseline | done — `docs/report.md`, ADR-011/012/013. Hybrid retrieval measured and **not built** — see ADR-011 |
| Auth & reliability | AuthN (API key), audit log, Prometheus, connection pool, statement timeout, retry jitter | Data layer, Agent routing | done — `docs/report.md`, ADR-015/016/017 |
| Final report | Final report on a fresh held-out set, README, demo | all | done — `docs/report.md`, ADR-018/019 |

## Known limits (kept current)

- `/ask` answers both document questions (dense retrieval) and business-number
  questions (SQL tool): a Gemini router classifies each question as `sql`, `docs`,
  or both, RBAC is checked per tool **before** execution using the authenticated
  identity's role/department (ADR-015), and SQL numbers are returned verbatim —
  never rephrased by an LLM (ADR-013).
- Hybrid retrieval was measured and deliberately **not built** — dense embeddings
  handled every paraphrase tried, including deliberately hard ones. See ADR-011.
- A question asking for both a number and a policy in one sentence used to be routed
  to only one tool sometimes (confirmed independently by the held-out set) — the
  router prompt was strengthened afterward, measured 6/6 on a fresh probe. Small
  sample, not a guarantee at scale. See ADR-020.
- A self-contradictory model response (`abstained: true` with non-empty citations)
  used to 502 after retries — now degrades to a plain abstain instead (citations
  dropped, logged in `grounding_problems`). Found by the held-out run, fixed
  afterward without touching the sealed set. See ADR-020.
- A raw network timeout to Gemini (`httpx.TimeoutException`/`ConnectError`) used to
  skip `router.py`/`generation.py`'s retry loop entirely — now retried the same as
  an HTTP 503. Found by the held-out run, fixed afterward. See ADR-020.
- AuthN is possession-based API keys, not JWT/OAuth2 — no built-in expiry or
  instant revocation (only manual deletion of `api_key_hash`). See ADR-015 for when
  to upgrade.
- Retry jitter was added for the exact mechanism measured causing concurrent
  `503`s, but the fix itself has not been re-measured under the same
  concurrent-load scenario — see ADR-016.
- Token cost is real (`audit_log.total_tokens`, ADR-018) but reported in tokens,
  not currency — no reliable per-token pricing lookup was available at measurement
  time. See `docs/report.md`.
- The corpus is synthetic, written for this project. No real company documents.
- Exact vector search, no ANN index — correct at a few hundred chunks, not a
  statement about scale.
