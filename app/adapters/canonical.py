"""Use the original engine's transforms and IDs, retaining FINAL's richer fields."""
import copy

from app.adapters.base import Mapped, MappingError
from app.adapters.transform import ndp, odrs
from app.adapters.transform.assemble import EMBEDDED, assemble
from app.adapters.transform.hsds import clean
from app.adapters.transform.partition import partition
from app.hsds.normalize import normalize_document

EXTRA_FIELDS = {
    "languages", "service_areas", "required_documents", "interpretation_services",
    "accessibility", "attributes",
}


def map_record(adapter, record):
    mapper = {"odrs": odrs, "ndp": ndp}[adapter.config.adapter]
    if adapter.name != mapper.SOURCE:
        raise MappingError("source name must match the canonical transform")
    try:
        enriched = adapter._enriched_map(record)
        unique = {}
        for kind, obj in mapper.map(record):
            unique.setdefault((kind, obj["id"]), (kind, obj))
        pairs = [(kind, clean(normalize_document(obj, kind, adapter.settings.default_timezone)))
                 for kind, obj in unique.values()]
        pairs, held = partition(pairs)
        resources, orphans = assemble(pairs)
        if orphans:
            raise MappingError(str(orphans))
        def key(resource):
            source = resource.data.get("x_resource_engine", {}).get("source", {})
            return resource.type, source.get("record_id")
        baseline = {key(r): r for r in resources if key(r)[1] is not None}
        aliases = {r.id: baseline[key(r)].id for r in enriched.resources if key(r) in baseline}

        def relink(value):
            if isinstance(value, dict):
                return {k: relink(v) for k, v in value.items()}
            if isinstance(value, list):
                return [relink(v) for v in value]
            return aliases.get(value, value) if isinstance(value, str) else value

        for extra in enriched.resources:
            base = baseline.get(key(extra)) if key(extra)[1] is not None else None
            if base:
                for field in EXTRA_FIELDS:
                    if field in extra.data and field not in base.data:
                        base.data[field] = relink(copy.deepcopy(extra.data[field]))
                if base.type == "organization":
                    # Keep the explicit description-gap policy and flags from FINAL.
                    base.data["description"] = extra.data["description"]
                    base.data["x_resource_engine"] = relink(extra.data["x_resource_engine"])
            elif extra.type in {"taxonomy", "taxonomy_term"} and adapter.name == "odrs":
                resources.append(extra)
        for resource in resources:
            resource.data = clean(normalize_document(resource.data, resource.type,
                                                     adapter.settings.default_timezone))
        # Validate enrichment using the same object/parent rules as the original transform.
        flattened = {}
        def unfold(kind, obj):
            obj = copy.deepcopy(obj)
            for child_kind, field in EMBEDDED.items():
                for child in obj.pop(field, []):
                    unfold(child_kind, child)
            flattened.setdefault((kind, obj["id"]), (kind, obj))
        for resource in resources:
            unfold(resource.type, resource.data)
        good, additional_held = partition(list(flattened.values()))
        resources, orphans = assemble(good)
        if orphans:
            raise MappingError(str(orphans))
        return Mapped(mapper.native_id(record), resources, enriched.warnings,
                      held + additional_held, len(flattened) + len(held))
    except (KeyError, TypeError, ValueError) as error:
        raise MappingError(str(error)) from error
