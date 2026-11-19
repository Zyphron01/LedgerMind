# LEDGERMIND — ARCHITECTURAL SPECIFICATIONS & MERMAID DIAGRAMS

**Document:** System Architecture, Data Flow, and Lifecycle Specifications  
**Status:** Verified Local Implementation  
**Auditor Roles:** Senior AI Systems Architect, RAG Engineer, QA Engineer  

---

## 1. Overall System Architecture

The current LedgerMind architecture combines a local relational database for financial audit integrity, a deterministic rule and policy engine for control enforcement, an isolated Docker container for Hindsight vector memory, and Groq cloud LLM for advisory explanations with local deterministic fallback.

```mermaid
flowchart TB
    subgraph UI_TIER["PRESENTATION TIER (Streamlit)"]
        Nav["app.py<br/>Multi-Page Navigation"]
        P1["Overview Dashboard<br/>(Metrics, Discrepancies)"]
        P2["Invoice Intake<br/>(Single & Batch Ingestion)"]
        P3["Exception Queue<br/>(Deep Inspector, Match Cards)"]
        P4["Resolution Workbench<br/>(Policy Cards, Memory, Actions)"]
        P5["Memory Intelligence<br/>(Vendor Profiles, Audit Telemetry)"]
        Nav --> P1
        Nav --> P2
        Nav --> P3
        Nav --> P4
        Nav --> P5
    end

    subgraph APP_TIER["APPLICATION & REASONING TIER"]
        Matcher["agent/matcher.py<br/>Deterministic 3-Way Match"]
        Retriever["policy/retriever.py<br/>Temporal Policy Retriever"]
        Corpus[("policy/corpus.py<br/>Versioned Company Policies")]
        Conflict["policy/conflict.py<br/>Policy-Precedent Conflict Detector"]
        Agent["agent/resolver.py<br/>ResolutionAgent"]
        Prompts["agent/prompts.py<br/>Structured Prompt Builder"]
        Confidence["agent/confidence.py<br/>Heuristic Confidence Scorer"]
        Feedback["agent/feedback.py<br/>Human Review Processor"]

        Retriever <--> Corpus
        Agent --> Matcher
        Agent --> Retriever
        Agent --> Conflict
        Agent --> Prompts
        Agent --> Confidence
        P4 --> Agent
        P4 --> Feedback
    end

    subgraph LLM_TIER["INFERENCE TIER"]
        Groq["agent/llm.py<br/>GroqClient (openai/gpt-oss-120b)"]
        FallbackEngine["agent/resolver.py<br/>Deterministic Fallback Engine"]
        Agent -->|Primary| Groq
        Agent -->|Offline / Rate-Limit| FallbackEngine
    end

    subgraph MEMORY_TIER["INSTITUTIONAL MEMORY TIER"]
        MemClient["memory/client.py<br/>MemoryClient (Async Lifecycle)"]
        MemOps["memory/operations.py<br/>Domain Memory Operations"]
        Budget["memory/budget_guard.py<br/>BudgetGuard (Cloud vs Local)"]
        ReflectCache["memory/reflect_cache.py<br/>Bank-Scoped Reflection Cache"]
        Hindsight[("Local Hindsight Container<br/>http://localhost:8888")]
        OfflineStore[("Offline JSONL Store<br/>offline_memory.jsonl")]

        Agent --> MemOps
        MemOps --> MemClient
        MemClient --> Budget
        MemClient --> ReflectCache
        MemClient <-->|Live Vector Search| Hindsight
        MemClient <-->|Offline Fallback| OfflineStore
    end

    subgraph STORAGE_TIER["PERSISTENCE & AUDIT TIER"]
        DBStore["data/store.py<br/>SQLite Storage Adapter"]
        SQLiteDB[("SQLite Database<br/>data/ledgermind.db")]
        DBStore <--> SQLiteDB
        P2 --> DBStore
        P3 --> DBStore
        Feedback --> DBStore
    end
```

---

## 2. Three-Way Matching & Discrepancy Detection Flow

Mathematical reconciliation compares supplier line-item billings against contracted commitments and physical warehouse receipts before any AI components are engaged.

