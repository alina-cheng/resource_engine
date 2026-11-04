# Source-to-HSDS mapping (as implemented)

## ODRS (`app/adapters/odrs.py`)
| ODRS | HSDS | Notes |
|---|---|---|
| opportunity.id | service.id (UUIDv5) | native id kept in `x_resource_engine.source` and `resource_source` |
| title, description (HTML stripped) | service.name, description | |
| organization | organization | **no description in ODRS**: policy `fallback` writes "<name> (description not available)" and flags `description_missing`; policy `quarantine` rejects the record |
| last_verified_at / updated_at | service.assured_date / last_modified | |
| unavailable_at | service.status | any value → `inactive` |
| properties.elig-description | eligibility_description | |
| elig-age-or-over / -under | minimum_age / maximum_age | strings → numbers |
| elig-documentation | required_document (split on `;`) | |
| cost-free, cost-pay, cost-note | fees_description | |
| lang-* | language | `lang-all-languages-by-interpreter` → interpretation_services |
| service-county-*, elig-city/county-resident | service_area | |
| ada-accessible(+notes) | accessibility on each location | ADA is service-level in ODRS but location-level in HSDS; shared locations make this lossy (see shared_disagreements) |
| action-signup-url | service.url | |
| access_instructions, is_appointment | application_process | |
| areas > categories > tags | taxonomy "One Degree" + attribute | tags attach under the first category (ODRS does not say which) |
| elig-*, community-*, citizenship-*, gender-* flags | taxonomy "One Degree Eligibility" + attribute | |
| phones, locations[].phones | phone | extension split from number; de-duplicated |
| locations[] | location, address, service_at_location | address omitted if address, city or ZIP missing (warning) |
| weekly schedule | schedule (WEEKLY, byday, opens_at/closes_at with UTC offset; the IANA zone is kept in x_resource_engine.local_schedule) | days with identical hours grouped; schedule notes kept as a notes schedule |
| attachments, images, rating*, slugs, translations | not mapped | stay in the raw store |

## NDP (`app/adapters/ndp.py`)
| NDP | HSDS | Notes |
|---|---|---|
| organization (record) | organization | description HTML stripped; same gap policy |
| services[] | service | status from meta.status |
| locations[], addresses[] | location, address | `mailing` → `postal`; country name → ISO code; address omitted if incomplete |
| servicesAtLocations / locationIds | service_at_location | |
| taxonomy[] (up to 6 levels + code) | taxonomy "211 NDP Taxonomy" + attribute | parent chain from levels 1..6, code on the leaf |
| schedules[].open[] | schedule | same grouping and offsets as ODRS |
| eligibility.description, documents.description, fees, languages.description | eligibility_description, required_document, fees_description, language | text split on `;` and `,` |
| serviceAreas[] | service_area | |
| meta.lastVerified / lastUpdated | assured_date / last_modified | |

## Rules applied to every record
Empty properties omitted; UUIDv5 ids; every object validated before storage; one source record is stored or quarantined as a unit.
