# Design: Help seeker chat and profile

- `app/services/chat.py` intent order: crisis, about, policy, need, clarify.
- `app/services/seekers.py` profile and requests; `app/services/search.py` query expansion and BM25.
- Cognito login first-password/MFA challenges are completed in the shared auth form before session/resume. Chat system prompt is inventoried in `docs/kiro-and-prompts-audit.md`; its wording and consent boundaries are unchanged by the integration.

See `docs/detailed-design.md` for diagrams and `docs/technical-spec.md` for algorithms.
