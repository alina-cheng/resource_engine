import copy
from app.adapters.base import Resource
from app.adapters.transform.hsds import parents
from app.services.store import TOP_LEVEL_TYPES
EMBEDDED = {
    "phone": "phones",
    "schedule": "schedules",
    "address": "addresses",
    "language": "languages",
    "service_area": "service_areas",
    "accessibility": "accessibility",
    "attribute": "attributes",
    "required_document": "required_documents",
    "contact": "contacts",
    "cost_option": "cost_options",
    "funding": "funding",
    "url": "additional_urls",
}


def _parent_of(kind: str, obj: dict, in_batch: dict[str, dict]) -> dict | None:
    if kind == "attribute":  # an attribute belongs to what it links to, not to its taxonomy term
        return in_batch.get(obj.get("link_id"))
    return next((in_batch[pid] for _, pid in parents(kind, obj) if pid in in_batch), None)


def assemble(objects: list[tuple[str, dict]]) -> tuple[list[Resource], list[tuple[str, dict, str]]]:
    """Fold flat (kind, object) pairs into documents. Returns the documents and any orphans."""
    copies = [(kind, copy.deepcopy(obj)) for kind, obj in objects]
    in_batch = {obj["id"]: obj for _, obj in copies}
    orphans = []
    for kind, obj in copies:
        if kind in TOP_LEVEL_TYPES:
            continue
        parent = _parent_of(kind, obj, in_batch)
        if kind not in EMBEDDED or parent is None:
            orphans.append((kind, obj, f"{kind} has no stored parent document"))
            continue
        parent.setdefault(EMBEDDED[kind], []).append(obj)

    resources = []
    for kind, obj in copies:
        if kind not in TOP_LEVEL_TYPES:
            continue
        org_id = obj["id"] if kind == "organization" else obj.get("organization_id")
        if kind == "service_at_location":
            org_id = in_batch.get(obj.get("service_id"), {}).get("organization_id")
        resources.append(Resource(kind, obj["id"], org_id, obj))
    return resources, orphans

