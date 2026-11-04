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
