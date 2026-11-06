"""Original engine's object validation with parent-failure cascade."""
from .hsds import parents, validate


def partition(objects):
    bad = {}
    for kind, obj in objects:
        errors = validate(kind, obj)
        if errors:
            bad[obj["id"]] = (kind, obj, errors)
    in_batch = {obj["id"] for _, obj in objects}
    changed = True
    while changed:
        changed = False
        for kind, obj in objects:
            if obj["id"] in bad:
                continue
            for parent_kind, parent_id in parents(kind, obj):
                if parent_id in bad:
                    reason = f"parent {parent_kind} {parent_id} was quarantined"
                elif parent_id not in in_batch:
                    reason = f"parent {parent_kind} {parent_id} is missing from source record"
                else:
                    continue
                bad[obj["id"]] = (kind, obj, [reason])
                changed = True
                break
    return [(k, obj) for k, obj in objects if obj["id"] not in bad], list(bad.values())
