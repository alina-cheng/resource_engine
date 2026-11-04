"""AI maintenance detection engine.

Ported from the One Degree `onedegree_resource_engine` monorepo (the `contracts`,
`maintenance/extractor`, `maintenance/comparator`, and `maintenance/worker` packages).
The engine is framework-free: it depends only on this package plus `app.hsds.ids`.
It talks to the rest of `resource-engine` through three ports -- a website source,
a findings sink, and an HSDS record reader -- all supplied by
`app.services.maintenance_bridge`. `app.services.maintenance.MaintenanceService`
drives the engine and preserves the existing change-request / check_result write
contract so the API, UI, and existing tests are unchanged.
"""
