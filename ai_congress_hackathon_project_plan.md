# Verifiable Institutional Memory: Hackathon Project Plan

A temporal, conflict-aware, data-sovereign knowledge system for multinational organizations. Every answer and every flagged conflict traces back to a tamper-evident source.

---

## 1. Judging Criteria (as provided by the hackathon)

Total: 100 points.

| # | Criterion | Weight | Score range |
|---|---|---|---|
| 1 | Innovation | 20% | 0-20 |
| 2 | Technical Execution | 20% | 0-20 |
| 3 | Business Model (+ Global Readiness) | 20% | 0-20 |
| 4 | Real-World Impact (+ Ethical AI Compliance) | 20% | 0-20 |
| 5 | Scalability (+ NRB Collaboration) | 10% | 0-10 |
| 6 | Presentation | 10% | 0-10 |

### 1.1 Innovation (20%)

**What judges look at:** Originality, creativity, and non-obvious AI application. Judges evaluate whether the idea is meaningfully differentiated, applies AI in a transformative way, and demonstrates bold or systems-level thinking rather than incremental improvements.

**Score bands**
- 0-5: Incremental improvement or common idea.
- 6-10: Moderately differentiated concept with limited novelty.
- 11-15: Strong originality and creative AI integration.
- 16-20: Breakthrough or globally competitive innovation.

### 1.2 Technical Execution (20%)

**What judges look at:** Architecture quality, AI integration depth, system robustness. Judges assess the clarity and robustness of the technical architecture, including input → processing → output workflow, model selection logic, integration of AI technologies (LLMs, ML, RAG, multimodal systems), code or workflow reliability, and explainability of the intelligence core.

**Score bands**
- 0-5: Basic prototype with limited AI implementation.
- 6-10: Functional architecture with moderate technical depth.
- 11-15: Well-structured AI-native system design.
- 16-20: Production-grade engineering maturity suitable for real-world deployment.

### 1.3 Business Model + Global Readiness (20%)

**What judges look at:** Monetization logic, adoption pathway, cross-border applicability. Judges evaluate the clarity of the value proposition, monetization or sustainability pathway, user adoption strategy, cross-border market viability, and evidence of market validation or demand.

**Score bands**
- 0-5: Concept without sustainability or business model.
- 6-10: Basic business logic with limited validation.
- 11-15: Viable market pathway with defined users.
- 16-20: Scalable, globally adaptable economic model with strong potential.

### 1.4 Real-World Impact + Ethical AI Compliance (20%)

**What judges look at:** Problem relevance, measurable benefit, responsible AI safeguards. Judges consider the significance of the problem, measurable outcomes or KPIs, societal or economic relevance, responsible data usage, bias mitigation strategies, and overall transparency in AI design.

**Score bands**
- 0-5: Weak or unclear impact case.
- 6-10: Clear localized benefit with limited scale.
- 11-15: Strong national relevance with measurable outcomes.
- 16-20: High social return with documented ethical safeguards.

### 1.5 Scalability + NRB Collaboration (10%)

**What judges look at:** Deployment feasibility, modular design, global builder integration. Judges evaluate whether the system can scale technically and operationally, including cloud readiness, modular architecture, infrastructure feasibility, inclusion of NRB or global collaboration, and alignment with international standards.

**Score bands**
- 0-3: Demo-only system without scalability considerations.
- 4-7: Early scaling strategy with limited infrastructure planning.
- 8-10: Clear deployment pathway and strong global collaboration readiness.

### 1.6 Presentation (10%)

**What judges look at:** Clarity, structure, confidence, and AI reasoning explanation. Judges assess the clarity of storytelling, effectiveness of the demonstration, ability to explain AI decisions, and overall professionalism and confidence of the team.

**Score bands**
- 0-3: Unclear or poorly structured communication.
- 4-7: Clear presentation with moderate structure.
- 8-10: Compelling, data-driven, and investor-ready presentation.

---

## 2. The Merged Project

**One-line pitch:** *Verifiable institutional memory for multinational organizations.*

| Idea | Role in the merged product |
|---|---|
| 1. Temporal KG | Data layer: ingest and structure knowledge over time |
| 2. Conflict detection | Killer feature: use the time dimension to find contradictions |
| 5. Visual lineage | Trust layer and UI: every answer and flag traces to a source |
| 4. Federated RAG | Deployment architecture: data stays in-region |
| 3. ZKP | Privacy layer, scoped honestly (see section 5.8) |

