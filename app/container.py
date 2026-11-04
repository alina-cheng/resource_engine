"""Composition root: builds every service once. Swapping a backend (SQLite->Aurora, mock->Bedrock,
sample->live websites, memory->OpenSearch, disk->S3, local->Cognito) happens here, driven by settings."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from app.adapters.registry import load_source_configs
from app.config import Settings, load_settings
from app.db import Database
from app.hsds.validator import HsdsValidator
from app.services.blob import build_blob_store
from app.services.chat import ChatEngine
from app.services.documents import DocumentService
from app.services.extract import build_extractor
from app.services.ingest import IngestService
from app.services.llm import build_llm
from app.services.maintenance import MaintenanceService
from app.services.proposals import ChangeRequests
from app.services.search import SearchService
from app.services.seekers import SeekerService
from app.services.store import HsdsStore
from app.services.users import UserService, build_auth
from app.services.website import build_website_source


@dataclass
class Container:
    settings: Settings
    db: Database
    validator: HsdsValidator
    store: HsdsStore
    proposals: ChangeRequests
    blob: Any
    ingest: IngestService
    search: SearchService
    users: UserService
    auth: Any
    llm: Any
    maintenance: MaintenanceService
    documents: DocumentService
    seekers: SeekerService
    chat: ChatEngine
    jobs: Any = None

    def sources(self):
        return load_source_configs(self.settings.sources_path)

    def ingest_all(self, trigger="scheduled", who="scheduler", only: str | None = None) -> list[dict]:
        return [self.ingest.run(c, trigger, who) for c in self.sources() if c.enabled and (only in (None, c.name))]


def build_container(settings: Settings | None = None) -> Container:
    s = settings or load_settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(s.database_url)
    db.init_schema()
    validator = HsdsValidator(s.hsds_schema_dir, s.hsds_version)
    store = HsdsStore(db, validator)
    proposals = ChangeRequests(db, store)
    blob = build_blob_store(s)
    search = SearchService(s, db, store)
    users = UserService(db)
    llm = build_llm(s)
    maintenance = MaintenanceService(s, db, store, proposals, build_website_source(s), build_extractor(llm), llm)
    seekers = SeekerService(db, search, store)
    c = Container(
        settings=s, db=db, validator=validator, store=store, proposals=proposals, blob=blob,
        ingest=IngestService(s, db, store, blob, proposals), search=search, users=users, auth=build_auth(s, users),
        llm=llm, maintenance=maintenance, documents=DocumentService(s, db, blob), seekers=seekers,
        chat=ChatEngine(s, db, store, search, llm, seekers))
    from app.jobs.runner import JobRunner
    c.jobs = JobRunner(c)
    return c