```mermaid
flowchart TD
    Start(["Input: Supplier Invoice, PO, GRN"]) --> ReadFields["Extract Line Items, Unit Rates, Quantities, HSN, GST"]
    
    ReadFields --> MatchPO{"PO Exists & Valid?"}
    MatchPO -->|Missing PO| Incomplete["Flag: PENDING_PO_DOCUMENTATION<br/>ExceptionType: MISSING_PO<br/>Recommendation: ESCALATED"]
    MatchPO -->|PO Lapsed| POExpired["Check PO Expiry vs Invoice Date<br/>ExceptionType: PO_EXPIRED"]
    
    MatchPO -->|Valid PO| MatchDup{"Duplicate Hash / Number?"}
    MatchDup -->|Duplicate Found| DupExc["Flag: DUPLICATE_INVOICE<br/>Recommendation: REJECTED"]
    
    MatchDup -->|Unique| MatchQty{"Billed Qty == GRN Accepted Qty?"}
    MatchQty -->|Billed > Accepted| QtyExc["Compute Shortfall Delta<br/>ExceptionType: QUANTITY_SHORTFALL"]
    
    MatchQty -->|Qty Matches| MatchPrice{"Billed Unit Price == PO Unit Price?"}
    MatchPrice -->|Price > Contract| PriceExc["Compute Variance Delta & %<br/>ExceptionType: PRICE_MISMATCH"]
    
    MatchPrice -->|Price Matches| MatchTax{"Invoice GST & HSN == Statutory / PO?"}
    MatchTax -->|Tax Rate Differs| TaxExc["ExceptionType: GST_RATE_ERROR<br/>Statutory CGST/SGST/IGST"]
    MatchTax -->|HSN Differs| HSNExc["ExceptionType: HSN_MISMATCH<br/>Tariff Classification"]
    
    MatchTax -->|All Match| Clean["Clean 3-Way Match Verified<br/>is_match: True, variance: ₹0.00"]
    
    Incomplete --> OutputResult["Construct MatchResult Object"]
    POExpired --> OutputResult
    DupExc --> OutputResult
    QtyExc --> OutputResult
    PriceExc --> OutputResult
    TaxExc --> OutputResult
    HSNExc --> OutputResult
    Clean --> OutputResult
    OutputResult --> NextStage(["Proceed to Policy Retrieval"])
```

---

## 3. Temporal Policy Retrieval & Version Selection

Corporate policies are dynamically selected by exception category and transaction date, ensuring expired guidelines cannot govern modern transactions.

```mermaid
sequenceDiagram
    autonumber
    participant Resolver as ResolutionAgent (agent/resolver.py)
    participant Retriever as PolicyRetriever (policy/retriever.py)
    participant Corpus as Policy Corpus (policy/corpus.py)

    Resolver->>Retriever: get_applicable_policy(exception_type, as_of_date=invoice.invoice_date)
    Note over Retriever: Filter 1: pol.applicable_exception_types contains exception_type
    Note over Retriever: Filter 2: pol.effective_from <= invoice.invoice_date
    Note over Retriever: Filter 3: pol.effective_to is None OR invoice.invoice_date <= pol.effective_to
    
    Retriever->>Corpus: Query POLICIES matching criteria
    Corpus-->>Retriever: List[CompanyPolicy] candidate versions

    alt No Policy Found
        Retriever-->>Resolver: None (Triggers ConflictStatus.POLICY_UNKNOWN)
    else Candidate Versions Found
        Note over Retriever: Sort candidates by version descending (e.g. 2.0 > 1.0)
        Retriever-->>Resolver: Authoritative Governing CompanyPolicy instance
    end
```

---

## 4. Policy-Supremacy Conflict Handling Architecture

The core compliance safeguard prevents generative AI or historical precedents from violating financial controls.