---

## 3. Scope Decisions

1. **Must work end to end:** Ideas 1, 2 and 5. Ingest Slack and PDFs, detect a conflict between policy versions, click through to source nodes.
2. **Simulate convincingly:** Idea 4. Two region-tagged nodes (Dhaka, Frankfurt); raw text never leaves its region, only structured claims, citation IDs and hashes cross over.
3. **Scope Idea 3 honestly:** do not claim the AI queries data it cannot see. Use Merkle commitments for tamper-evident lineage and selective disclosure. Present ZK predicates and TEEs as roadmap.
4. **One concrete story:** a fictional company, *Meridian Trade Finance* (Dhaka HQ, Frankfurt office), handling revised and conflicting policies. Use synthetic documents so no real regulator is misquoted.
5. **NRB angle:** diaspora and international contributors as pilot users and authors of region adapters and connectors.

**Business model:** per-seat or per-region SaaS for compliance teams at multinationals. Sovereignty is the sales blocker we remove.

**Impact KPIs to report:** conflicts caught, time to detect, estimated review hours saved, precision and recall on a labeled set.

---

## 4. Demo Scenarios

Fictional company: **Meridian Trade Finance**.

### Demo 1: "The Catch" (conflict detection over time)

**Setup:** ingest Policy v2 (PDF), Policy v3 (PDF), and a Slack thread from #operations.
- v2: loans under $50,000 need one manager's approval.
- v3: loans over $25,000 need two approvals.
- Slack: an ops lead tells a new hire, "we only need one sign-off up to 50k."

**On screen**
1. Drop files in and watch the temporal graph build live.
2. Red alert: *"Conflict: Slack guidance (Mar 3) contradicts Policy v3 §4.2 (effective Feb 1)."*
3. Timeline view: v2 rule, v3 rule, then the Slack message still following the old rule.
4. Counter: "3 conflicts found in 40 seconds, ~6 hours of manual review."

**Covers:** Ideas 1 and 2; Impact KPI.

### Demo 2: "The Trace" (lineage plus tamper evidence)

**Setup:** ask "How many approvals does a $30,000 loan need?"

**On screen**
1. The AI answers and flags that its sources conflict.
2. Click the answer; the lineage graph opens, tracing to the exact PDF paragraph and Slack message, each with hash and timestamp.
3. **Wow moment:** edit one word in the source PDF behind the scenes and re-verify. Lineage turns red: *"Source modified since ingestion."*

**Covers:** explainability (Technical), transparency (Impact), honest cryptographic claim. State plainly that full ZKP-over-LLM is roadmap.

### Demo 3: "The Border" (federated, data-sovereign query)

**Setup:** two deployments, DHAKA (local lending policies) and FRANKFURT (EU compliance documents).

**On screen**
1. A Frankfurt user asks, "Do Dhaka-originated loans meet our retention rules?"
2. Split screen with a live request log. Query routes to Dhaka, retrieval happens locally, only the answer, citation IDs and hashes cross. Highlight **"raw text transferred: 0 bytes."**
3. System flags a cross-jurisdiction conflict (5-year vs 7-year record retention) and links both sources.

**Covers:** Global Readiness and Scalability; NRB pilot story.

### Presentation tips
- **3-minute video order:** Demo 1 (~60s), Demo 2 (~60s), Demo 3 (~45s), then closing slide with impact numbers and business model.
- **Record backup takes** of each demo.
- **Say what's simulated.** Honesty about scope is rewarded more than it is penalized.
- If short on time, Demos 1 and 2 alone make a strong video; reduce Demo 3 to a simple two-node simulation.
- **Key line for "AI reasoning explanation":** *"Language models read the documents, but they don't make the final call. They extract structured rules, deterministic logic checks the conflicts, and every answer carries a signed trail back to the source."*

---

## 5. Technical Design

### Architecture overview

```
 Slack ──┐
         ├─► [1 Ingest] ─► [2 Extract] ─► [3 Temporal KG] ◄─► [4 Conflict Engine]
 PDFs ───┘   queue,parse    LLM → rules    bi-temporal graph        │
                                  │               │                │
                                  ▼               ▼                ▼
                    [5 Lineage & Integrity: hashes, Merkle roots, signed records]
                                              │
                    [6 Query layer: hybrid RAG + federation gateway] ─► UI

 └──────────────── runs per region (DHAKA, FRANKFURT) ────────────────┘
```

