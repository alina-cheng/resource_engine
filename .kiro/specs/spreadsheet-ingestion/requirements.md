# Requirements: Spreadsheet ingestion (stretch)

Traces to: BR-15

## User story
As a data partner, I send a spreadsheet and it is ingested without custom code.

## Acceptance criteria (EARS)
1. WHEN a spreadsheet is uploaded THE SYSTEM SHALL propose a column mapping using a model and ask a person to confirm it once per layout.
2. WHEN a layout packs details into one cell THE SYSTEM SHALL split them with model assistance and show the result for review.
3. THE SYSTEM SHALL pass the mapped records through the same validation and quarantine as other sources.
