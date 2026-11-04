# Detailed Design

## 1. Architecture (AWS)
```mermaid
flowchart LR
  subgraph Users
    S[Help seeker]:::u --- P[Provider]:::u --- A[Admin]:::u
  end
  Users -->|HTTPS| ALB[Application Load Balancer]
  ALB --> WEB[ECS Fargate: Flask + UI]
  WEB --> DB[(Aurora PostgreSQL Serverless v2)]
  WEB --> S3[(S3: raw payloads, policy documents)]
  WEB --> BR[Amazon Bedrock]
  WEB --> TX[Textract]
  WEB --> COG[Cognito]
  WEB -. optional .-> OS[(OpenSearch)]
  EB[EventBridge Scheduler] -->|RunTask| JOB[ECS Fargate one-off task: import / maintenance]
  JOB --> DB
  JOB --> S3
  JOB --> BR
  JOB -->|sample or live HTTP| WEBSITES[Organization websites]
  JOB -->|HTTP| SRC[ODRS API / NDP API]
  API[Other systems] -->|Bearer API key| ALB
  classDef u fill:#e3f0f4,stroke:#1b6e8c
```

## 2. Components
```mermaid
flowchart TB
  subgraph web[app/web]
    R1[routes_app: seeker, provider, admin]
    R2[routes_hsds: API-key HSDS API]
  end
  subgraph services[app/services]
    ING[IngestService] --> ADP[Adapters: odrs, ndp]
    ING --> STORE[HsdsStore: validate, history, reconcile]
    MAINT[MaintenanceService] --> WSRC[WebsiteSource sample/live]
    MAINT --> EXT[Extractor rules/LLM]
    MAINT --> CR[ChangeRequests]
    CHAT[ChatEngine] --> SRCH[SearchService]
    CHAT --> SEEK[SeekerService]
    DOCS[DocumentService] --> SRCH
    CR --> STORE
  end
  R1 --> services
  R2 --> STORE
  R2 --> SRCH
  STORE --> VAL[HsdsValidator + schemas]
  STORE --> DBL[(Database: SQLite/PostgreSQL)]
  ING --> BLOB[(BlobStore: disk/S3)]
  DOCS --> BLOB
  JOBS[app/jobs: runner, CLI] --> ING
  JOBS --> MAINT
```

## 3. Data flow: import and reconciliation
```mermaid
sequenceDiagram
  participant Sch as Scheduler / Admin
  participant I as IngestService
  participant A as Adapter
  participant S as HsdsStore
  participant Q as Quarantine
  Sch->>I: run(source)
  I->>A: fetch()
  A-->>I: RawBatch (bytes + records)
  I->>I: store raw bytes (as received)
  loop each source record
    I->>A: map(record)
    A-->>I: HSDS objects
    I->>S: validate all objects
    I->>I: partition valid objects; cascade invalid-parent failures
    I->>Q: preserve held objects + reasons
    I->>S: accepted graph + quarantine evidence + conflicts in one transaction
    S-->>I: created / updated / clashes / partial
  end
  I->>I: assert source-record balance and mapped-object balance separately
```

## 4. Data flow: AI maintenance and approval
```mermaid
sequenceDiagram
  participant Sch as Scheduler / Admin
  participant M as MaintenanceService
  participant W as WebsiteSource
  participant E as Extractor
  participant CR as ChangeRequests
  participant Adm as Admin UI
  participant S as HsdsStore
  Sch->>M: run(all | one service)
  M->>W: fetch(org website)
  W-->>M: page or failure
  alt failure
    M->>M: actively_bad or check_failed finding
  else page
    M->>E: extract facts with snippets
    M->>M: compare facts, categorise
    M->>CR: create ai_finding (evidence required)
  end
  Adm->>CR: approve / reject
  CR->>CR: claim pending decision and lock baseline in one transaction
  CR->>S: apply_patch (validate, history)
```

## 5. Chat and request flow
```mermaid
sequenceDiagram
  participant V as Visitor
  participant C as ChatEngine
  participant U as Auth
  V->>C: "I need rental assistance"
  C-->>V: ask to create a profile (no provider data)
  V->>U: register
  V->>C: resume(session)
  C-->>V: top matches (diversified, nearest first)
  V->>C: confirm(service)
  alt no sharing consent
    C-->>V: 409 consent_required -> dialog
  else consent
    C->>C: create help_request (open)
  end
```
Provider side: `provider_needs` lists direct requests and unassigned needs whose text matches the provider's services; contact details appear only after the provider accepts.

## 6. Deployment view
One VPC, two public subnets (ALB, Fargate tasks; no NAT) and two private subnets (Aurora). Security groups: ALB open on 80/443; app only from ALB; database only from app. Scheduled jobs use the same task definition with a command override.

`infra/bootstrap` prepares encrypted/versioned state and repository-scoped OIDC. Workshop access uses expiring event credentials and must follow event region/service restrictions. Web job starts return a durable job ID and admin UI polls status; one-off ECS tasks read stored parameters. Cognito first-password/MFA challenges complete before application login. `schema_migration` tracks workflow/compatibility upgrades; resource IDs/history survive upgrades.

## 7. Design decisions
See `docs/decisions.md`.
