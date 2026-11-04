# Known limitations (read before production)
1. **HSDS schemas are a hand-authored subset**, not the official v3.2.3 files. Run `make schemas`, then fix whatever the stricter schemas reject.
2. **Untested here:** PostgreSQL path, Cognito, S3, Bedrock, OpenSearch, Textract, live website fetching, ECS job runner, Terraform.
3. **Personal data.** Seeker profiles, needs and requests are sensitive. Needs a privacy and legal review (HIPAA/state law, retention, deletion, consent records, audit of admin access), field-level encryption decisions and a data-processing agreement with any model provider.
4. **Maintenance accuracy** is measured only on synthetic pages. Real sites need JavaScript rendering, different wording and anti-bot handling; those cases surface as `check_failed`.
5. **Hours** use an offset valid at import time plus the IANA zone; the offset can be wrong across daylight-saving changes until recomputed.
6. **Shared ODRS locations** lose per-service accessibility differences (first version wins; disagreements counted).
7. **Not implemented:** spreadsheet adapter (stretch), POST endpoints on the HSDS API, deduplication across sources (provenance links are kept for it), semantic/embedding search, deletion of records removed at the source, email notifications, MFA enforcement in the app (Cognito optional MFA is enabled).
8. **Local auth** uses a shared HS256 secret and in-DB passwords for demos only.
9. Terraform uses broad `Resource = "*"` for Bedrock and Textract; tighten once model ARNs are fixed.
10. **User reports force a recheck on the next maintenance run, not instantly.** `POST /api/reports` records the report and raises the `user_reported` flag; the forced AI check happens when the next scheduled (or admin-triggered) maintenance run picks the record up. There is no per-report rate limiting or de-duplication yet, so a record can accumulate several open reports until it is rechecked (they are all resolved together).
11. **The grounded Bedrock extractor is exercised only with a fake invoker.** Offline runs (demo, tests) use the deterministic rule extractor; the real Bedrock fact extraction path has not been run against a live model in this environment (compounds limitation 2).
