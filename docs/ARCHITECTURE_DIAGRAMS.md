# Architecture and workflow diagrams

> Historical discovery baseline. Local implementation is now authorized and documented in [LOCAL_IMPLEMENTATION.md](LOCAL_IMPLEMENTATION.md); original source references below describe the audited snapshot. Remote execution remains pending review.

Date: 2026-11-20. Solid edges describe calls present in local source. Dashed edges describe owner-reported hosting or unresolved dependencies, or explicitly labeled proposals. These diagrams are source reconstructions, not observed production network traces. See CODEBASE_ANALYSIS.md for line references.

## Current architecture: verified source boundaries

```mermaid
flowchart LR
    Staff["Staff browser"] --> Pages["Static admin HTML and inline JS"]
    Pages --> Auth["Firebase Authentication\nproject configured in rudo-auth.js"]
    Pages --> Local["Browser storage\nprofile, preferences, unsafe session marker"]
    Pages --> Redis[("Primary Upstash Redis\nconversations, orders, referrals")]
    Pages -->|"direct text send with embedded credential"| Meta["Meta WhatsApp API"]
    Pages --> Risk["Client regex risk labels\nno durable escalation"]
    Flask["app.py Flask"] -->|"serves HTML/CSS/JS/images"| Pages
    Flask -->|"GET /api/qr-analytics"| Redis
    Caller["Any caller in source auth model"] -->|"POST /sendWhatsApp"| Flask
    Flask -->|"v19.0 send"| Meta
    Meta -->|"POST /webhook if configured"| Flask
    Flask --> Logs["Raw payload/message logs\nno local ingestion persistence"]
    External["Unidentified external writer"] -.->|"writer must be confirmed"| Redis
    Host["Namecheap cPanel\nowner-reported provenance"] -.-> Flask
    Cake["Separate cake_orders.html"] --> CakeRedis[("Second Redis host\norders, proof/design images")]
```

No dashboard fetch to `/sendWhatsApp` or `/api/qr-analytics` was found. An edge from Meta to Flask is a supported handler, not proof it is the active registered callback. No local AI path was found.

## Current health-data flow and privacy boundaries

```mermaid
flowchart TD
    P["WhatsApp patient content"] --> M["Meta"]
    M --> H["Local webhook handler, when invoked"]
    H --> L["Unfiltered application logs"]
    X["External writer, provenance unresolved"] -.-> R[("Redis: phone-keyed history and loose JSON")]
    R -->|"browser bearer capability"| B["Full records in browser memory"]
    B --> D["Dashboard / analytics / orders"]
    B --> T["Regex flags and display IDs\ncomputed in browser"]
    B --> U["UI masks some phone text\nraw data still delivered"]
    B -->|"outbound message"| M
    B -->|"whole conversation or order SET"| R
    D --> E["Local JSON metric download"]
```

Phone masking in a display is not authorization or anonymization. Exported dashboard metrics are computed UI values, not verified database reports.

## Current administrator login and dashboard sequence

```mermaid
sequenceDiagram
    actor A as Administrator
    participant B as Browser
    participant F as Firebase
    participant S as Browser storage
    participant R as Redis REST
    A->>B: Submit login / Google popup
    B->>F: signInWithEmailAndPassword / signInWithPopup
    alt Provider succeeds
        F-->>B: Firebase user
        B->>S: rudoSessionActive = true
        B->>B: Redirect to index2.html
        par UI auth check
            B->>F: onAuthStateChanged
        and Dashboard load starts independently
            B->>R: SCAN conversation* and orders:*
            B->>R: GET each value with embedded bearer
        end
        B->>B: Compute metrics and risk labels
    else Provider fails
        F-->>B: Error
        B-->>A: Form error
    end
    Note over B,S: Shared UI guard also accepts forged local marker without a Firebase user
    Note over B,R: No server-side staff authorization on this data path
```

## Current incoming webhook and administrator send

```mermaid
sequenceDiagram
    participant M as Meta or unsigned caller
    participant F as Local Flask
    participant L as Logs
    participant B as Admin browser
    participant R as Redis
    M->>F: POST /webhook
    F->>F: Parse JSON; take first message per change
    F->>L: Full payload, sender and text
    F-->>M: 200 success, or 500 exception
    Note over F,R: No local webhook persistence, dedup or AI reply
    B->>B: Append optimistic bot message
    B->>M: Direct Graph messages POST with browser credential
    M-->>B: Provider JSON
    alt Provider reports success
        B->>R: SET entire conversation array
        Note over B,R: Write HTTP status not checked; concurrent updates can be overwritten
    else Send failure
        B->>B: Append system failure message locally
    end
```

