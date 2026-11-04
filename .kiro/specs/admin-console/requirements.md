# Requirements: Admin console

Traces to: BR-1, BR-4, BR-5, BR-6, BR-11

## User story
As an admin, I run imports and checks, review proposals with evidence, edit data and manage access.

## Acceptance criteria (EARS)
1. THE SYSTEM SHALL show counts, record health by category and pending reviews on an overview.
2. WHEN an admin opens the review queue THE SYSTEM SHALL show current and proposed values side by side with evidence and a stale warning.
3. THE SYSTEM SHALL list all records filterable by category and source with last-checked time and a verified marker.
4. THE SYSTEM SHALL let an admin see seeker and provider profiles and create provider logins linked to an organization.
5. THE SYSTEM SHALL show import runs, whether they balance, and quarantined records, and SHALL let an admin upload a JSON file for a chosen source to import it through the normal pipeline.
6. THE SYSTEM SHALL let an admin create, scope and revoke API keys.
7. THE SYSTEM SHALL list user-reported listings with the reporter's note, link each to its record, and let an admin mark a report resolved; the overview SHALL show the count of open reports.
