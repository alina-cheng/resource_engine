"""Run-scoped ID indexes must preserve public IDs and import transaction behavior."""
import copy
import json
from unittest.mock import patch
from uuid import uuid4

from app.adapters.base import Mapped, MappingError, Resource, SourceConfig
from tests.helpers import ODRS, SAMPLES, make_container


def test_existing_json_is_parsed_once_per_run_and_index_is_rebuilt_for_each_run():
    c = make_container()
    assert c.ingest.run(ODRS)["stored"] == 50
    before = c.store.counts()
    existing = c.db.one("SELECT COUNT(*) AS n FROM resource WHERE source='odrs' AND deleted=0")["n"]
    with patch.object(c.ingest, "_build_identity_maps", wraps=c.ingest._build_identity_maps) as build, \
         patch("app.services.ingest.json", wraps=json) as ingest_json:
        for _ in range(2):
            result = c.ingest.run(ODRS)
            assert (result["created"], result["updated"], result["unchanged"], result["quarantined"]) == (0, 0, 50, 0)
        assert build.call_count == 2
        assert ingest_json.loads.call_count == 2 * existing
    assert c.store.counts() == before


def test_cached_index_preserves_legacy_ids_and_all_relationships_without_more_queries():
    c = make_container()
    old = {kind: str(uuid4()) for kind in ("organization", "service", "location", "service_at_location")}
    new = {kind: str(uuid4()) for kind in old}
    rows = []
    candidates = []
    for kind in old:
        data = {"id": new[kind], "x_resource_engine": {"source": {"record_id": kind}}}
        if kind == "service":
            data.update(organization_id=new["organization"], phones=[{"service_id": new["service"]}])
        elif kind == "service_at_location":
            # Legacy links may have no native ID; match their aliased parents instead.
            data.update(service_id=new["service"], location_id=new["location"])
            data["x_resource_engine"]["source"] = None
        stored = copy.deepcopy(data)
        stored["id"] = old[kind]
        if kind == "service_at_location":
            stored.update(service_id=old["service"], location_id=old["location"])
        rows.append({"id": old[kind], "type": kind, "data": json.dumps(stored)})
        candidates.append(Resource(kind, new[kind], new["organization"], data))
    with patch.object(c.db, "q", return_value=rows):
        index = c.ingest._build_identity_maps("odrs")
    mapped = Mapped("record", candidates)
    with patch.object(c.db, "q", side_effect=AssertionError("Cached remapping must not query the database")):
        c.ingest._preserve_public_ids(mapped, "odrs", index)
    actual = {r.type: r for r in mapped.resources}
    for kind in old:
        assert actual[kind].id == actual[kind].data["id"] == old[kind]
        assert actual[kind].org_id == old["organization"]
    assert actual["service"].data["organization_id"] == old["organization"]
    assert actual["service"].data["phones"][0]["service_id"] == old["service"]
    assert actual["service_at_location"].data["service_id"] == old["service"]
    assert actual["service_at_location"].data["location_id"] == old["location"]


def test_rolled_back_shared_objects_are_still_imported_by_the_next_record():
    c = make_container()
    first = json.loads((SAMPLES / "BayesExport_20250729.json").read_text())["opportunities"][0]
    second = copy.deepcopy(first)
    second["id"] = str(first["id"]) + "-second"
    path = c.settings.data_dir / "retry-shared.json"
    path.write_text(json.dumps({"opportunities": [first, second]}))
    original = c.store.ingest_upsert
    failed = False

    def fail_first_service(t, source, native_id, fetched_at, resource, run_id):
        nonlocal failed
        if resource.type == "service" and not failed:
            failed = True
            raise MappingError("Fail after writing the shared organization in the transaction")
        return original(t, source, native_id, fetched_at, resource, run_id)

    with patch.object(c.store, "ingest_upsert", side_effect=fail_first_service):
        result = c.ingest.run(SourceConfig("odrs", "odrs", str(path)))
    assert (result["status"], result["received"], result["stored"], result["quarantined"]) == ("completed", 2, 1, 1)
    services = c.store.all_of_type("service")
    assert len(services) == 1
    assert services[0]["data"]["x_resource_engine"]["source"]["record_id"] == str(second["id"])
    assert c.store.get(services[0]["org_id"]) is not None