### 5.1 Ingestion pipeline (Idea 1)

**Slack:** Events API, or Socket Mode (easier for a hackathon, no public URL needed). Each message goes onto a queue (Redis Streams or an async queue) and is normalized:

```json
{"source_type":"slack","channel":"#operations","author":"u_ops_lead",
 "ts":"2026-03-03T09:14:00Z","thread_id":"t_88","text":"we only need one sign-off up to 50k"}
```

**PDFs:** chunk by clause (`§4.2`), not by fixed token count. Use a layout-aware parser (PyMuPDF or pdfplumber) to detect headings and numbered sections so each chunk has a section path (`Policy v3 > §4 > 4.2`). Fixed-size chunking can split "approvals required" from "unless the amount exceeds...", causing false conflicts.

**Idempotency:** every item gets a content hash. Re-uploads and duplicate Slack events create no new nodes (event delivery is at-least-once).

### 5.2 Structured extraction (the intelligence core)

An LLM converts each chunk into normalized rule claims using a fixed JSON schema (structured output, temperature 0):

```json
{
  "claim_id": "clm_0412",
  "subject": "loan_approval",
  "applies_to": {"amount_usd": {"gt": 25000}},
  "obligation": {"type": "min_approvals", "value": 2},
  "authority": "policy",
  "source_node": "doc:policy_v3#4.2",
  "valid_from": "2026-02-01",
  "recorded_at": "2026-02-03T10:00:00Z"
}
```

The Slack message becomes a claim with `amount_usd: {lte: 50000}`, `min_approvals: 1`, `authority: "informal"`, and `valid_from` set to the message timestamp.

**Model selection logic**
- A small, fast model does bulk extraction (cheap, schema-constrained).
- A stronger model handles adjudication and answer generation.
- **Validation:** every extraction is checked against the JSON schema, and extracted numbers must literally appear in the source text (regex check). If "50,000" isn't in the chunk, the claim is rejected.

### 5.3 Temporal knowledge graph

**Bi-temporal modeling:** every fact carries two time axes.
- **Valid time:** when the rule applies in the world (`valid_from`, `valid_to`).
- **Transaction time:** when the system learned it (`recorded_at`).

This supports both "what is the rule on March 10?" and "what did we believe on March 1?"

**Node types:** `Document`, `Version`, `Clause`, `Claim`, `Message`, `Entity`, `Region`.

**Edge types:** `IN_VERSION`, `SUPERSEDES`, `EXTRACTED_FROM`, `MENTIONS`, `CONTRADICTS` (created by the conflict engine, with a reason).

```cypher
MATCH (c:Claim {subject:'loan_approval'})-[:EXTRACTED_FROM]->(src)
WHERE c.valid_from <= date($asof)
  AND (c.valid_to IS NULL OR c.valid_to > date($asof))
RETURN c, src
```

Neo4j is the natural choice. Postgres + `pgvector` with an edges table, or NetworkX persisted to SQLite, also work. The data model matters more than the database.

### 5.4 Conflict detection engine (Idea 2)

A naive "ask an LLM about every pair" approach is O(n²), slow and unreliable. Use a three-stage funnel.

**Stage A: Candidate generation (cheap).** Compare only claims with the same `subject` and overlapping scope. Use embeddings plus entity matching to catch paraphrases ("sign-off" vs "approval").

**Stage B: Symbolic check (deterministic).**

```python
def overlaps(a, b):
    return max(a.lo, b.lo) < min(a.hi, b.hi)   # amount ranges intersect?

def incompatible(c1, c2):
    return c1.min_approvals != c2.min_approvals

# v3: (25000, inf) -> 2 approvals ; Slack: (0, 50000] -> 1 approval
# overlap = (25000, 50000] and approvals differ => conflict in that band
```

Result: "conflict for loans between $25,000 and $50,000," which is verifiable and more convincing than "the AI thinks these disagree."

**Stage C: Temporal and authority classification.**

| Pattern | Classification |
|---|---|
| v3 overlaps v2, v3 effective later | Supersession (expected, no alert) |
| Informal claim (Slack) contradicts in-force policy | Stale or incorrect guidance (high severity) |
| Two in-force policies disagree | True contradiction |
| Same topic, different jurisdictions | Cross-jurisdiction conflict |

Only the last three raise alerts, which avoids alert fatigue.

