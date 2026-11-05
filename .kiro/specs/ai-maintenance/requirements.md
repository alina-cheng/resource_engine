# Requirements: AI maintenance worker

Traces to: BR-6, BR-7

## User story
As an admin, I want records checked against organization websites on a schedule, or one record on demand, so that staff review a short list of evidence-backed problems.

## Acceptance criteria (EARS)
1. WHEN a check runs THE SYSTEM SHALL fetch the organization website and extract phones, counties served, languages, hours and eligibility with a supporting snippet for each.
2. THE SYSTEM SHALL assign each record one category: verified, discrepancy, actively bad, check failed or missing information.
3. IF the website cannot be read, is gone, has an expired certificate or says the organization closed THEN THE SYSTEM SHALL report it as a finding and SHALL NOT skip it silently.
4. WHEN a difference is found THE SYSTEM SHALL create a change request with current value, proposed value, source URL and snippet, and SHALL discard proposals without evidence.
5. THE SYSTEM SHALL compare facts and SHALL NOT flag wording differences.
6. WHEN the page and record are unchanged since a verified check THE SYSTEM SHALL skip the model call.
7. WHEN an admin requests it THE SYSTEM SHALL check a single record immediately.
8. WHEN any signed-in user reports a listing THE SYSTEM SHALL record the report and, on the next maintenance run, select that record and raise a single `user_reported` flag for specialist review, whatever the check concludes. The AI re-reviews only if the page changed since the last review (it respects the hash-skip); the human-review flag is raised regardless.
9. WHEN a reported record has been handled in a run THE SYSTEM SHALL mark its open reports resolved.
10. THE SYSTEM SHALL size each scheduled maintenance run from the active source count so that every source is reviewed within `MAINTENANCE_RECHECK_DAYS`: checks per run = ceil(active_sources / recheck_days) × safety_factor, optionally capped by `MAINTENANCE_MAX_BATCH`. The daily count SHALL NOT be a fixed number and SHALL scale as the corpus grows. An explicit limit (e.g. an admin one-off) overrides the self-sized value.
11. WHEN an admin starts a corpus check without a limit THE SYSTEM SHALL drain all due/unchecked records rather than applying the periodic daily slice. An explicit all-record check SHALL visit every selected service and persist its progress and result, including fetch/extraction failures.
12. WHEN enabled, a completed nonempty import/upload SHALL queue maintenance for the corpus backlog. Edits SHALL make the changed record due immediately; unchanged real-model checks SHALL reuse the persisted full review hash.
13. THE SYSTEM SHALL show checked/total coverage, records needing recheck, and active job progress. A page with no comparable grounded facts SHALL NOT produce a verified marker.
