# CV bullets

Every number below points at a specific file or ADR in this repo —
before using one, open that source and confirm the number still matches (numbers in
`evidence/` don't change; a bullet copied without checking is exactly the mistake
`AGENTS.md` mục 4 warns against: "đưa số chưa đo vào README/CV"). Pick 3-4 that fit
the role you're applying for rather than using all seven — see selection notes below.

## The bullets

```text
• Ran a genuinely new 12-question held-out evaluation against a live RAG+SQL agent
  through its real HTTP API (real auth, real audit log) — 9/12 correct, and left the
  3 real bugs it found (a router tool-selection miss, a schema-contradiction crash, an
  unretried network timeout) unfixed rather than patch-and-rescore the same set, which
  would have invalidated the whole point of holding it out. (docs/report.md, ADR-019)

• Instrumented real per-request token cost end-to-end — a column that had existed
  unused in the database since the project's first day — by reading usageMetadata
  from the LLM API and threading it through a multi-tool agent pipeline without
  introducing a concurrency bug (rejected a simpler module-global design specifically
  because it could race under concurrent requests). (src/agent/router.py, ADR-018)

• Built an internal Q&A API that routes between SQL (business data) and document
  retrieval with citations and role-based access control — 18/18 answerable
  evaluation questions correct, MRR 1.000, zero fabricated citations or access
  violations across 25 questions. (docs/report.md)

• Measured whether hybrid retrieval (BM25 + dense embeddings) would improve
  results BEFORE building it — 5 deliberately hard paraphrase queries against the
  production corpus still resolved at 100% recall@3, so documented the decision
  not to add the complexity instead of following the original plan. (ADR-011)

• Found and closed a real authentication vulnerability through testing: an
  unauthenticated request could self-declare an executive role and receive
  restricted financial-approval data. Fixed with a real API-key auth layer so
  access control uses the authenticated identity, not client-submitted fields —
  verified end-to-end with a live before/after reproduction. (ADR-015)

• Wrote a 61-case automated access-control isolation test matrix (role × access
  level for documents, role × department × department for business data) plus
  live end-to-end auth tests against a real database — 187/187 tests passing.
  (tests/test_rbac_isolation.py, tests/test_auth_integration.py)

• Instrumented the API with Prometheus metrics and a real audit trail, then fixed
  three reliability gaps found through direct measurement: database connection
  pooling (~15ms -> ~5.5ms per request), a missing query-level statement timeout,
  and a retry-backoff collision that caused concurrent requests to fail under a
  provider rate limit. (ADR-016, ADR-017)
```

## Selection notes

| Role emphasis | Prefer |
|---|---|
| Eval / MLOps rigor, "how do you know it works" | Bullets 1, 2, 4 — held-out discipline and a decision not to build something |
| Security / access control | Bullets 3, 5, 6 |
| Backend reliability / SRE | Bullets 2, 7, plus bullet 1's "unretried timeout" detail as a talking point |

## The one-sentence version of bullet 1, for a cover letter

"I ran a held-out evaluation the way it's supposed to be run — once, honestly
reported, including the three bugs it exposed — instead of quietly fixing and
re-scoring until the number looked better."

That sentence is defensible in an interview because it is literally what
`docs/report.md`'s held-out section and ADR-019 show happened, with the server log
lines to back it up.