**LLM adjudication** is reserved for cases the symbolic check can't settle (exceptions, vague wording). It receives both clauses and returns a verdict, a one-sentence reason, and quotes of the exact spans used.

**Evaluation:** hand-label about 30-50 claim pairs (true conflicts plus decoys). Report precision and recall, e.g. "precision 0.9, recall 0.8 on 40 labeled pairs."

### 5.5 Lineage and integrity (Idea 5, plus the honest version of Idea 3)

**Hashing:** leaf hash = `SHA256(canonical_text || source_id || offset)`. Leaves of a document version form a **Merkle tree**; the root is stored.

**Ingestion ledger (hash chain):**

```
entry_n = SHA256(entry_{n-1} || merkle_root || timestamp)
```

**Signed answer lineage record (Ed25519):**

```json
{
  "answer_id": "ans_771",
  "query_hash": "9f2c…",
  "model": "adjudicator-v1",
  "retrieved": [
    {"node":"doc:policy_v3#4.2","leaf_hash":"ab31…","merkle_root":"c0de…"},
    {"node":"slack:t_88#msg1","leaf_hash":"77de…"}
  ],
  "claims_used": ["clm_0412","clm_0455"],
  "signature": "…"
}
```

**Tamper demo:** on "verify," the system re-reads the source, recomputes the leaf hash, and checks it against the stored Merkle proof. A one-word change turns the UI red.

**What this proves:** the cited source is byte-identical to what was ingested, and the lineage record wasn't altered afterward.
**What it does not prove:** that the LLM reasoned correctly. That is covered by citation verification (5.6).

**Lineage UI:** React Flow or D3 rendering answer → claims → clauses/messages → document version, colored by verification status. Clicking a node opens the highlighted source passage.

### 5.6 Query layer: hybrid RAG with verification

1. **Query analysis:** extract time scope ("as of today" by default) and entities.
2. **Hybrid retrieval:** vector search + BM25 (exact terms like "§4.2") + graph traversal (pull conflicting or superseding neighbors).
3. **Time filter:** exclude superseded claims unless the question is historical.
4. **Generation:** retrieved claims carry IDs; every statement must cite claim IDs. If sources conflict, the model says so rather than picking one.
5. **Verification pass:** confirm each cited passage supports the sentence citing it. Drop or flag unsupported sentences. If retrieval confidence is low, **abstain**.

### 5.7 Federation and data sovereignty (Idea 4)

Each region runs its own stack (ingestion, graph, vector store, region-pinned model endpoint). A thin **coordinator/gateway** sits above them.

**Flow for "Do Dhaka-originated loans meet our retention rules?" (asked from Frankfurt):**

1. Coordinator consults a metadata catalog (region, topic tags, no content) and picks the Dhaka node.
2. Sends a sub-query over mTLS:
   ```json
   {"request_id":"r_19","from":"FRANKFURT","question":"retention period for loan records",
    "egress_policy":"structured_claims_only"}
   ```
3. Dhaka retrieves and reasons locally, returning only an allowlisted payload:
   ```json
   {"claims":[{"subject":"record_retention","years":5,"authority":"policy",
               "source_ref":"doc:dhaka_policy_v2#9.1","leaf_hash":"5be1…"}],
    "raw_text_bytes": 0}
   ```
4. Frankfurt's conflict engine compares Dhaka's claim (5 years) with its own (7 years). **Cross-region comparison runs on structured claims, not text.**

**Egress filter:** a policy layer at each node enforces which fields may leave (claim values, citation IDs, hashes), blocks everything else, and logs every transfer. The "0 bytes of raw text" counter comes from this log.

**Honest caveat:** a returned claim can itself be sensitive, and an LLM-written answer can leak content. Mitigate with per-document sensitivity labels, egress rules that block "restricted" claims or require local human approval, and PII redaction (e.g. Microsoft Presidio) before anything leaves.

### 5.8 Privacy layer (Idea 3, scoped honestly)

| Level | What it is | Status |
|---|---|---|
| Commitments | Merkle roots prove source integrity without sharing the full document | **Build now** |
| Selective disclosure | Share a proof for one clause, not the whole document | **Build now** (Merkle proofs) |
| Confidential computing | Retrieval and model inside a TEE (AWS Nitro Enclaves, Intel TDX) | Roadmap |
| ZK predicates | Prove "this committed rule has retention ≥ 7 years" without revealing the document | Roadmap (feasible with zk-SNARKs for simple numeric predicates) |
| ZK over LLM inference | Prove a model's output without exposing inputs | Research-stage, too slow for production |

