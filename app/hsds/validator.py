"""HSDS validation against a pinned schema directory.

Uses the `jsonschema` package when installed (production). Falls back to a small
built-in validator that supports the keyword subset used by the vendored schemas, so the
project also runs in minimal environments. Separate schema files are bundled into one
document per object ($ref "phone.json" -> "#/$defs/phone").
"""
from __future__ import annotations
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

try:  # pragma: no cover - depends on environment
    from jsonschema import Draft202012Validator, FormatChecker
except Exception:  # noqa: BLE001
    Draft202012Validator = None  # type: ignore
    FormatChecker = None  # type: ignore

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def bundle(schema_dir: Path, name: str) -> dict:
    """Inline relative file refs so a schema is one self-contained document."""
    defs: dict[str, Any] = {}

    def load(n: str) -> dict:
        return json.loads((schema_dir / f"{n}.json").read_text())

    def rewrite(node: Any) -> Any:
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k == "$ref" and isinstance(v, str) and v.endswith(".json") and "/" not in v:
                    ref = v[:-5]
                    if ref not in defs:
                        defs[ref] = {}  # placeholder to stop recursion
                        sub = rewrite(load(ref))
                        sub.pop("$schema", None)
                        sub.pop("$id", None)
                        defs[ref] = sub
                    out[k] = f"#/$defs/{ref}"
                else:
                    out[k] = rewrite(v)
            return out
        if isinstance(node, list):
            return [rewrite(x) for x in node]
        return node

    root = rewrite(load(name))
    if defs:
        root["$defs"] = {**root.get("$defs", {}), **defs}
    return root


class _MiniValidator:
    """Supports: type, required, properties, items, enum, const, format(uuid), pattern,
    minLength, minimum, maximum, allOf/anyOf/oneOf, $ref (local)."""

    def __init__(self, schema: dict):
        self.root = schema

    def iter_errors(self, inst: Any):
        yield from self._v(self.root, inst, "")

    def _resolve(self, ref: str) -> dict:
        node: Any = self.root
        for part in ref.lstrip("#/").split("/"):
            node = node[part]
        return node

    @staticmethod
    def _type_ok(t: str, v: Any) -> bool:
        return {
            "string": isinstance(v, str), "boolean": isinstance(v, bool), "null": v is None,
            "integer": isinstance(v, int) and not isinstance(v, bool),
            "number": isinstance(v, (int, float)) and not isinstance(v, bool),
            "array": isinstance(v, list), "object": isinstance(v, dict),
        }[t]

    def _v(self, s: dict, v: Any, path: str):
        if "$ref" in s:
            yield from self._v(self._resolve(s["$ref"]), v, path)
            return
        if "type" in s:
            types = s["type"] if isinstance(s["type"], list) else [s["type"]]
            if not any(self._type_ok(t, v) for t in types):
                yield (path, f"expected {'/'.join(types)}, got {type(v).__name__}")
                return
        if "enum" in s and v not in s["enum"]:
            yield (path, f"{v!r} is not one of {s['enum']}")
        if "const" in s and v != s["const"]:
            yield (path, f"must equal {s['const']!r}")
        if isinstance(v, str):
            if s.get("format") == "uuid" and not UUID_RE.match(v):
                yield (path, "not a valid UUID")
            if "pattern" in s and not re.search(s["pattern"], v):
                yield (path, f"does not match {s['pattern']}")
            if "minLength" in s and len(v) < s["minLength"]:
                yield (path, f"shorter than {s['minLength']}")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if "minimum" in s and v < s["minimum"]:
                yield (path, f"below minimum {s['minimum']}")
            if "maximum" in s and v > s["maximum"]:
                yield (path, f"above maximum {s['maximum']}")
        if isinstance(v, dict):
            for r in s.get("required", []):
                if r not in v or v[r] is None:
                    yield (f"{path}/{r}", "is required")
            for k, sub in s.get("properties", {}).items():
                if k in v and v[k] is not None:
                    yield from self._v(sub, v[k], f"{path}/{k}")
        if isinstance(v, list) and "items" in s:
            for i, item in enumerate(v):
                yield from self._v(s["items"], item, f"{path}/{i}")
        for kw in ("allOf",):
            for sub in s.get(kw, []):
                yield from self._v(sub, v, path)
        if "anyOf" in s and not any(not list(self._v(sub, v, path)) for sub in s["anyOf"]):
            yield (path, "does not match any allowed shape")
        if "oneOf" in s and sum(1 for sub in s["oneOf"] if not list(self._v(sub, v, path))) != 1:
            yield (path, "must match exactly one allowed shape")


class HsdsValidator:
    def __init__(self, schema_dir: Path, version: str = "3.2.3"):
        self.schema_dir = Path(schema_dir)
        self.version = version
        self._cache: dict[str, Any] = {}

    def _validator(self, name: str):
        if name not in self._cache:
            schema = bundle(self.schema_dir, name)
            if Draft202012Validator is not None:
                self._cache[name] = Draft202012Validator(schema, format_checker=FormatChecker())
            else:
                self._cache[name] = _MiniValidator(schema)
        return self._cache[name]

    def errors(self, object_type: str, data: dict) -> list[str]:
        """Return human-readable validation errors ([] when valid). Extensions (x_*) are ignored."""
        clean = {k: v for k, v in data.items() if not k.startswith("x_")}
        v = self._validator(object_type)
        out = []
        for e in v.iter_errors(clean):
            if isinstance(e, tuple):
                path, msg = e
            else:  # jsonschema ValidationError
                path, msg = "/" + "/".join(str(p) for p in e.absolute_path), e.message
            out.append(f"{object_type}{path}: {msg}")
        return out

    def is_valid(self, object_type: str, data: dict) -> bool:
        return not self.errors(object_type, data)

    def engine(self) -> str:
        return "jsonschema" if Draft202012Validator is not None else "builtin-subset"
