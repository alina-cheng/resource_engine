# Requirements: HSDS ingest

Traces to: BR-1, BR-2, BR-3, BR-12

## User story
As a platform engineer, I add a source and get valid HSDS records, with nothing lost or duplicated, so that every consumer sees one format.

## Acceptance criteria (EARS)
1. WHEN an import runs THE SYSTEM SHALL store every fetched payload exactly as received with source name and fetch time.
2. WHEN a source record is mapped THE SYSTEM SHALL validate every resulting HSDS object against the pinned schema before storing any of them.
3. IF a record cannot be converted to valid HSDS THEN THE SYSTEM SHALL quarantine the whole record with the reason and SHALL NOT store part of it.
4. WHEN an import finishes THE SYSTEM SHALL report received, stored and quarantined counts and SHALL fail the run if received differs from stored plus quarantined.
5. WHEN the same source is imported again THE SYSTEM SHALL update existing records by deterministic id and SHALL NOT create duplicates.
6. WHEN a source update and a human or AI change touch the same field THE SYSTEM SHALL keep the current value and open a conflict change request.
7. WHEN a new source is added THE SYSTEM SHALL require only an adapter module and a configuration entry.
8. WHEN an admin uploads a JSON file for an existing source THE SYSTEM SHALL run it through the same fetch, map, validate and upsert-or-quarantine pipeline as a configured import, reusing that source's adapter, and SHALL report the same balanced counts.
