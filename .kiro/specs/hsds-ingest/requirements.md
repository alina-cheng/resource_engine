# Requirements: HSDS ingest

Traces to: BR-1, BR-2, BR-3, BR-12

## User story
As a platform engineer, I add a source and get valid HSDS records, with nothing lost or duplicated, so that every consumer sees one format.

## Acceptance criteria (EARS)
1. WHEN an import runs THE SYSTEM SHALL store every fetched payload exactly as received with source name and fetch time.
2. WHEN a source record is mapped THE SYSTEM SHALL validate every resulting HSDS object against the pinned schema before storing any of them.
3. WHEN mapped HSDS objects fail validation THE SYSTEM SHALL quarantine those objects with their reasons and cascade quarantine to objects that depend on them, while retaining the valid independent object graph. IF a source record cannot be mapped at all, or no valid top-level objects remain, THEN THE SYSTEM SHALL quarantine the source record.
4. WHEN an import finishes THE SYSTEM SHALL report received, stored and quarantined counts and SHALL fail the run if received differs from stored plus quarantined.
5. WHEN the same source is imported again THE SYSTEM SHALL update existing records by deterministic id and SHALL NOT create duplicates.
6. WHEN a source update and a human or AI change touch the same field THE SYSTEM SHALL keep the current value and open a conflict change request.
7. WHEN a new source is added THE SYSTEM SHALL require only an adapter module and a configuration entry.
8. THE SYSTEM SHALL write the accepted graph, its conflicts/history and held-object evidence in one transaction; any write failure SHALL roll back that accepted graph and quarantine the source record.
9. THE SYSTEM SHALL expose separate source-record and mapped-object counts. `received = stored + quarantined` counts source records; partially accepted records count as stored and also as `partial_records`. For mapped objects, `objects_received = objects_stored + objects_quarantined`. The UI SHALL identify partial imports explicitly.
