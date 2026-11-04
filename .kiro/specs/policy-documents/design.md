# Design: Policy documents for chat

- `app/services/documents.py`: pypdf, docx and text extraction; Textract fallback in AWS mode.
- Chunks indexed by `SearchService.search_chunks`; visibility and status filter retrieval.

See `docs/detailed-design.md` for diagrams and `docs/technical-spec.md` for algorithms.
