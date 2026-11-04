"""Writes the vendored HSDS 3.2.3 *subset* schemas into schemas/hsds/3.2.3/.

IMPORTANT: these files are a hand-authored subset built from the required-field
table in the technical document and the HSDS field reference. They are NOT the
official release files. For production, run `python scripts/fetch_hsds_schemas.py`
(needs network) to replace them with the official v3.2.3 files from
github.com/openreferral/specification. The code loads whatever is in the directory.
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "schemas" / "hsds" / "3.2.3"
UUID = {"type": "string", "format": "uuid"}
S = {"type": "string"}
I = {"type": "integer"}
N = {"type": "number"}
B = {"type": "boolean"}
D = {"type": "string"}  # dates kept as strings (ISO-8601); format checked in tests


def arr(ref):
    return {"type": "array", "items": {"$ref": f"{ref}.json"}}


OBJECTS = {
    "organization": (["id", "name", "description"], {
        "id": UUID, "name": S, "alternate_name": S, "description": {"type": "string", "minLength": 1},
        "email": S, "website": S, "tax_status": S, "tax_id": S, "year_incorporated": I,
        "legal_status": S, "logo": S, "uri": S,
        "phones": arr("phone"), "urls": arr("url"), "attributes": arr("attribute")}),
    "service": (["id", "name", "status"], {
        "id": UUID, "organization_id": UUID, "program_id": UUID, "name": S, "alternate_name": S,
        "description": S, "url": S, "email": S,
        "status": {"enum": ["active", "inactive", "defunct", "temporarily closed"]},
        "interpretation_services": S, "application_process": S, "fees_description": S, "wait_time": S,
        "accreditations": S, "licenses": S, "minimum_age": N, "maximum_age": N,
        "eligibility_description": S, "assured_date": S, "assurer_email": S, "last_modified": S,
        "phones": arr("phone"), "schedules": arr("schedule"), "languages": arr("language"),
        "service_areas": arr("service_area"), "required_documents": arr("required_document"),
        "cost_options": arr("cost_option"), "attributes": arr("attribute"), "urls": arr("url")}),
    "location": (["id", "location_type"], {
        "id": UUID, "location_type": {"enum": ["physical", "postal", "virtual"]}, "url": S, "name": S,
        "alternate_name": S, "description": S, "transportation": S, "latitude": N, "longitude": N,
        "external_identifier": S, "external_identifier_type": S,
        "addresses": arr("address"), "phones": arr("phone"), "accessibility": arr("accessibility"),
        "languages": arr("language"), "schedules": arr("schedule")}),
    "address": (["id", "address_1", "city", "state_province", "postal_code", "country", "address_type"], {
        "id": UUID, "location_id": UUID, "attention": S, "address_1": S, "address_2": S, "city": S,
        "region": S, "state_province": S, "postal_code": S, "country": S,
        "address_type": {"enum": ["physical", "postal", "virtual"]}}),
    "phone": (["id", "number"], {
        "id": UUID, "location_id": UUID, "service_id": UUID, "organization_id": UUID, "contact_id": UUID,
        "service_at_location_id": UUID, "number": S, "extension": N, "type": S, "language": S, "description": S}),
    "service_at_location": (["id"], {
        "id": UUID, "service_id": UUID, "location_id": UUID, "description": S,
        "phones": arr("phone"), "schedules": arr("schedule")}),
    "schedule": (["id"], {
        "id": UUID, "service_id": UUID, "location_id": UUID, "service_at_location_id": UUID,
        "valid_from": S, "valid_to": S, "dtstart": S, "timezone": S, "until": S, "count": I,
        "wkst": S, "freq": {"enum": ["WEEKLY", "MONTHLY"]}, "interval": I, "byday": S, "byweekno": S,
        "bymonthday": S, "byyearday": S, "description": S, "opens_at": S, "closes_at": S,
        "schedule_link": S, "attending_type": S, "notes": S}),
    "language": (["id"], {"id": UUID, "service_id": UUID, "location_id": UUID, "phone_id": UUID,
                          "name": S, "code": S, "note": S}),
    "accessibility": (["id"], {"id": UUID, "location_id": UUID, "description": S, "details": S, "url": S}),
    "service_area": (["id"], {"id": UUID, "service_id": UUID, "service_at_location_id": UUID, "name": S,
                              "description": S, "extent": S, "extent_type": S, "uri": S}),
    "required_document": (["id"], {"id": UUID, "service_id": UUID, "document": S, "uri": S}),
    "cost_option": (["id"], {"id": UUID, "service_id": UUID, "valid_from": S, "valid_to": S, "option": S,
                             "currency": S, "amount": N, "amount_description": S}),
    "attribute": (["id"], {"id": UUID, "link_id": UUID, "taxonomy_term_id": UUID, "link_type": S,
                           "link_entity": S, "value": S}),
    "url": (["id", "url"], {"id": UUID, "label": S, "url": S, "organization_id": UUID, "service_id": UUID}),
    "taxonomy": (["id", "name", "description"], {"id": UUID, "name": S, "description": S, "uri": S, "version": S}),
    "taxonomy_term": (["id", "name"], {"id": UUID, "code": S, "name": S, "description": S, "parent_id": UUID,
                                       "taxonomy": S, "taxonomy_id": UUID, "language": S, "term_uri": S}),
    "metadata": (["id", "last_action_date", "last_action_type", "field_name", "previous_value",
                  "replacement_value", "updated_by"], {
        "id": UUID, "resource_id": UUID, "last_action_date": S, "last_action_type": S, "field_name": S,
        "previous_value": S, "replacement_value": S, "updated_by": S}),
}

OUT.mkdir(parents=True, exist_ok=True)
for name, (required, props) in OBJECTS.items():
    schema = {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": f"{name}.json",
              "title": name, "type": "object", "required": required, "properties": props}
    (OUT / f"{name}.json").write_text(json.dumps(schema, indent=2) + "\n")
(OUT / "README.md").write_text(
    "Vendored HSDS 3.2.3 SUBSET (hand-authored). Replace with the official files via "
    "scripts/fetch_hsds_schemas.py before production use.\n")
print("wrote", len(OBJECTS), "schemas to", OUT)
