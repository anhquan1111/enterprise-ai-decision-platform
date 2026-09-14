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
    U["Caller: user_id + role + department"] --> API["POST /ask"]
    API --> V["Contract validation (Pydantic)"]
    V -->|"invalid role / empty question"| R422["422 — never reaches data"]
    V --> SC["Resolve access scope from role + department"]
    SC --> AG["Router: which tool can answer this?"]
    AG -->|numbers| T1["SQL tool: parameterised, read-only"]
    AG -->|rules| T2["Docs tool: hybrid retrieval, scope-filtered"]
    AG -->|both| T3["Both tools"]
    T1 --> DB[("PostgreSQL 17 + pgvector")]
    T2 --> DB
    T1 --> GEN["Generation: structured output"]
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

## Module layout

```text
src/
├── api.py          # FastAPI app: /health, /ready, /ask
├── config.py       # Settings from env/.env, single source of truth
├── db.py           # psycopg helpers; read-only sessions for the query path
└── schemas.py      # Request/response contracts (Role, Department, Citation)

sql/                # Schema and seed, applied with psql (D1)
eval/               # Evaluation questions with ground truth (D2)
evidence/           # Raw outputs behind every number in the README
scripts/            # One-purpose CLI entry points (ingestion, eval runs)
docs/               # architecture.md, decisions.md, report.md (D5)
```

## Build order

Each day adds one layer and leaves the previous layers working. The
evaluation harness comes **before** the retrieval improvements on purpose: without
a baseline measured first, "hybrid search is better" is an opinion.

| Day | Layer | Depends on | Status |
|---|---|---|---|
| D0 | Skeleton: config, DB access, contracts, health/ready, CI | — | done |
| D1 | Schema + contract-validated ingestion | D0 | done |
| D2 | Dense retrieval, structured output, **eval set + baseline numbers** | D1 | done — `docs/report.md` |
| D3 | Hybrid retrieval measured against D2 baseline, agent routing | D2 | not started |
| D4 | RBAC scoping (SQL tool), audit log, timeouts | D1, D3 | not started — docs retrieval already scopes by role (D1/D2) |
| D5 | Final report on a fresh held-out set, README, demo | all | not started |

## Known limits (kept current)

- `/ask` answers document questions (D2): dense retrieval, RBAC and point-in-time
  filtered, structured output with two validation gates. It does not yet answer
  business-number questions or route between tools — no SQL tool and no agent
  exist yet (D3). A revenue question is treated as no evidence and abstains,
  which is accurate but not useful.
- No audit logging yet (D4). The `audit_log` table exists; nothing writes to it.
- The corpus is synthetic, written for this project. No real company documents.
- Exact vector search, no ANN index — correct at a few hundred chunks, not a
  statement about scale.
