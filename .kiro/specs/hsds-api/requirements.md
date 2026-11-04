# Requirements: HSDS REST API

Traces to: BR-11

## User story
As an engineer, I call a keyed API and receive HSDS JSON, optionally limited to one source.

## Acceptance criteria (EARS)
1. THE SYSTEM SHALL require an API key as a bearer token on every HSDS endpoint.
2. WHEN a key is scoped to a source THE SYSTEM SHALL return only that source's records.
3. WHEN a list is requested THE SYSTEM SHALL return the HSDS Page object with total_items, total_pages, page_number, size, first_page, last_page, empty and contents.
4. THE SYSTEM SHALL return nested service records that validate against the HSDS schema and SHALL hide extensions unless requested.
5. WHEN `search` is provided THE SYSTEM SHALL return services ranked by relevance.
6. THE SYSTEM SHALL store only a hash of each key and show the key once at creation.
