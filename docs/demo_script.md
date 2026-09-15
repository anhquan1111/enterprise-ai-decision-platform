# Demo script (2-3 minutes)

D5 deliverable. Every line below is a command already reproducible from the Quick
Start in `README.md` — nothing here is staged or trimmed of failures. If a step
fails when you actually record it, keep the failure in: that is more convincing than
a silent cut, and consistent with how this project reports every other result.

Recording tool: `Win+Alt+R` (Xbox Game Bar, no install) or OBS. No editing needed
beyond trimming dead air at the start/end.

## Setup (before recording — not part of the timed demo)

```bash
docker compose up -d db
docker compose exec -T db psql -U app -d enterprise_ai -f /sql/01_schema.sql
docker compose exec -T db psql -U app -d enterprise_ai -f /sql/02_seed.sql
docker compose exec -T db psql -U app -d enterprise_ai -f /sql/06_auth.sql
uv run python -m scripts.ingest
uv run python -m scripts.backfill_embeddings
uv run python -m scripts.issue_api_keys   # copy one printed key for emp_006 (engineering/employee)
uv run uvicorn src.api:app --port 8010
```

Have the printed key for `emp_006` ready in a `KEY=` shell variable before recording.

## Timed script

| Time | Screen | Say |
|---|---|---|
| 0:00–0:20 | `README.md`, top of file (status banner) | "This is an internal Q&A API — it answers from either business data or policy documents, with citations, inside the asker's access scope, and it's D5: a fresh 12-question held-out set was just run once against this exact system." |
| 0:20–0:45 | Terminal: run the no-header request | `curl -s -X POST http://127.0.0.1:8010/ask -H "Content-Type: application/json" -d '{"user_id":"x","role":"executive","department":"finance","question":"..."}'` → show the `401`. "No key, no answer — role and department in the request body are never trusted." |
| 0:45–1:15 | Terminal: real request with `emp_006`'s key, a docs question | `curl ... -H "Authorization: Bearer $KEY" -d '{"user_id":"emp_006","role":"employee","department":"engineering","question":"Neu mot ban release bi loi thi phai lam gi?"}'` → point at `citations[0].quote` in the JSON. "The answer quotes the exact source chunk — `ENG-007#1` — not a paraphrase the model made up." |
| 1:15–1:45 | Terminal: same key, a cross-department SQL question | `curl ... -d '{"user_id":"emp_006","role":"employee","department":"engineering","question":"Doanh thu phong finance thang 1 nam 2026 la bao nhieu?"}'` → point at `abstained: true`. "Engineering asking for finance's revenue — blocked before the SQL query even runs, using the identity from the key, not anything in this request body." |
| 1:45–2:15 | `curl http://127.0.0.1:8010/metrics` then `docker compose exec -T db psql ... -c "select * from audit_log order by created_at desc limit 3;"` | "Every one of those three requests — the 401, the answer, the block — is on `/metrics` for Prometheus, and every successful one has a row in a real audit log: who, what tool, how long, how many tokens." |
| 2:15–2:45 | `docs/report.md`, D5 section | "The held-out run itself found three real bugs — a router that sometimes drops one tool on a combined question, a model response that contradicts its own schema, a network timeout that isn't retried. All three are documented and left unfixed on purpose — patching them and rescoring the same held-out set would defeat the point of it." |
| 2:45–3:00 | `README.md`, Limits section | "None of that is hidden in a limits section at the bottom — that's the same discipline this project has used since the first bug it found, in D2." |

## What not to do

- Do not cut the 401 or the RBAC block out of the recording — they are the two most
  convincing 15 seconds in the whole demo.
- Do not re-run a command that failed live to get a cleaner take. If the network
  timeout limitation shows up on camera by chance, leave it in and mention it — it is
  literally one of this project's own documented findings.
