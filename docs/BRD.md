# Business Requirements Document: One Degree Resource Engine

## 1. Purpose
One Degree helps low-income people find free and low-cost services. Its directory (30,000+ listings) goes stale from the day it is published, and specialists verify listings by hand. The Resource Engine replaces the legacy resource service (ODRS) over time. It ingests data from several sources, converts it to Open Referral HSDS, keeps it accurate with an AI maintenance worker that humans supervise, and serves it to help seekers, providers and One Degree staff.

## 2. Personas and goals
| Persona | Goal | Must be able to |
|---|---|---|
| Help seeker | Find help fast, without jargon | Ask questions without logging in; create a profile to be matched; send a request to a provider; see request status; control what is shared |
| Help provider | Keep listing current; reach people it can serve | See who it has supported; see people in need that match what it offers; propose data changes (HSDS); share policy documents |
| One Degree admin | Keep data trustworthy at scale | See seeker and provider profiles; edit provider data; approve or reject every provider-, AI- or source-proposed change; run imports and AI checks on demand or on schedule; manage API keys |
| Engineer / data partner | One consistent format and API | Call an HSDS API with a key (optionally limited to one source) |

## 3. Business requirements
IDs are referenced by tests (`docs/test-plan.md`) and Kiro specs.

| ID | Requirement | Priority |
|---|---|---|
| BR-1 | Import data from the ODRS and NDP formats, on a schedule and on demand by an admin; keep each payload exactly as received | Must |
| BR-2 | Every stored record validates against the pinned HSDS version; records that cannot be converted are quarantined with the reason; received = stored + quarantined | Must |
| BR-3 | Re-running an import never duplicates records and never silently overwrites a human or AI change; clashes are shown to an admin | Must |
| BR-4 | Every change to stored data records who, what (old and new value), when and why | Must |
| BR-5 | Provider edits do not take effect until an admin approves them | Must |
| BR-6 | An AI worker checks records against organization websites on a schedule, for all records or one record on admin request, and proposes evidence-backed changes that require admin approval | Must |
| BR-7 | Failures (site gone, certificate expired, unreadable) are reported as findings, not silently skipped | Must |
| BR-8 | Anonymous visitors can chat about One Degree; a request for a service requires a profile; signed-in seekers get matched providers and can send a request with explicit consent | Must |
| BR-9 | Providers see who they have supported and unassigned people whose needs match their services, with privacy controls | Must |
| BR-10 | Policy documents (PDF and others) are searchable by chat with citations, after admin approval | Must |
| BR-11 | HSDS API protected by API keys; a key can be limited to one source | Must |
| BR-12 | Adding a data source or changing the HSDS version needs configuration plus one module, not core changes | Should |
| BR-13 | Runs on AWS with cost control, scalability and operational visibility; also runs locally for demos | Must |
| BR-14 | Sample-data generator produces schema-faithful data for demos and load tests | Must |
| BR-15 | Spreadsheet ingestion (two very different layouts, model-assisted column mapping) | Stretch |

## 4. Out of scope
Writing back to ODRS; enforcing content style rules; phone or email outreach; multilingual listings; integrating with One Degree's own authentication; real client data. HIPAA and SOC 2 apply to One Degree as an organization; **seeker profiles and requests are personal data and need a privacy review before production** (see `docs/known-limitations.md`).

## 5. Success measures
1. 100% of stored and served records validate against the pinned schema. 2. Every import balances. 3. A third source needs only an adapter and configuration. 4. On the seeded evaluation, the maintenance layer catches at least 95% of seeded problems with at most 5% false flags on clean pages. 5. A specialist goes from flagged record to saved fix in three steps (open, review evidence, approve).

## 6. Assumptions and risks
The website is treated as more accurate than the record (R2.4); wrong websites will cause wrong proposals, so a human always decides. ODRS lacks an organization description that HSDS requires (policy: fallback text plus a flag, or quarantine). Hours need a UTC offset that changes with daylight saving (offset plus IANA zone stored). The NDP mock may differ from the real feed.
