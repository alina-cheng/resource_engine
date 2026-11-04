"""211 National Data Platform (NDP) -> HSDS. Built against the supplied samples
(national-data-platform-sample-1/2.json); the real NDP format is not available to teams."""
from __future__ import annotations
from typing import Any

from app.adapters.base import Mapped, MappingError, Resource, SourceAdapter
from app.adapters.common import (DAY_CODES, TaxonomyBuilder, clean, country_code, html_to_text, norm_time,
                                 phone, split_items, weekly_schedules)
from app.hsds.ids import make_id

STATUS = {"active": "active", "inactive": "inactive", "defunct": "defunct"}
ADDR_TYPE = {"physical": "physical", "mailing": "postal", "postal": "postal", "virtual": "virtual"}


def _intervals(schedules: list[dict]) -> tuple[dict, str | None]:
    out: dict[str, list[tuple[str, str]]] = {}
    notes = None
    for s in schedules or []:
        for slot in s.get("open") or []:
            d = DAY_CODES.get(str(slot.get("day", "")).lower())
            o, c = norm_time(slot.get("opensAt")), norm_time(slot.get("closesAt"))
            if d and o and c:
                out.setdefault(d, []).append((o, c))
        if not s.get("open") and s.get("description"):
            notes = s["description"]
    return out, notes


