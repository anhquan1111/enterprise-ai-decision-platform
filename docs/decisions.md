# Decision log

Short records of choices that are not obvious from reading the code, so the
reasoning survives past the day it was made. Format: context → decision →
consequence. A decision that later turns out wrong is superseded here, not
silently edited.

---

## ADR-001 — One PostgreSQL instance for business data, vectors and audit log

**Date:** D0 · **Status:** accepted

**Context.** The system needs relational business tables (for the SQL tool),
document chunks with embeddings (for the retrieval tool), and an audit trail. The
obvious alternative is a dedicated vector database (Qdrant, Weaviate) next to
PostgreSQL.

**Decision.** Use a single PostgreSQL 17 instance with the `pgvector` extension
for all three.

**Why.** Two reasons, in order of weight:

1. **Access control stays in one place.** Row-level scoping for SQL results and
   document chunks is enforced by the same `WHERE` clauses against the same
   session. With a separate vector store, the document side would need its own
   filter implementation, and two implementations of one security rule is how
   isolation bugs happen.
2. Fewer moving parts for a demo that must start with one command.

**Consequence.** Approximate-nearest-neighbour tuning options are narrower than a
dedicated vector DB. At a few hundred chunks this is irrelevant — exact search is
fast enough, and an honest "exact search, corpus is small" beats an untuned HNSW
index. Revisit only if measured latency says so.

---

## ADR-002 — LLM and embedding provider deliberately unset on D0

**Date:** D0 · **Status:** open, decide on D2

**Context.** Generation and embeddings both need a provider. Anthropic has no
embedding API; OpenAI and Google have both generation and embeddings; local
`sentence-transformers` embeddings are free but pull in torch (a large download).

**Decision.** `LLM_PROVIDER`, `LLM_MODEL` and `EMBEDDING_BACKEND` default to
`unset`/`local` and are read from the environment. No provider SDK is a hard
dependency yet; the `embed` and `eval` extras stay optional.

**Why.** Committing the skeleton to one vendor before the eval harness exists
would make the first measurement a vendor comparison instead of a baseline.

**Consequence.** D2 must pick one and record the exact model name and date in
`docs/report.md`, because model behaviour changes over time and a number without
a model name cannot be reproduced.

---

## ADR-003 — The eval set and the evidence files are committed; data and models are not

**Date:** D0 · **Status:** accepted

**Context.** `.gitignore` normally excludes data. But the evaluation questions are
ground truth written by hand, and every number in the README comes from a
specific run.

**Decision.** Commit `eval/` (questions and expected answers) and `evidence/`
(raw run outputs). Keep `data/raw/`, `models/`, `mlruns/` out.

**Why.** A claimed metric that cannot be traced to a file is not evidence. The
eval set is also the artefact that makes a retrieval change comparable across
days; versioning it in git (and with DVC once it grows) is what makes
"recall went from A to B" a statement about the system rather than about the
dataset.

**Consequence.** The eval set is visible to anyone reading the repo. That is
intended — it invites the reader to judge whether the questions are fair.

---

## ADR-004 — Liveness and readiness are separate endpoints

**Date:** D0 · **Status:** accepted

**Context.** A container healthcheck that calls the database will fail the
container when the database is briefly unavailable, and the orchestrator will
restart a process that was working fine.

**Decision.** `/health` reports only that the process is up and makes no
dependency calls. `/ready` checks PostgreSQL and returns 503 when it is
unreachable. The Docker `HEALTHCHECK` uses `/health`.

**Consequence.** A database outage makes the service not-ready (so traffic can be
withheld) without triggering a restart loop.

---

## ADR-005 — Database host defaults to `127.0.0.1`, never `localhost`

**Date:** D0 · **Status:** accepted, found by measurement

**Context.** The first run of the integration test hung instead of failing.

**Diagnosis.** On this Windows host, `localhost` resolves to `::1` (AAAA) before
`127.0.0.1` (A), while compose publishes the port as `127.0.0.1:5433:5432` — IPv4
only. `Test-NetConnection ::1 -Port 5433` returns false, `127.0.0.1` returns true.
The client attempted IPv6 first and stalled.

**Decision.** Default `POSTGRES_HOST` to `127.0.0.1` in both `src/config.py` and
`.env.example`.

**Consequence.** The same test went from hanging to passing in 0.44s. Keep the
explicit IPv4 binding in compose: binding to all interfaces would hide this but
would also expose the database beyond the host.
