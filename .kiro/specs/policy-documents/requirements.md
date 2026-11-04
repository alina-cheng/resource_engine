# Requirements: Policy documents for chat

Traces to: BR-10

## User story
As a provider, I upload policy PDFs so the assistant can answer eligibility questions with citations.

## Acceptance criteria (EARS)
1. WHEN a document is uploaded THE SYSTEM SHALL store it, extract text and split it into chunks.
2. WHEN a provider uploads a document THE SYSTEM SHALL keep it pending until an admin approves it.
3. WHEN a policy question is asked THE SYSTEM SHALL answer from approved public documents and cite title and effective date.
4. IF no document answers the question THEN THE SYSTEM SHALL say so and suggest contacting the provider.
5. IF a PDF has no text layer THEN THE SYSTEM SHALL record that OCR is needed and SHALL NOT approve it.