Structured numeric claims are exactly what ZK circuits handle well, which makes ZK predicates a realistic next step rather than a buzzword.

### 5.9 Responsible AI controls

- **Access control:** RBAC enforced at retrieval time, before the model sees anything.
- **Human in the loop:** conflicts above a severity threshold go to a reviewer queue; the system recommends, a person decides.
- **Bias and fairness:** no decisions about individuals. Redact PII in Slack text; frame alerts around the guidance, not the employee.
- **Audit trail:** every extraction, verdict and answer logged with model version and prompt hash.
- **Abstention:** low-confidence answers are labeled as such.

### 5.10 Scalability design

- Stateless workers behind a queue, so ingestion scales horizontally.
- Modular adapters (Slack, Teams, SharePoint, email) emit the same normalized event. NRB or diaspora contributors can add regional connectors here.
- Each region packaged as a Helm chart or Compose bundle; adding a country means deploying one more node and registering it in the catalog.
- Incremental conflict checks: a new claim is compared only against claims sharing its subject and scope.
- Schema versioning on the claim format, so extraction can improve without full re-ingestion.

---

## 6. Deployment and Requirements

**Yes, it runs on laptops.** The synthetic dataset is small; no GPU or server is needed. The main decision is where the LLM runs.

### 6.1 Team hardware

5 team members, 5 laptops, 16 GB RAM each. This is the "comfortable" tier: the full stack, including Neo4j, runs on any single laptop.

| Component | Approx. RAM |
|---|---|
| Two region nodes (FastAPI + SQLite/Postgres) | 0.5-1 GB |
| Gateway | ~0.2 GB |
| Frontend dev server | ~0.5 GB |
| Neo4j (optional) | 1-2 GB |
| Docker Desktop overhead | 1-2 GB |
| OS, browser, editor | 4-6 GB |
| **Total** | **~8-12 GB** |

- **Windows users:** cap WSL2 memory in `%UserProfile%\.wslconfig` (`memory=8GB`) so Docker doesn't freeze the laptop.
- A local 7-8B model via Ollama needs another 6-8 GB. Treat it as optional on one machine only, preferably an Apple Silicon Mac or a laptop with a dedicated GPU.

### 6.2 LLM options

| Option | Notes |
|---|---|
| **A. Hosted LLM API (recommended)** | Reliable JSON-schema output; laptop just sends HTTP requests; needs internet at demo time (use cache fallback). Check pricing and hackathon credits. |
| **B. Local models via Ollama** | Works offline and strengthens the sovereignty story, but slow without a GPU and less reliable at strict JSON; plan for validation retries. |
| **Hybrid** | API for extraction and adjudication; optionally one region's node on a local model as a "sovereign mode" proof of concept. Be explicit about which is which. |

### 6.3 Lean vs full stack

| Component | Lean (laptop-friendly) | Full |
|---|---|---|
| Graph | SQLite + NetworkX, or Postgres + pgvector | Neo4j |
| Queue | Python `asyncio` queue | Redis Streams |
| Vector search | `pgvector` or in-process FAISS | Dedicated vector DB |
| PDF parsing | PyMuPDF | Same |
| Backend | FastAPI | Same |
| Frontend | React + React Flow (Vite) | Same |

**Start lean**, swap in Neo4j later if time allows.

### 6.4 Two "regions" on one laptop

```yaml
# docker-compose.yml (sketch)
services:
  dhaka-node:
    build: ./node
    environment: [REGION=DHAKA, DB_PATH=/data/dhaka.db]
    volumes: ["./data/dhaka:/data"]
    ports: ["8001:8000"]

  frankfurt-node:
    build: ./node
    environment: [REGION=FRANKFURT, DB_PATH=/data/fra.db]
    volumes: ["./data/frankfurt:/data"]
    ports: ["8002:8000"]

  gateway:
    build: ./gateway          # routing + egress log
    ports: ["8000:8000"]
    depends_on: [dhaka-node, frankfurt-node]

  ui:
    build: ./ui
    ports: ["3000:3000"]
```

Separate containers and volumes make the "0 bytes of raw text crossed the border" claim measurable from the gateway log. State plainly that both regions share one machine in the demo.

### 6.5 Demo-day setup options

