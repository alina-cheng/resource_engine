# Design: Help seeker chat and profile

- `app/services/chat.py` intent order: crisis, about, policy, need, clarify.
- `app/services/seekers.py` profile and requests; `app/services/search.py` query expansion and BM25.

See `docs/detailed-design.md` for diagrams and `docs/technical-spec.md` for algorithms.