```mermaid
flowchart TD
    subgraph INPUTS["EVALUATION INPUTS"]
        Pol["Governing CompanyPolicy<br/>(Tolerances, Mandated Action)"]
        Match["MatchResult<br/>(Exception, Variance INR, Variance %)"]
        Mems["Recalled Historical Memories<br/>(Hindsight Precedents)"]
    end

    INPUTS --> Dedup["Deduplicate Historical Decisions<br/>(Exclude self-reviews & extract unique actions)"]
    Dedup --> CheckUnknown{"Is Policy Known?"}

    CheckUnknown -->|Policy is None| SetUnknown["status = POLICY_UNKNOWN<br/>requires_escalation = True<br/>action = ESCALATED"]
    
    CheckUnknown -->|Policy Found| CheckSample{"Sample Size (n) > 0?"}
    CheckSample -->|n == 0| SetNoEvidence["status = INSUFFICIENT_EVIDENCE<br/>action = Policy Mandated Action"]
    
    CheckSample -->|n > 0| CheckVersionShift{"Precedents dated prior to active policy?<br/>(e.g. Approved under retired v1.0 grace)"}
    CheckVersionShift -->|Yes & Contradicts v2.0| SetVerShift["status = POLICY_VERSION_CHANGED<br/>explanation: Historical approvals used retired policy.<br/>action = REJECTED per active v2.0 standard"]
    
    CheckVersionShift -->|No| CheckConflict{"Did human approve an overage exceeding policy?<br/>(e.g. Approved 2.0% variance when policy caps at 1.0%)"}
    CheckConflict -->|Yes: Unauthorized Practice| SetConflict["status = POLICY_PRECEDENT_CONFLICT<br/>explanation: Past informal approvals violate controls.<br/>action = ESCALATED / REJECTED"]
    
    CheckConflict -->|No: Precedent Complies| SetCompliant["status = COMPLIANT_PRECEDENT<br/>explanation: Precedents align with policy.<br/>action = Policy Mandated Action"]

    subgraph ENFORCEMENT["CODE-LEVEL RESOLVER OVERRIDE (agent/resolver.py)"]
        SetUnknown --> Intercept
        SetVerShift --> Intercept
        SetConflict --> Intercept
        SetCompliant --> Intercept
        Intercept["Model Generates Raw Proposed Action"] --> GuardCheck{"Conflict Status != COMPLIANT?"}
        GuardCheck -->|POLICY_PRECEDENT_CONFLICT| OverrideConflict["Force proposed_action = ESCALATED / REJECTED<br/>Insert Policy Override Rationale"]
        GuardCheck -->|POLICY_VERSION_CHANGED| OverrideVersion["Force proposed_action = REJECTED<br/>Insert Version Shift Rationale"]
        GuardCheck -->|COMPLIANT_PRECEDENT| KeepProposal["Keep Model Proposal"]
    end

    OverrideConflict --> OutputProposal(["Final ResolutionProposal"])
    OverrideVersion --> OutputProposal
    KeepProposal --> OutputProposal
```

---

## 5. Hindsight Memory Lifecycle & Deduplication Flow

LedgerMind resolves raw memory observations into logical human reviews to prevent artificial confidence inflation.

```mermaid
sequenceDiagram
    autonumber
    participant UI as Workbench / Memory Intelligence
    participant Resolver as ResolutionAgent
    participant MemClient as MemoryClient
    participant Hindsight as Hindsight Service (Docker :8888)
    participant Offline as Offline Store (JSONL)

    UI->>Resolver: Resolve invoice with Memory ON
    Resolver->>MemClient: recall(bank_id, query, tags, limit=15)
    
    alt Hindsight Container Healthy
        MemClient->>Hindsight: POST /v1/banks/{bank_id}/memories/recall
        Hindsight-->>MemClient: RecallResponse (raw results: text, tags, metadata, scores)
    else Hindsight Timeout / Offline
        MemClient->>Offline: Scan offline_memory.jsonl by tags & query
        Offline-->>MemClient: List[RecalledMemory] with is_offline_fallback=True
    end

    MemClient-->>Resolver: List of 9 raw memory objects
    
    Note over Resolver: Deduplication Engine (normalize_and_deduplicate_memories)<br/>1. Group records by document_id ('feedback-INV-...')<br/>2. Designate primary human decision review<br/>3. Aggregate remaining records as supporting sub-facts<br/>4. Exclude current invoice self-reviews
    
    Resolver-->>UI: 1 Verified Decision with 8 supporting facts
```

---

## 6. End-to-End Human Review & Audit Trail Flow

The closing loop guarantees that human decisions persist both in relational database tables for internal audit and in vector memory for institutional learning.

```mermaid
sequenceDiagram
    autonumber
    participant Reviewer as AP Reviewer (UI)
    participant Workbench as ui/pages/workbench.py
    participant Feedback as agent/feedback.py
    participant DB as data/store.py (SQLite)
    participant Client as memory/client.py
    participant Hindsight as Hindsight Live Bank (:8888)

    Reviewer->>Workbench: Select Decision (APPROVED/EDITED/REJECTED), Role, Reason, Amount
    Workbench->>Feedback: process_human_feedback(FeedbackSubmission)
    
    Note over Feedback: Step 1: Immutable Relational Persistence
    Feedback->>DB: save_human_review(invoice_number, decision, role, reason, doc_id, bank_id)
    DB-->>Feedback: Record written to human_reviews table
    
    Note over Feedback: Step 2: Institutional Vector Retention
    Feedback->>Client: retain(bank_id='ledgermind-live-demo', content, document_id, tags, metadata)
    Client->>Hindsight: POST /v1/banks/ledgermind-live-demo/memories/retain
    Hindsight-->>Client: 201 Created (document_id confirmed)
    
    Note over Feedback: Step 3: Audit Synchronization Update
    Feedback->>DB: update human_reviews SET hindsight_status='SYNCED'
    Feedback-->>Workbench: FeedbackResult(status=SYNCED, doc_id='feedback-INV-...')
    Workbench-->>Reviewer: Display Success Notification & Persistent Audit Badge
```
