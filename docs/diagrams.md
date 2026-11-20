# InspectIQ — Mermaid diagrams

Mermaid.js source (renders on GitHub, mermaid.live, Notion). PNG versions are next to this file.

## 1. System architecture

![1. System architecture](1_architecture.png)

```mermaid
flowchart TB
    subgraph Users["Quality personnel (role-based login)"]
        direction LR
        I[Inspector]
        S[Supervisor]
        Q[Quality Manager]
        C[Compliance Officer]
    end

    subgraph FE["React frontend"]
        direction LR
        LF[Live Feed]
        RP[Reports + Editor]
        DB[Dashboard + AI Insights]
        CR[Compliance Rules]
        AL[Audit Log]
        AQ[Ask Quality AI]
    end

    subgraph BE["FastAPI backend"]
        AUTH[Auth + RBAC]
        INS[Inspection API + Simulator]
        REP[Report service]
        ANA[Analytics: SPC, Cpk, Pareto, drift]
        CMP[Compliance rule engine]
        GR[Guardrails: input + output]
        LLM[llm.py adapter]
        AUD[Audit logger]
    end

    subgraph DATA["Data"]
        direction LR
        SYN[(Synthetic data: sensors, camera, manual checks, history)]
        SQL[(SQLite: reports, rules, users, audit)]
    end

    EXT[[Provided LLM API]]

    Users --> FE
    FE -->|/api + token| AUTH
    AUTH --> INS & REP & ANA & CMP & AUD
    INS --> SYN
    REP --> ANA
    REP --> GR
    GR <--> LLM
    LLM <--> EXT
    REP --> CMP
    CMP --> SQL
    REP --> SQL
    AUD --> SQL
```

## 2. Report generation flow (guardrails + compliance)

![2. Report generation flow (guardrails + compliance)](2_report_generation.png)

```mermaid
sequenceDiagram
    autonumber
    actor U as Inspector
    participant FE as React (Reports page)
    participant API as FastAPI /api/reports
    participant RB as RBAC + Audit
    participant AG as Aggregator + Analytics
    participant GI as Input guardrails
    participant L as llm.py
    participant X as Provided LLM
    participant GO as Output guardrails
    participant CE as Compliance engine
    participant DB as SQLite

    U->>FE: Select line, shift, batch and click Generate
    FE->>API: POST /api/reports/generate (token)
    API->>RB: check role can generate, log action
    API->>AG: pull sensor, camera, manual-check data
    AG->>AG: compute stats, out-of-spec counts, Cpk, Pareto, patterns
    AG-->>API: facts JSON (all numbers computed by code)
    API->>GI: facts + inspector notes
    GI->>GI: mask names/PII, strip injection text, size cap
    GI->>L: chat_json(template prompt, cleaned facts, temperature 0.1)
    L->>X: request
    alt LLM down or filtered
        X-->>L: error
        L-->>API: fallback: stats-only report
    else success
        X-->>L: report JSON
        L-->>GO: report JSON
        GO->>GO: schema check, number check, defect-code whitelist
        GO->>GO: severity rules override, low-confidence flags
        GO-->>API: report + guardrail results
    end
    API->>CE: check report against active rulebook version
    CE-->>API: compliance score, pass/fail per rule
    API->>DB: save Draft report, rule version, guardrail log
    API->>RB: audit log entry
    API-->>FE: report + guardrail panel + compliance score + time taken
    FE-->>U: editable report
```

## 3. Report lifecycle and approval

![3. Report lifecycle and approval](3_report_lifecycle.png)

```mermaid
stateDiagram-v2
    [*] --> Draft: AI generates report
    Draft --> Draft: Inspector edits / AI rewrite (audit-logged)
    Draft --> InReview: Inspector submits
    InReview --> Draft: Supervisor requests changes
    InReview --> Reviewed: Supervisor reviews
    Reviewed --> Blocked: Blocking compliance rule fails
    Blocked --> Draft: Fix issues
    Reviewed --> Approved: Quality Manager approves (all blocking rules pass)
    Approved --> [*]: Locked, PDF exported
```

## 4. Editing a compliance rule

![4. Editing a compliance rule](4_compliance_edit.png)

```mermaid
sequenceDiagram
    autonumber
    actor C as Compliance Officer
    participant FE as Compliance Rules page
    participant API as FastAPI /api/compliance
    participant DB as SQLite
    participant CE as Compliance engine
    participant AUD as Audit log

    C->>FE: Change "submit within 24 h" to 12 h
    FE->>API: PUT /api/compliance/rules/R-001
    API->>API: check role (Compliance or QM only), validate settings
    API->>DB: save rule as new version (old version kept)
    API->>AUD: who, what changed, old vs new value, time
    API->>CE: re-check open reports with new rulebook version
    CE-->>API: report RPT-042 now FAILS R-001
    API-->>FE: saved + affected reports
    FE-->>C: rule updated, 1 report now non-compliant
```

## 5. Data model (SQLite tables + synthetic CSV data)

![5. Data model (SQLite tables + synthetic CSV data)](5_data_model.png)

```mermaid
erDiagram
    USERS ||--o{ REPORTS : creates
    USERS ||--o{ AUDIT_LOG : performs
    USERS ||--o{ LLM_CALLS : triggers
    REPORTS ||--o{ REPORT_VERSIONS : "has versions"
    RULE_VERSIONS }o--|| META : "rulebook_version"
    LOTS ||--o{ MEASUREMENTS : contains
    LOTS ||--o{ DETECTIONS : contains
    LOTS ||--o{ MANUAL_CHECKS : contains
    LOTS ||--o| REPORTS : "reported in"

    USERS { string username PK string name string role string password_hash }
    REPORTS { string id PK string line string lot string shift string status json data }
    REPORT_VERSIONS { int version string changed_by string change_note json data }
    RULE_VERSIONS { string rule_id int version int rulebook_version string changed_by json data }
    META { string key PK string value }
    AUDIT_LOG { datetime ts string username string action string entity json before json after }
    LLM_CALLS { datetime ts string purpose string model string prompt_version int latency_ms bool ok json guardrails }
    LOTS { string lot PK string line string shift datetime shift_end int lot_size int sampled }
    MEASUREMENTS { string part_serial string feature float value float lsl float usl string gauge_id }
    DETECTIONS { string part_serial string defect_code float confidence string severity string image_id }
    MANUAL_CHECKS { string inspector_id string item string result string notes }
```