| Setup | Pros | Cons |
|---|---|---|
| **A. One laptop runs everything** | Simple, no network dependency | Both regions share one machine |
| **B. Dhaka node on laptop X, Frankfurt on laptop Y, gateway on a third, over hotspot or local router** | Sovereignty claim is literally true across machines; visually impressive | Network and firewall issues can break it live |

**Plan:** build for A first and make B a configuration change (node addresses in environment variables, not hardcoded). Rehearse B once the core works and record with whichever is more stable. **Designate a primary demo laptop and a hot backup** with an identical, tested setup.

### 6.6 Making the demo reliable

1. **Replay mode for Slack:** a script replays a saved Slack export (JSON) through the same ingestion path. Live Slack is optional.
2. **Seed data and one-command reset:** `make seed` or `./reset_demo.sh` wipes databases and loads synthetic data.
3. **Cache LLM outputs** keyed by chunk hash, so the pipeline is fast, deterministic, and works if the API is slow or down. Be upfront if the video shows cached results.
4. **Pin versions:** `requirements.txt` or `uv.lock`, `package-lock.json`, Docker image tags, `.python-version`, `.nvmrc`.
5. **Test on the exact demo laptop**, at the recording resolution, on the venue network or a phone hotspot.
6. **Record backup takes** from a known-good run.
7. **Venue network:** many Wi-Fi networks isolate clients from each other, silently breaking laptop-to-laptop traffic. Use a phone hotspot or travel router, open ports (e.g. 8001, 8002) in firewalls, and test with `curl`.

### 6.7 Software checklist

- Python 3.11+ and Node 18+
- Docker Desktop (Windows: WSL2 enabled)
- Git with one shared repo and a `.env.example` (never commit API keys)
- A Slack app, only for live ingestion
- Optional: Ollama for local models

### 6.8 Hosting online (optional)

Not required for judging by video or live demo. If judges want a link, put the same Compose file on one small cloud VM (2-4 vCPUs, 4-8 GB RAM) or a platform like Render or Fly.io. Keep API keys in environment variables and add read-only access or rate limits so strangers can't run up the LLM bill.

---

## 7. Team Plan (5 members)

| Person | Owns | Demo it enables |
|---|---|---|
| 1 | Ingestion and extraction: PDF clause parser, Slack replay, claim schema, LLM extraction with validation | Demo 1 |
| 2 | Graph and conflict engine: bi-temporal model, symbolic check, severity classification, labeled evaluation set | Demo 1 |
| 3 | Integrity and lineage backend: hashing, Merkle proofs, signed answer records, tamper check, RAG with citations | Demo 2 |
| 4 | Frontend: timeline view, conflict alerts, lineage graph (React Flow) | All three |
| 5 | Federation and DevOps: gateway, egress filter and log, Compose setup, `reset`/`seed` scripts | Demo 3 |

Everyone shares the pitch. One person writes the synthetic dataset and narration script early, since it unblocks persons 1 and 2. The whole team rehearses the video.

**First hour: agree on two contracts**
1. The claim JSON schema (section 5.2).
2. The API endpoints between backend, gateway and UI, with mock responses.

With those fixed, the frontend can be built against fake data and nobody blocks anyone.

**Team practices**
- Commit the extraction cache so nobody burns API calls re-extracting.
- Share one API key through a password manager (not the repo) and set a spending cap.
- Pin the same Python and Node versions; add `.gitattributes` early to avoid line-ending bugs on mixed Windows/macOS teams.

---

## 8. Build Order

1. Claim schema and extraction on the synthetic documents.
2. Graph and the symbolic conflict check, with Demo 1 working end to end.
3. Hashing, Merkle proofs and the tamper check (Demo 2).
4. Lineage UI.
5. Two-node federation with the egress log (Demo 3).
6. Evaluation table and metrics for the impact slide.
7. Freeze features, cache all LLM outputs, rehearse three times from a clean reset, record backup takes.

An ugly working pipeline beats a polished half-built one. If you can only build part of it, build Ideas 1, 2 and 5 first.

### Suggested stack summary

| Layer | Choice |
|---|---|
| Backend | Python, FastAPI |
| Queue | Redis Streams (or asyncio) |
| Graph | Neo4j (or Postgres + pgvector) |
| Parsing | PyMuPDF / pdfplumber |
| Extraction and reasoning | LLM API with JSON-schema outputs |
| Hashing and signing | `hashlib`, `cryptography` (Ed25519) |
| Frontend | React + React Flow / D3 |
| Federation | Two Docker Compose stacks + gateway |