class NdpAdapter(SourceAdapter):
    def parse_page(self, data: Any) -> list[dict]:
        return data.get("data", [])

    def native_id(self, record: dict) -> str:
        return str(record["id"])

    def fetch_http(self, url, since):  # pragma: no cover - live API
        import os
        import requests
        from app.adapters.base import RawBatch
        headers = {}
        if self.config.options.get("bearer_env"):
            headers["Authorization"] = f"Bearer {os.environ.get(self.config.options['bearer_env'], '')}"
        skip, take = 0, int(self.config.options.get("take", 100))
        while True:
            params = {"skip": skip, "take": take}
            if since:
                params["lastUpdated"] = since
            r = requests.get(url, headers=headers, params=params, timeout=60)
            r.raise_for_status()
            data = r.json()
            recs = self.parse_page(data)
            if not recs:
                return
            yield RawBatch(f"skip-{skip}", r.content, recs)
            skip += take
            if skip >= (data.get("input") or {}).get("countAvailable", 0):
                return

    def map(self, rec: dict) -> Mapped:
        src, tz = self.name, self.settings.default_timezone
        if not rec.get("id") or not rec.get("name"):
            raise MappingError("organization has no id/name")
        warnings: list[str] = []
        resources: list[Resource] = []
        org_id = make_id(src, "organization", rec["id"])
        desc = html_to_text(rec.get("description"))
        flags = []
        if not desc:
            if self.settings.org_description_policy == "quarantine":
                raise MappingError("organization.description is required by HSDS and the source has none")
            desc, flags = f"{rec['name']} (description not available)", ["description_missing"]
        olink = {"organization_id": org_id}
        ophones = [p for p in (phone(src, org_id, olink, ph.get("number"), ext=ph.get("extension"),
                                     ptype=ph.get("type") if ph.get("type") in ("voice", "fax", "text", "hotline", "tty") else
                                     ("fax" if ph.get("type") == "fax" else "voice"),
                                     description=ph.get("description") or ph.get("name"))
                                for ph in rec.get("phones") or []) if p]
        meta = rec.get("meta") or {}
        resources.append(Resource("organization", org_id, org_id, clean({
            "id": org_id, "name": rec["name"], "description": desc, "website": rec.get("url"),
            "email": rec.get("email"), "tax_status": rec.get("taxStatus"), "tax_id": rec.get("taxId"),
            "year_incorporated": rec.get("yearIncorporated"), "legal_status": rec.get("legalStatus"),
            "alternate_name": ", ".join(rec.get("alternateNames") or []), "phones": ophones,
            "x_resource_engine": {"source": {"system": src, "record_id": str(rec["id"])}, "flags": flags,
                                  "data_owner": rec.get("dataOwner")}})))

        # ---- taxonomy (up to 6 levels, with AIRS-style codes) -------------------------------------
        tax = TaxonomyBuilder(src, "211 NDP Taxonomy", "Taxonomy attached to services by the 211 National Data Platform")

        # ---- locations ------------------------------------------------------------------------------
        locs = {}
        for loc in rec.get("locations") or []:
            lid = make_id(src, "location", loc["id"])
            link = {"location_id": lid}
            addrs = []
            for a in loc.get("addresses") or []:
                if a.get("street") and a.get("city") and a.get("postalCode") and a.get("state"):
                    addrs.append(clean({"id": make_id(src, "address", lid, a.get("id") or a["street"]),
                                        "location_id": lid, "address_1": a["street"], "city": a["city"],
                                        "region": a.get("county"), "state_province": a["state"],
                                        "postal_code": str(a["postalCode"]), "country": country_code(a.get("country")),
                                        "address_type": ADDR_TYPE.get(a.get("type"), "physical")}))
                else:
                    warnings.append(f"location {loc['id']} address incomplete; omitted")
            lphones = [p for p in (phone(src, lid, link, ph.get("number"), ext=ph.get("extension"),
                                         description=ph.get("description")) for ph in loc.get("phones") or []) if p]
            iv, notes = _intervals(loc.get("schedules") or [])
            acc = loc.get("accessibility") or {}
            access = [clean({"id": make_id(src, "accessibility", lid), "location_id": lid,
                             "description": acc.get("description"),
                             "details": ", ".join(acc.get("types") or [])})] if acc.get("description") else []
            ltype = "physical" if addrs or loc.get("latitude") else "virtual"
            data = clean({"id": lid, "location_type": ltype, "name": loc.get("name"),
                          "description": loc.get("description"), "latitude": loc.get("latitude"),
                          "longitude": loc.get("longitude"), "transportation": loc.get("transportation"),
                          "addresses": addrs, "phones": lphones, "accessibility": access,
                          "schedules": weekly_schedules(src, lid, link, iv, tz, notes=notes),
                          "x_resource_engine": {"source": {"system": src, "record_id": str(loc["id"])}}})
            resources.append(Resource("location", lid, org_id, data))
            locs[loc["id"]] = lid

        # ---- services -------------------------------------------------------------------------------
        for s in rec.get("services") or []:
            sid = make_id(src, "service", s["id"])
            link = {"service_id": sid}
            attributes = []
            for t in s.get("taxonomy") or []:
                names = [t.get(f"taxonomyTermLevel{i}") for i in range(1, 7)]
                names = [n for n in names if n] or [t.get("taxonomyTerm")]
                leaf = tax.term_path(names, code=t.get("taxonomyCode"))
                if leaf:
                    attributes.append(tax.attribute(sid, leaf))
            iv, notes = _intervals(s.get("schedules") or [])
            sphones = [p for p in (phone(src, sid, link, ph.get("number"), ext=ph.get("extension"),
                                         ptype="fax" if ph.get("type") == "fax" else "voice",
                                         description=ph.get("description") or ph.get("name"))
                                   for ph in s.get("phones") or []) if p]
            langs = [{"id": make_id(src, "language", sid, n), "service_id": sid, "name": n}
                     for n in split_items((s.get("languages") or {}).get("description"), r"[;,/]| and ")]
            areas = []
            for sa in s.get("serviceAreas") or []:
                gc = (sa.get("geoComponents") or [{}])[0]
                name = sa.get("value") or gc.get("locality") or gc.get("county")
                if name:
                    areas.append(clean({"id": make_id(src, "service_area", sid, name), "service_id": sid,
                                        "name": name, "extent_type": sa.get("type")}))
            docs = [{"id": make_id(src, "required_document", sid, d), "service_id": sid, "document": d}
                    for d in split_items((s.get("documents") or {}).get("description"))]
            fees = s.get("fees") or {}
            smeta = s.get("meta") or {}
            status = STATUS.get(smeta.get("status") or meta.get("status") or "active", "inactive")
            resources.append(Resource("service", sid, org_id, clean({
                "id": sid, "organization_id": org_id, "name": s["name"],
                "alternate_name": ", ".join(s.get("alternateNames") or []),
                "description": html_to_text(s.get("description")), "url": s.get("url"), "email": s.get("email"),
                "status": status, "interpretation_services": s.get("interpretationServices"),
                "application_process": s.get("applicationProcess"),
                "fees_description": " ".join(x for x in [fees.get("type"), fees.get("description")] if x),
                "wait_time": s.get("waitTime"),
                "eligibility_description": (s.get("eligibility") or {}).get("description"),
                "accreditations": ", ".join(map(str, s.get("accreditations") or [])),
                "licenses": ", ".join(map(str, s.get("licenses") or [])),
                "assured_date": smeta.get("lastVerified"), "last_modified": smeta.get("lastUpdated"),
                "phones": sphones, "schedules": weekly_schedules(src, sid, link, iv, tz, notes=notes),
                "languages": langs, "service_areas": areas, "required_documents": docs, "attributes": attributes,
                "x_resource_engine": {"source": {"system": src, "record_id": str(s["id"])}}})))
            for lraw in s.get("locationIds") or []:
                lid = make_id(src, "location", lraw)
                if any(r.type == "location" and r.id == lid for r in resources):
                    salid = make_id(src, "service_at_location", s["id"], lraw)
                    resources.append(Resource("service_at_location", salid, org_id,
                                              {"id": salid, "service_id": sid, "location_id": lid}))
        if len(tax.resources) > 1:
            resources.extend(tax.resources)
        return Mapped(str(rec["id"]), resources, warnings)
