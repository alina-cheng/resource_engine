"""Preserve local schedule context outside HSDS's numeric timezone property."""
import copy
from datetime import datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def normalize_document(data, kind=None, timezone="America/Los_Angeles"):
    out = copy.deepcopy(data)
    if kind == "taxonomy_term" and not out.get("description"):
        out["description"] = out.get("name", "Description not available")
        out.setdefault("x_resource_engine", {}).setdefault("flags", []).append("description_missing")

    def visit(node):
        if isinstance(node, list):
            for child in node:
                visit(child)
        elif isinstance(node, dict):
            if "opens_at" in node or "closes_at" in node:
                zone = node.get("x_resource_engine", {}).get("local_schedule", {}).get("timezone") or (
                    node.get("timezone") if isinstance(node.get("timezone"), str) else timezone)
                local = node.setdefault("x_resource_engine", {}).setdefault("local_schedule", {"timezone": zone})
                for field in ("opens_at", "closes_at"):
                    if node.get(field):
                        raw = node[field][:5]
                        local[field] = raw  # A reviewed time edit must supersede retained metadata.
                        try:
                            moment = datetime.combine(datetime.now(ZoneInfo(zone)).date(), time.fromisoformat(raw), ZoneInfo(zone))
                        except (ValueError, ZoneInfoNotFoundError):
                            continue  # Leave invalid input visible for object-level quarantine.
                        offset = moment.strftime("%z")
                        node[field] = f"{moment:%H:%M}{offset[:3]}:{offset[3:]}"
                if isinstance(node.get("timezone"), str):
                    node.pop("timezone")
            for key, child in list(node.items()):
                if key != "x_resource_engine":
                    visit(child)
    visit(out)
    return out
