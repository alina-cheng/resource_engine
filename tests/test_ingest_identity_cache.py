"""Guard against rebuilding source identity indexes for every record."""
import json
from unittest.mock import patch

from tests.helpers import ODRS, make_container


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
