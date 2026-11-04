"""ODRS (One Degree legacy API / BayesExport) -> HSDS. Mapping follows technical doc section 4."""
from __future__ import annotations
import re
from typing import Any

from app.adapters.base import Mapped, MappingError, Resource, SourceAdapter
from app.adapters.common import (DAY_CODES, TaxonomyBuilder, clean, country_code, html_to_text, norm_time,
                                 phone, split_items, weekly_schedules)
from app.hsds.ids import make_id

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
ELIG_PREFIXES = ("elig-", "community-", "citizenship-", "gender-")
SKIP_ELIG = {"elig-description", "elig-documentation", "elig-age-or-over", "elig-age-or-under",
             "elig-city-resident", "elig-county-resident"}


def _truthy(v: Any) -> bool:
    return str(v).strip().lower() in ("true", "yes", "1")


def _title(key: str) -> str:
    return re.sub(r"[-_]+", " ", key).strip().capitalize()


class OdrsAdapter(SourceAdapter):
    def parse_page(self, data: Any) -> list[dict]:
        return data.get("opportunities", [])

    def native_id(self, record: dict) -> str:
        return str(record["id"])

    def fetch_http(self, url, since):  # pragma: no cover - live API
        import requests
        from app.adapters.base import RawBatch
        headers = {}
        token = self.config.options.get("bearer_env")
        if token:
            import os
            headers["Authorization"] = f"Bearer {os.environ.get(token, '')}"
        page = 1
        while url:
            r = requests.get(url, headers=headers, timeout=60)
            r.raise_for_status()
            data = r.json()
            yield RawBatch(f"page-{page}", r.content, self.parse_page(data))
            url = (data.get("paging") or {}).get("next_page")
            page += 1

    def map(self, opp: dict) -> Mapped:
        src = self.name
        org = opp.get("organization") or {}
        if not org.get("id") or not org.get("name"):
            raise MappingError("opportunity has no organization id/name")
        props = opp.get("properties") or {}
        tz = self.settings.default_timezone
        warnings: list[str] = []
        resources: list[Resource] = []

        # ---- organization (description is required by HSDS but absent in ODRS) --------------
        org_id = make_id(src, "organization", org["id"])
        flags = []
        description = html_to_text(org.get("description"))
        if not description:
            if self.settings.org_description_policy == "quarantine":
                raise MappingError("organization.description is required by HSDS and ODRS provides none")
            description = f"{org['name']} (description not available)"
            flags.append("description_missing")
        org_data = clean({"id": org_id, "name": org["name"], "description": description,
                          "website": org.get("website"),
                          "x_resource_engine": {"source": {"system": src, "record_id": str(org["id"])},
                                                "flags": flags}})
        resources.append(Resource("organization", org_id, org_id, org_data))

        # ---- service ---------------------------------------------------------------------------
        sid = make_id(src, "service", opp["id"])
        link = {"service_id": sid}
        tax = TaxonomyBuilder(src, "One Degree", "One Degree areas > categories > tags")
        elig_tax = TaxonomyBuilder(src, "One Degree Eligibility", "Eligibility and audience flags from ODRS properties")
        attributes = []
        # areas > categories > tags. ODRS does not say which category a tag belongs to, so tags are
        # placed under the first category (documented ambiguity); no cross-product is generated.
        areas, cats, tags = opp.get("areas") or [], opp.get("categories") or [], opp.get("tags") or []
        first_area = areas[0] if areas else None
        first_cat = cats[0] if cats else None
        for a in areas[1:]:
            attributes.append(tax.attribute(sid, tax.term_path([a])))
        for c in cats:
            attributes.append(tax.attribute(sid, tax.term_path([first_area, c])))
        for t in tags:
            attributes.append(tax.attribute(sid, tax.term_path([first_area, first_cat, t])))
        if first_area and not cats and not tags:
            attributes.append(tax.attribute(sid, tax.term_path([first_area])))
        for key, val in props.items():
            if key.startswith(ELIG_PREFIXES) and key not in SKIP_ELIG and _truthy(val):
                leaf = elig_tax.term_path([_title(key)])
                attributes.append(elig_tax.attribute(sid, leaf))
        attributes = list({a["id"]: a for a in attributes}.values())

        status = "inactive" if opp.get("unavailable_at") else "active"
        fees = []
        if _truthy(props.get("cost-free")):
            fees.append("Free")
        if props.get("cost-pay") and not _truthy(props.get("cost-pay")):
            fees.append(str(props["cost-pay"]))
        if props.get("cost-note"):
            fees.append(str(props["cost-note"]))
        steps = []
        for ai in opp.get("access_instructions") or []:
            bit = ai.get("instructions") or ""
            if ai.get("access_value"):
                bit = f"{bit} ({ai['access_value']})".strip()
            if bit:
                steps.append(bit)
        if opp.get("is_appointment") or _truthy(props.get("time-appointment-required")):
            steps.append("Appointment required.")

        def num(k):
            try:
                return float(props[k]) if k in props and str(props[k]).strip() != "" else None
            except ValueError:
                return None

        languages, interp = [], None
        for key, val in props.items():
            if key.startswith("lang-") and _truthy(val):
                if key == "lang-all-languages-by-interpreter":
                    interp = "Interpretation available in all languages"
                else:
                    name = _title(key[5:])
                    languages.append({"id": make_id(src, "language", sid, name), "service_id": sid, "name": name})
        areas = []
        for key, val in props.items():
            if key.startswith("service-county-") and _truthy(val):
                parts = key[len("service-county-"):].split("-")
                state, county = parts[0].title(), " ".join(parts[1:]).title()
                name = f"{county} County, {state}"
                areas.append({"id": make_id(src, "service_area", sid, name), "service_id": sid, "name": name})
        for key in ("elig-city-resident", "elig-county-resident"):
            if props.get(key) and not _truthy(props[key]):
                name = f"{props[key]} (residents)"
                areas.append({"id": make_id(src, "service_area", sid, name), "service_id": sid, "name": name})
        docs = [{"id": make_id(src, "required_document", sid, d), "service_id": sid, "document": d}
                for d in split_items(props.get("elig-documentation"), r";")]
        phones = [p for p in (phone(src, sid, link, ph.get("digits"), description=ph.get("phone_type"))
                              for ph in opp.get("phones") or []) if p]
        phones = list({p["id"]: p for p in phones}.values())
        emails = opp.get("emails") or []
        email = None
        if emails:
            e = emails[0]
            email = e.get("email") or e.get("address") if isinstance(e, dict) else str(e)
        sched_notes = (opp.get("schedule") or {}).get("notes")
        schedules = weekly_schedules(src, sid, link, {}, tz, notes=sched_notes) if sched_notes else []
        if opp.get("available_on") or opp.get("expires_on"):
            schedules.append(clean({"id": make_id(src, "schedule", sid, "validity"), **link,
                                    "valid_from": opp.get("available_on"), "valid_to": opp.get("expires_on")}))

        service = clean({
            "id": sid, "organization_id": org_id, "name": opp["title"],
            "description": html_to_text(opp.get("description")), "url": props.get("action-signup-url"),
            "email": email, "status": status, "interpretation_services": interp,
            "application_process": " ".join(steps), "fees_description": ". ".join(fees),
            "minimum_age": num("elig-age-or-over"), "maximum_age": num("elig-age-or-under"),
            "eligibility_description": props.get("elig-description"),
            "assured_date": opp.get("last_verified_at"), "last_modified": opp.get("updated_at"),
            "phones": phones, "schedules": schedules, "languages": languages, "service_areas": areas,
            "required_documents": docs, "attributes": attributes,
            "x_resource_engine": {"source": {"system": src, "record_id": str(opp["id"])}}})
        resources.append(Resource("service", sid, org_id, service))
        for builder in (tax, elig_tax):
            if len(builder.resources) > 1:          # taxonomy + at least one term
                resources.extend(builder.resources)

        # ---- locations ---------------------------------------------------------------------------
        for loc in opp.get("locations") or []:
            lid = make_id(src, "location", loc["id"])
            llink = {"location_id": lid}
            addresses = []
            if loc.get("address") and loc.get("city") and loc.get("zip_code"):
                addresses.append({"id": make_id(src, "address", lid), "location_id": lid,
                                  "address_1": loc["address"], **clean({"address_2": loc.get("unit")}),
                                  "city": loc["city"], "state_province": loc.get("state") or "CA",
                                  "postal_code": str(loc["zip_code"]), "country": country_code(None),
                                  "address_type": "physical"})
            elif loc.get("address") or loc.get("city"):
                warnings.append(f"location {loc['id']} has an incomplete address; address omitted")
            intervals: dict[str, list[tuple[str, str]]] = {}
            sch = loc.get("schedule") or {}
            for d in DAYS:
                o, c = norm_time(sch.get(f"{d}_start")), norm_time(sch.get(f"{d}_end"))
                if o and c:
                    intervals.setdefault(DAY_CODES[d], []).append((o, c))
            lphones = [p for p in (phone(src, lid, llink, ph.get("digits"), description=ph.get("phone_type"))
                                   for ph in loc.get("phones") or []) if p]
            access = []
            if props.get("ada-accessible") not in (None, ""):
                access.append(clean({"id": make_id(src, "accessibility", lid), "location_id": lid,
                                     "description": f"ADA accessible: {props['ada-accessible']}",
                                     "details": props.get("ada-accessible-notes")}))
            ldata = clean({"id": lid, "location_type": "physical", "name": loc.get("name"),
                           "latitude": loc.get("lat"), "longitude": loc.get("long"), "addresses": addresses,
                           "phones": lphones, "accessibility": access,
                           "schedules": weekly_schedules(src, lid, llink, intervals, tz, notes=sch.get("notes")),
                           "x_resource_engine": {"source": {"system": src, "record_id": str(loc["id"])}}})
            resources.append(Resource("location", lid, org_id, ldata))
            salid = make_id(src, "service_at_location", opp["id"], loc["id"])
            resources.append(Resource("service_at_location", salid, org_id,
                                      {"id": salid, "service_id": sid, "location_id": lid}))
        # de-duplicate taxonomy resources emitted twice
        seen, uniq = set(), []
        for r in resources:
            if (r.type, r.id) not in seen:
                seen.add((r.type, r.id))
                uniq.append(r)
        return Mapped(str(opp["id"]), uniq, warnings)
