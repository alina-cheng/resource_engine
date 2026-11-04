# Requirements: Change history and approvals

Traces to: BR-4, BR-5

## User story
As an admin, I approve every change before it goes live and can see who changed what and when, so that data stays trustworthy.

## Acceptance criteria (EARS)
1. WHEN any stored field changes THE SYSTEM SHALL record the field, previous value, new value, actor type, actor, time and note.
2. WHEN a provider submits a change THE SYSTEM SHALL validate the resulting record and SHALL reject an invalid change immediately.
3. WHEN a change request is pending THE SYSTEM SHALL NOT alter the live record.
4. WHEN an admin approves a change request THE SYSTEM SHALL apply it, attribute it to the proposer and record the approver.
5. IF the record changed after a proposal was made THEN THE SYSTEM SHALL block approval until the admin confirms applying anyway.
6. WHEN an admin edits a record directly THE SYSTEM SHALL validate it against HSDS on save and SHALL record history.