## Proposed Supabase architecture (not implemented)

```mermaid
flowchart LR
    B["Staff browser\nno privileged provider keys"] -->|"Firebase sign-in"| FA["Firebase Auth retained initially"]
    B -->|"HTTPS + verified identity token"| API["Protected Flask API\nstaff role, scope, validation"]
    API -->|"user-scoped token / reviewed DB role"| PG[("Supabase Postgres\nRLS, constraints, indexes")]
    API -->|"approved operation"| O[("Durable message outbox")]
    O --> W["Scoped sending worker"]
    W --> M["Meta WhatsApp"]
    M --> V["Single authoritative signed webhook\nraw-body HMAC check"]
    V --> I[("Durable event inbox\nunique event identity")]
    I --> P["Leased retryable processor"]
    P --> PG
    PG --> AU["Restricted audit metadata\nno health message bodies"]
    P -.-> AI["Existing bot / inference services\nonly after ownership and contract review"]
    P -.-> O
    API --> Priv["Private approved media storage\nonly if scoped in"]
    R[("Redis source\nread-only after approved cutover")] -.-> IMP["Approved encrypted backup\nvalidation and idempotent importer"]
    IMP -.-> PG
```

Staff Firebase-token forwarding requires configured Supabase third-party integration and explicit policies. Broad service keys bypass RLS; isolated worker/import operations must be separately authorized and minimized. Queue tables/worker hosting remain design proposals; do not assume Vercel or cPanel runs durable background jobs automatically.

## Proposed durable receive/send sequence (not implemented)

```mermaid
sequenceDiagram
    participant M as Meta
    participant H as Authoritative webhook
    participant DB as Postgres inbox and history
    participant W as Worker
    participant A as Protected staff API
    M->>H: Signed event batch
    H->>H: Verify exact raw-body signature and configured account
    H->>DB: Transactional insert of each event identity
    alt Durable acceptance succeeds
        DB-->>H: Accepted / already recorded
        H-->>M: 200 acknowledgement
        W->>DB: Atomic lease pending event
        W->>DB: Append message and versioned state
        W->>DB: Record completion; enqueue reply only when appropriate
    else Storage unavailable
        H-->>M: Retryable failure, no false durable acknowledgement
    end
    A->>A: Verify staff token, scope and idempotency key
    A->>DB: Persist outbound operation
    A-->>A: Return pending operation status to browser
    W->>DB: Lease outbound operation
    W->>M: Send using server-only credential
    alt Confirmed provider result
        M-->>W: Provider message ID / failure
        W->>DB: Store result and append ledger
    else Uncertain network outcome
        W->>DB: Mark unknown; reconcile before another send
    end
```

An idempotent local operation does not by itself guarantee exactly-once external delivery. Provider acceptance followed by process/network failure requires explicit uncertainty handling.

## Proposed entity relationships

```mermaid
erDiagram
    PATIENTS ||--o{ CONVERSATIONS : has
    CONVERSATIONS ||--o{ MESSAGES : contains
    PATIENTS o|--o{ ORDERS : linked_when_verified
    PATIENTS o|--o{ REFERRAL_EVENTS : linked_when_verified
    CLINICS o|--o{ REFERRAL_EVENTS : attributes
    CAMPAIGNS o|--o{ REFERRAL_EVENTS : attributes
    CONVERSATIONS ||--o{ MESSAGE_OUTBOX : sends
    CONVERSATIONS ||--o| CONVERSATION_STATE : tracks
    STAFF_MEMBERSHIPS ||--o{ FACILITY_MEMBERSHIPS : scopes
    MIGRATION_RUNS ||--o{ MIGRATION_RECORDS : reconciles
```

Nullable associations deliberately avoid fabricating a patient/clinic link when legacy records do not prove it. Meta account/tenant scoping, inbox and audit entities are specified in SUPABASE_MIGRATION_PLAN.md; this diagram shows the core relationships only.
