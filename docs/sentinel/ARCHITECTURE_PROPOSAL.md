# Sentinel AI — Foundation & Architecture Proposal

**Status:** PROPOSED — awaiting owner review
**Scope:** Architecture preparation only. No Phase 0 implementation has been performed.
**Author:** Principal architect (Claude Code session)
**Date:** 2026-08-15

> Nothing in this document is wired into a build. No frameworks installed, no
> production code written, no directories created beyond `docs/sentinel/`.
> Phase 0 begins only on explicit owner approval.

---

## A. Architecture Assessment

### A.1 What the specification gets right

The specification is unusually strong on the things most AI platforms get wrong
late and expensively:

1. **Provider neutrality as a first-class constraint (§2, §4, §14, §23).** Most
   platforms discover vendor lock-in after it is structural. Declaring the model
   gateway, voice pipeline, and integration adapters as replaceable *before*
   implementation is the single highest-leverage decision in the document.
2. **Separation of reasoning from execution (§13, §38.13).** The graded
   permission ladder (L0–L4) is the correct primitive. Most agent frameworks
   conflate "the model decided" with "the system acted".
3. **Integrate, do not replace (§15).** This is a genuine product differentiator
   and a scope-control mechanism. It caps the surface area of the platform.
4. **Capability Registry (§33) with an anti-duplication rule.** This is the only
   mechanism in the document that can mechanically prevent feature sprawl. It
   deserves to be enforced in CI, not just documented.
5. **Intellectual integrity as non-negotiable (§27) and FACT/INFERENCE/ESTIMATE/
   RECOMMENDATION/UNKNOWN labelling (§8).** Correct, and it should be a data
   type, not a prose convention.
6. **Build order (§37) is broadly correct** — security and identity before
   intelligence, intelligence before agents, agents before UI.

### A.2 The central architectural tension

§3 lists fifteen responsibilities for "Sentinel Core" and then says Core must not
become a monolith. Those two statements cannot both be satisfied by a component
that *implements* fifteen things. They can both be satisfied by a Core that
**owns a request lifecycle and delegates everything else through contracts**.

This proposal therefore defines Sentinel Core narrowly:

> **Sentinel Core owns:** the turn/request lifecycle, intent resolution, plan
> construction, capability resolution via the registry, the policy enforcement
> point, approval gating, and turn state.
>
> **Sentinel Core does not own:** models, memory, research, agents, integrations,
> notifications, licensing, audit storage, or identity. It *calls* them, and it
> calls them through contracts it does not implement.

Concretely: **Core never imports a capability, agent, provider, or adapter
package.** It imports only contracts (L0) and resolves implementations at runtime
through the registry. This is what keeps the anti-monolith rule enforceable
rather than aspirational.

### A.3 The largest unaddressed risk

The specification contains **no threat model for untrusted content**. Sentinel is
designed to ingest web research (§8), inbound email and chat (§20), OCR'd
documents and images (§18), and third-party integration payloads (§14) — and
then feed them into a system that can execute tools with the user's authority.
This is the dominant, actively-exploited attack class for agent platforms
(indirect prompt injection / confused deputy), and it is not mentioned once.

This proposal introduces **Trust Tiers and the Authority Rule** (§G.2) as a
foundational primitive, on par with identity and permissions. It must land in
Phase 1, not Phase 6.

### A.4 Overall verdict

The specification is a sound basis for implementation after the corrections in
Section B. The highest-priority corrections are:

| Priority | Correction |
|---|---|
| P0 | Trust tiers + authority-never-flows-from-content rule (B.11) |
| P0 | Core narrowed to a thin lifecycle owner (B.1) |
| P0 | Language/runtime and repository placement decided (B.2, N.1, N.2) |
| P0 | Single Policy Decision Point; deny by default (B.9) |
| P0 | Durable execution model before multi-model orchestration (B.15) |
| P1 | Agents as first-class attenuated principals (B.10) |
| P1 | Four distinct record streams disentangled (B.23) |
| P1 | Immediate-revocation-compatible session model (B.22) |
| P1 | Budget/quota enforcement, not just "cost awareness" (B.13) |

---

## B. Problems / Risks Found

Format: **Issue → Why It Matters → Recommended Correction**

### Contradictions

**B.1 — Core is specified as both an orchestrator of 15 subsystems and as
not-a-monolith (§3).**
*Why it matters:* Left unresolved, every new feature lands "in Core" because Core
is where coordination lives. This is the standard path to a god object, which
§34 explicitly prohibits. It also makes Core untestable — you cannot unit test a
component with fifteen live dependencies.
*Correction:* Adopt the narrow Core definition in A.2. Core depends on contracts
only; implementations are resolved at runtime from the Capability Registry.
Enforce with an automated import-direction check in CI (see E.3). Add an
architectural test that fails if `sentinel/core/` imports any of
`capabilities/`, `agents/`, `integrations/`, or `intelligence/providers/`.

**B.2 — Level 4 "Limited Autonomous Execution" (§13) contradicts "Sentinel should
never rely on invisible autonomous behavior for consequential actions" (§29).**
*Why it matters:* As written, an implementer can justify almost any autonomous
action by pointing at a user-defined rule, or block all autonomy by pointing at
§29. The ambiguity will be resolved differently in different modules, which is
how permission leakage happens.
*Correction:* Level 4 is permitted only when **all** of the following hold:
(a) the action's `side_effect_class` is `READ`, `ANALYZE`, `DRAFT`, or
`EXECUTE_REVERSIBLE`; (b) a pre-declared, user-authored rule authorises it with
explicit bounds (scope, frequency, value ceiling, expiry); (c) the action is
announced to the user via the notification capability **before or immediately
after** execution, never silently; (d) it is fully audited with the triggering
rule id. Level 4 is *never* available for `EXECUTE_IRREVERSIBLE`, `DESTRUCTIVE`,
or `FINANCIAL` classes — those are capped at Level 3 regardless of user
configuration. "Autonomous" therefore means *unattended*, never *invisible*.

**B.3 — §7 forbids automatic creation or purchase; §22 defines a commerce
capability; §13 L4 permits autonomous execution.**
*Why it matters:* Three sections that will be read by three different
implementers, producing an accidental autopurchase path.
*Correction:* Encode the constraint in the capability manifest, not in prose.
Any capability declaring `side_effect_class: FINANCIAL` or
`side_effect_class: PROVISIONING` gets `max_permission_level: 3` as a
registry-enforced hard ceiling. The registry validator rejects a manifest that
declares `FINANCIAL` with `max_permission_level: 4`. Policy is then mechanically
unable to disagree with the specification.

**B.4 — §2/§4 demand full provider neutrality; real providers differ materially.**
*Why it matters:* Naive neutrality produces a lowest-common-denominator gateway:
no prompt caching, no provider-native structured output, no extended thinking, no
native tool-use semantics. You pay the abstraction cost and lose the capabilities
that justify choosing a provider. Conversely, leaking provider quirks into
callers is the lock-in §2 forbids.
*Correction:* Neutral **core contract** plus explicit **capability negotiation**.
Each provider adapter publishes a `ProviderCapabilities` descriptor (streaming,
tool-calling, structured output, caching, vision, context window, modality
support). Callers state *requirements*, never provider names. The gateway
selects among adapters that satisfy the requirements. Provider-specific
enhancements are permitted **only** as optional optimisations behind the neutral
contract, and must degrade silently when unavailable. A conformance test suite
(H.5) proves every adapter honours the contract identically.

**B.5 — "Sentinel Core + 3 Adaptive Agent Slots" (§6) states a licensing fact as
an architectural fact.**
*Why it matters:* If `3` reaches the core data model, adding a fourth agent is a
migration rather than an entitlement change — which §6 explicitly forbids.
*Correction:* Core supports N agents. `3` is the default value of the
`agents.slots` entitlement for the Individual plan. No constant `3` may appear
outside the entitlement seed data. Add a lint rule / test asserting this.

### Duplication

**B.6 — "Search and summarise the world" appears three times: Research Engine
(§8), communications triage (§20), commerce/product research (§22).**
*Why it matters:* Three retrieval-and-summarise implementations means three
citation formats, three freshness policies, three injection surfaces, and three
places to fix a bug. Directly violates §38.16.
*Correction:* Exactly one `research` capability owns external retrieval,
source-quality evaluation, conflict detection, and citation. Commerce and
communications **compose** it; they do not re-implement it. The registry's
`responsibility` uniqueness check (F.4) makes a second retrieval owner a CI
failure.

**B.7 — Document/image ingestion is owned by both the Visual Intelligence
Pipeline (§18) and Knowledge/document memory (§9), with the Visual Gallery (§19)
implying a third store.**
*Why it matters:* Two content stores with different permission models is a
guaranteed cross-workspace leak (§19 explicitly warns about this).
*Correction:* One `content` capability owns blob storage, metadata, workspace
association, retention, and deletion — for *all* media (images, documents,
audio). `visual_intelligence` is a stateless **processing** capability: content
reference in, structured observation out. The "Gallery" (§19) is a *view over
`content`*, not a subsystem. Knowledge memory (§9) stores derived
embeddings/extracts and references `content` by id; it never holds a second copy
of the bytes.

**B.8 — "What needs my attention today?" (§20) versus Alerts & Notifications
(§21).**
*Why it matters:* Triage (deciding what matters) and delivery (push/email/voice)
are different problems with different failure modes and different scaling
characteristics. Merging them produces a notification system that cannot be
tested without an LLM.
*Correction:* Split. `attention` capability = ranking/triage, produces
`AttentionItem` records with a reason. `notification` capability = transport,
priority, quiet hours, escalation, digesting, deduplication. `attention` emits;
`notification` delivers. Either can be replaced independently.

### Gaps

**B.9 — No authorization decision point is specified.**
*Why it matters:* §11 lists roles and permissions but not *where the decision is
made*. Without a single decision point, checks scatter across handlers — the
exact failure §26 warns about for licensing, applied to something far more
dangerous.
*Correction:* Introduce an explicit **Policy Decision Point (PDP)** and
**Policy Enforcement Points (PEPs)**. Every capability invocation passes through
exactly one PEP inside Core's dispatcher. The PDP is a pure function:
`decide(principal, scopes, resource, action, context) -> Permit | Deny(reason)`.
Deny by default; an unregistered capability or an unmatched scope is a denial,
never a fallthrough. The PDP is pure and side-effect-free so it can be exhaustively
tested with golden fixtures (H.3).

**B.10 — Agents are not principals.**
*Why it matters:* §32 says "never give an agent broader credentials than its job
requires", but §11 models only human roles. Without agent identity, an agent runs
as the user and inherits every scope the user has — the confused deputy problem,
at full user privilege.
*Correction:* Agents, sub-agents, and capability invocations are **first-class
principals** acting *on behalf of* a user. Each execution receives an
**attenuated capability token**: scopes = `user_scopes ∩ capability_declared_scopes
∩ entitlement_grants ∩ task_scope`, bound to one tenant, one correlation id, a
task-length TTL, and non-refreshable. Attenuation is monotonic — a sub-agent can
never hold a scope its parent lacked. This also makes audit answer "which agent,
with what authority" rather than just "which user".

**B.11 — No threat model for untrusted content (indirect prompt injection).**
*Why it matters:* This is the platform's largest security exposure. A malicious
web page found by the Research Engine, a crafted inbound email, or text embedded
in an uploaded image can attempt to redirect an agent that holds real tool
authority. Every ingestion path in the spec (§8, §14, §18, §20) is an attack
surface, and none of them is treated as one.
*Correction:* Introduce **Trust Tiers** as a kernel primitive (see G.2) and the
**Authority Rule**: *authority never flows from content*. Content can inform a
plan; only an authenticated principal plus policy can authorise one. Any plan step
whose provenance includes T2/T3 content and whose `side_effect_class` is
`EXECUTE_*` or above requires explicit human approval, regardless of permission
level. Untrusted content is delimited and labelled in every prompt, never
concatenated into instruction position.

**B.12 — Tenancy ambiguity between "user memory" and organization membership
(§9 vs §10).**
*Why it matters:* If a user belongs to a personal account and two business
organizations, "user memory" is undefined territory. Getting this wrong leaks a
user's personal context into their employer's workspace, or an employer's data
into the user's personal account. Both are serious.
*Correction:* Memory scope is a strict tree with an explicit visibility rule:
`account → organization → workspace → agent → session`. **User memory is
account-scoped and never visible to organization or workspace reads by default.**
Any cross-scope read requires an explicit, audited, user-approved
`MemoryBridge` grant with a scope, purpose, and expiry. There is no ambient
inheritance upward or downward. Every memory record carries `owner_scope` and
every read carries `requested_scopes`; the PDP evaluates the intersection.

**B.13 — "Cost awareness" (§4) is not cost control.**
*Why it matters:* Agentic loops fail *expensively*. A retry storm across a
fallback chain (§31) can multiply spend by an order of magnitude in minutes, and
§26 ties capabilities to paid plans without a mechanism to stop overspend.
*Correction:* Budgets are an enforcement primitive, not telemetry. Every
execution carries a **budget envelope** (max tokens, max provider calls, max
wall-clock, max cost) derived from entitlements. The gateway decrements and
**hard-fails** on exhaustion with a typed, user-visible error. Per-tenant daily
ceilings, plus a global platform circuit breaker. Recursion depth and fan-out for
sub-agents are bounded at the orchestrator, not by convention.

**B.14 — No storage, data-modelling, or migration phase in the build order (§37).**
*Why it matters:* Phase 1 builds identity, orgs, workspaces, and audit — all of
which are persistent, all of which will need schema evolution. Retrofitting
migrations after data exists is far more expensive than starting with them.
*Correction:* Add **persistence and migration tooling to Phase 1**, before
identity. Also add a **durable execution** component (B.15) to Phase 1, before
the Model Gateway.

**B.15 — Multi-model orchestration (§5) is implicitly synchronous.**
*Why it matters:* "Model A researches → Sentinel plans → Model B codes →
Sentinel validates" is a minutes-to-hours workflow. Running it inside a request
means timeouts, lost work on deploy, no resumability, and no idempotency — which
directly contradicts §31's requirements for retries, idempotency, and graceful
degradation.
*Correction:* Orchestration runs on a **durable execution model** from day one:
persisted plan + step state, idempotency keys on every side-effecting step,
at-least-once execution with effect deduplication, resumable after restart.
Clients observe progress via subscription, not by holding a connection. This is
the single hardest thing to retrofit; it belongs in Phase 1.

**B.16 — Memory has no retrieval contract (§9).**
*Why it matters:* "Memory" without an explicit write policy, retrieval policy,
and provenance requirement reliably degrades into an unbounded store that
poisons prompts and cannot be audited or deleted on request.
*Correction:* Memory is contract-first: typed records with `scope`, `owner`,
`provenance` (which turn/source produced it), `trust_tier`, `confidence`,
`retention_policy`, and `expires_at`. Writes are explicit operations, never a
side effect of conversation. Retrieval is a declared query with a scope filter
and a result budget. Deletion is a real, cascading, audited operation — §9
requires deletion capability, and that must include derived embeddings and
extracts, not just the source row.

**B.17 — Revocation (§12) is incompatible with long-lived stateless tokens.**
*Why it matters:* §12 requires that revoking a user *actually* removes active
authorization and invalidates live sessions. A stateless JWT with a multi-hour
expiry cannot do this, and this is the most common way "revocation" silently
fails in production.
*Correction:* Short-TTL access tokens (≤15 min) + server-side session records +
rotating refresh tokens + a per-principal **session epoch** counter. Revocation,
role change, or emergency lockout increments the epoch, invalidating every
outstanding token for that principal on next use. Agent capability tokens
additionally check the parent session epoch at issuance and at each capability
invocation. Add a test that proves a revoked principal cannot complete an
in-flight multi-step execution.

**B.18 — Founder/Internal permanent licence (§26) is a permanent privileged
backdoor.**
*Why it matters:* A never-expiring, all-capabilities entitlement is the highest-
value forgery target in the system. If it can be granted or verified client-side,
it will eventually be forged or leaked.
*Correction:* Founder entitlements are **server-issued only**, signed, bound to a
specific account id, non-transferable, and **flagged in every audit record they
enable**. They grant capability access; they do **not** bypass the PDP, tenant
isolation, approval gating, or audit. Add an explicit test: a founder principal
cannot read another tenant's data.

**B.19 — Device pairing (§25) is under-specified beyond "no permanent secrets in
QR codes".**
*Why it matters:* Pairing flows are a classic phishing target — a QR code
screenshotted and sent to an attacker grants a device.
*Correction:* Pairing codes are single-use, short-TTL (≤120s), bound to the
initiating session, require confirmation on an already-trusted device, and
provision a **device-bound keypair** (the code exchanges for a device credential;
it never *is* the credential). Trusted devices are listed, named, individually
revocable, and their revocation increments the session epoch.

**B.20 — §16 forbids storing financial credentials but does not say what *is*
stored.**
*Why it matters:* "Prefer scoped integrations and tokens" still means holding
OAuth refresh tokens, which are credentials.
*Correction:* Explicit rule: no bearer credential is ever stored in application
storage. All integration tokens live in a secrets store behind a `secrets`
interface with envelope encryption, per-tenant key derivation, and access
logging. Adapters receive short-lived materialised credentials at call time and
never persist them. Financial-category integrations default to read-only scopes
and require re-consent to widen.

### Bottlenecks & scaling risks

**B.21 — The Capability Registry is a single point of coupling.**
*Why it matters:* Every invocation resolves through it. If it is a live network
service on the hot path, it becomes a latency floor and an availability ceiling.
*Correction:* The registry is **statically declared** (manifest files in the
repo, validated at build time) and **loaded in-process at startup**, with an
optional runtime overlay for enable/disable and version pinning. It is a
compile-time artifact with a runtime index, not a service call per request.

**B.22 — Audit logging on the synchronous path.**
*Why it matters:* §29 requires audit for significant actions. If audit writes are
synchronous and the audit store is unavailable, either actions fail or audit is
silently dropped. Both are bad; the second is worse.
*Correction:* Audit writes go to a durable local append-only journal
synchronously (cheap, local), then ship asynchronously to the audit store.
Security-critical events (authz denial, permission change, revocation, lockout,
financial action) are **fail-closed**: if the journal write fails, the action
fails. Everything else is fail-open with a dropped-record metric.

**B.23 — Four different "logging" concepts are conflated across §28, §29, §30.**
*Why it matters:* They have incompatible retention, access-control, and integrity
requirements. Storing them together means either over-retaining telemetry or
under-protecting audit.
*Correction:* Four distinct, separately-stored streams:

| Stream | Question answered | Store | Retention | Integrity | Access |
|---|---|---|---|---|---|
| **ADR** (§28) | Why did *we* build it this way? | Git, `docs/adr/` | Permanent | Git history | Public to team |
| **Decision Log** (§28 runtime) | Why did *Sentinel* choose this route/model/agent? | Per-tenant DB | Tenant-configurable | Standard | Tenant users |
| **Audit Log** (§29) | Who did what, with what authority, when? | Append-only, hash-chained | Compliance-driven | Tamper-evident | Restricted + self-auditing |
| **Telemetry** (§30) | Is the system healthy and fast? | Metrics/traces backend | Short (days–weeks) | None | Operators |

**B.24 — No SLOs, no defined "consequential action".**
*Why it matters:* §29 hinges on the word "consequential" and §31 on failure
budgets, neither of which is defined. Undefined terms in security-relevant rules
get interpreted permissively under delivery pressure.
*Correction:* Define `side_effect_class` as a closed enum in the kernel (G.4) and
derive "consequential" mechanically from it. Defer numeric SLOs to Phase 1 but
define the telemetry contract in Phase 0 so they are measurable when set.

### Governance

**B.25 — Clean-room mandate has no enforcement mechanism.**
*Why it matters:* "Do not copy proprietary source or introduce incompatible
licensing" is unenforceable by intent alone across a long build.
*Correction:* Phase 0 adds: a dependency **licence allowlist** (permissive only:
MIT/BSD/Apache-2.0/ISC/PSF; copyleft and source-available require an ADR), an
automated licence check in CI, a pinned + hash-locked lockfile, SBOM generation,
and a `CONTRIBUTING.md` clean-room clause. A dependency is added only with a
one-paragraph justification in the PR.

**B.26 — The specification does not name a language, runtime, datastore, or
deployment target, yet Phase 0 requires coding standards, testing strategy, and
CI.**
*Why it matters:* Phase 0's deliverables are literally undefinable without this.
This is the top blocking decision.
*Correction:* See N.2 for a recommendation and rationale.

**B.27 — Repository collision with the existing Phantom project.**
*Why it matters:* This repository contains Phantom, a working stdlib-only Python
FX scanner. Sentinel is a clean-room platform with a different dependency policy
and a different lifecycle. Mixing them means shared CI, shared dependency rules,
and a confused architecture map. Worse: §6's "Trading Agent" example describes
functionality Phantom already implements — building it inside Sentinel would
violate §15 (integrate, do not replace) and §38.16 (do not duplicate).
*Correction:* Two parts. (a) Repository placement is an owner decision (N.1);
recommendation is a separate repository, or at minimum a hard-isolated
`sentinel/` tree with independent CI and dependency rules. (b) **Phantom is a
candidate first integration adapter, not a feature to reimplement** — it is the
ideal proof that the Integration Gateway's neutrality actually works, because it
is a real system with a real API that Sentinel does not own.

---

## C. Proposed Sentinel Architecture

### C.1 Layer model

Nine layers. **Dependencies point downward only.** No layer may import from a
higher layer; no sideways imports within L6 or L7.

```
L9  clients            desktop · web · mobile · device            (presentation only)
─────────────────────────────────────────────────────────────────────────────────
L8  interfaces         HTTP/RPC surface · auth middleware · streaming · webhooks
─────────────────────────────────────────────────────────────────────────────────
L7  integrations       integration gateway  +  provider adapters
─────────────────────────────────────────────────────────────────────────────────
L6  capabilities       research · attention · notification · content ·
                       visual_intelligence · knowledge · commerce · scm ·
                       recommendation
─────────────────────────────────────────────────────────────────────────────────
L5  agents             adaptive agent runtime · sub-agent runtime · agent registry
─────────────────────────────────────────────────────────────────────────────────
L4  core               request lifecycle · intent · planning · dispatch (PEP) ·
                       approval gate · turn state
─────────────────────────────────────────────────────────────────────────────────
L3  intelligence       model gateway · provider adapters · orchestration · memory
─────────────────────────────────────────────────────────────────────────────────
L2  platform           config · identity · authn · authz(PDP) · tenancy ·
                       entitlements · audit · telemetry · secrets · persistence ·
                       execution(durable jobs) · registry loader
─────────────────────────────────────────────────────────────────────────────────
L1  kernel             ids · errors · result types · clock · trust tiers ·
                       side-effect classes · assertion labels · redaction
─────────────────────────────────────────────────────────────────────────────────
L0  contracts          schemas · capability manifests · event definitions ·
                       API specs · permission vocabulary        (no executable code)
```

### C.2 Resolving the upward-call problem

Core (L4) must invoke capabilities (L6) — an upward call. This is resolved by
**dependency inversion**, and it is the load-bearing detail of the whole design:

- Capability *contracts* live in L0. Core imports the contract.
- Capability *implementations* live in L6 and depend downward on L0–L3.
- At startup, a composition root (the only place in the system permitted to
  import across layers) registers implementations into the registry index.
- Core resolves `registry.get(capability_id, version)` and receives an object
  satisfying the L0 contract. **Core has no compile-time knowledge of any
  capability.**

The same pattern governs agents (L5) and integrations (L7). One composition root,
`sentinel/composition/`, is the sole exception to the import rules and is
explicitly allowlisted in the dependency checker.

### C.3 Request lifecycle (the one path everything follows)

```
  client request
      │
      ▼
 [L8] authenticate → session valid? epoch current? → correlation id assigned
      │
      ▼
 [L4] Core: build RequestContext
      { principal, tenant, workspace, scopes, entitlements, budget,
        trust_tier=T1, correlation_id, idempotency_key }
      │
      ▼
 [L4] intent resolution ──uses──► [L3] model gateway (cheap/fast tier)
      │
      ▼
 [L4] plan construction → ordered steps, each declaring
      { capability_id, action, inputs, side_effect_class, provenance_tiers }
      │
      ▼
 [L4] PEP per step ──asks──► [L2] PDP  → Permit | Deny(reason)
      │                      [L2] entitlements → allowed? quota?
      │                      [L1] authority rule → provenance vs side effect
      ▼
 [L4] approval gate: required?  ──yes──► suspend → notify → await human
      │                                   (durable; survives restart)
      ▼no
 [L2] execution: durable step run, idempotency-keyed, budget-decremented
      │
      ├──► [L6] capability  ──► [L7] integration adapter ──► external service
      ├──► [L3] model gateway ──► provider adapter ──► model
      └──► [L3] memory
      │
      ▼
 [L2] audit record + decision record + telemetry span emitted per step
      │
      ▼
 [L4] response assembly (assertion-labelled) → [L8] → client
```

Every consequential action in Sentinel passes through this path. There is no
second path. That is what makes §29 (transparency) and §32 (least privilege)
enforceable rather than aspirational.

### C.4 Key subsystem contracts (shape only — not implementations)

**Model Gateway (L3).** Callers submit a `ModelRequest` declaring
*requirements* — task class, required capabilities (tool use / structured output
/ vision / streaming), quality tier, latency budget, cost ceiling, and data
classification. The gateway selects a route by policy (preference → capability
match → health → cost/latency → fallback chain), executes through a provider
adapter, and returns a `ModelResponse` carrying content, the actual model and
version used, token/cost accounting, latency, and a `route_trace`. Callers never
name a provider. Data classification can *exclude* providers (e.g. no
`RESTRICTED` data to a provider not covered by an agreement) — this is a policy
input, not adapter logic.

**Prompt Orchestration (L3).** A `PromptContract` is a structured, versioned,
serialisable object — never a formatted string — with exactly the fields §5
requires: objective, context refs, scope, constraints, `files_allowed`,
`files_forbidden`, acceptance criteria, required tests, documentation
requirements, security requirements, blueprint compliance refs, and self-review
directives. Two consequences: contracts are diffable and testable, and the
`files_forbidden` list is **enforced by the executing capability**, not by
politely asking a model to comply. Rendering to provider-specific format is the
adapter's job.

**Memory (L3).** Scoped tree per B.12, contract per B.16.

**Adaptive Agent Runtime (L5).** An agent is a *configuration*, not a class:
identity, workspace binding, granted capability ids, memory scope, permission
ceiling, budget envelope, persona/tone (never integrity), and sub-agent
definitions. Specialisation is data. Sub-agents are the same structure with
monotonically attenuated authority. Adding a "Trading Agent" is seeding a
configuration record, not writing a subclass.

**Integration Gateway (L7).** `Sentinel → Capability Contract → Provider Adapter
→ External Service` exactly as §14 specifies. Adapters are the only code allowed
to know a vendor's name, and they are imported only by the gateway. Each adapter
declares supported operations, required OAuth scopes, rate limits, health check,
idempotency semantics, and a conformance-suite result.

---

## D. Repository Structure

Assumes the isolated-tree option (N.1). A separate repository uses the same tree
minus the `sentinel/` prefix and the Phantom coexistence notes.

```
/
├─ phantom/                          # EXISTING — untouched. Candidate L7 adapter target.
├─ tests/                            # EXISTING — Phantom's tests.
│
├─ sentinel/
│  ├─ contracts/                     # L0 — language-neutral source of truth. No code.
│  │  ├─ capability/
│  │  │  ├─ capability.schema.json   # the manifest schema (F)
│  │  │  └─ manifests/               # one .yaml per capability
│  │  ├─ events/
│  │  │  ├─ audit.schema.json
│  │  │  ├─ decision.schema.json
│  │  │  └─ telemetry.schema.json
│  │  ├─ api/openapi.yaml            # client ↔ platform surface
│  │  ├─ policy/scopes.yaml          # permission vocabulary + role templates
│  │  └─ interfaces/                 # abstract interface definitions per subsystem
│  │
│  ├─ kernel/                        # L1 — zero third-party dependencies, ever.
│  │  ├─ ids.py  errors.py  result.py  clock.py
│  │  ├─ trust.py                    # TrustTier + authority rule
│  │  ├─ effects.py                  # SideEffectClass
│  │  ├─ assertions.py               # FACT/INFERENCE/ESTIMATE/RECOMMENDATION/UNKNOWN
│  │  └─ redaction.py
│  │
│  ├─ platform/                      # L2
│  │  ├─ config/  identity/  authn/  authz/          # authz = PDP
│  │  ├─ tenancy/  entitlements/  secrets/
│  │  ├─ audit/  telemetry/  persistence/  execution/
│  │  └─ registry/                   # manifest loader + runtime index
│  │
│  ├─ intelligence/                  # L3
│  │  ├─ gateway/                    # routing, health, budget, fallback
│  │  ├─ providers/                  # provider adapters — imported ONLY by gateway
│  │  ├─ orchestration/              # PromptContract, plans, steps
│  │  └─ memory/
│  │
│  ├─ core/                          # L4 — thin. Imports contracts only.
│  │  ├─ lifecycle/  intent/  planning/  dispatch/  approval/  state/
│  │
│  ├─ agents/                        # L5
│  ├─ capabilities/                  # L6 — one package each, no sideways imports
│  │  ├─ research/  attention/  notification/  content/
│  │  ├─ visual_intelligence/  knowledge/  commerce/  scm/  recommendation/
│  │
│  ├─ integrations/                  # L7
│  │  ├─ gateway/
│  │  └─ adapters/                   # only place vendor names may appear
│  │
│  ├─ interfaces/                    # L8
│  ├─ clients/                       # L9 — empty until Phase 9
│  └─ composition/                   # THE ONLY cross-layer importer. Allowlisted.
│
├─ docs/
│  ├─ sentinel/
│  │  ├─ ARCHITECTURE_PROPOSAL.md    # this document
│  │  ├─ architecture/               # layer map, request lifecycle, threat model
│  │  ├─ adr/                        # 0001-…md, ADR-TEMPLATE.md
│  │  ├─ capabilities/               # generated capability catalogue
│  │  ├─ standards/                  # coding, docs, security, testing standards
│  │  └─ runbooks/
│
├─ tools/
│  ├─ validate_manifests.py          # capability manifest validation
│  ├─ check_dependencies.py          # import-direction enforcement
│  ├─ check_licences.py              # dependency licence allowlist
│  └─ generate_arch_map.py           # machine-readable architecture map (§34)
│
├─ tests/sentinel/                   # mirrors sentinel/ tree
│  ├─ unit/  contract/  policy/  integration/  adversarial/  architecture/
│
└─ .github/workflows/ci.yml
```

**Test tree mirrors source tree.** `tests/sentinel/architecture/` holds the tests
that fail the build when the architecture is violated — these are as important
as any functional test.

---

## E. Module Ownership & Dependency Rules

### E.1 Ownership

Every module has exactly one owning concept and one interface. No module owns two
things; no concept is owned by two modules.

| Module | Owns | Must not own |
|---|---|---|
| `kernel` | Primitive types, ids, errors, trust tiers, effect classes, assertion labels | Any business logic, any I/O |
| `platform/authz` | The PDP: all authorization decisions | Enforcement, identity, entitlements |
| `platform/entitlements` | Plan → capability/quota resolution | Authorization, billing integration |
| `platform/audit` | Tamper-evident record of consequential actions | Metrics, decision rationale |
| `platform/telemetry` | Logs, metrics, traces, correlation propagation | Audit, anything security-critical |
| `platform/execution` | Durable step execution, idempotency, retries | Planning, capability semantics |
| `platform/registry` | Loading, validating, indexing manifests | Invoking capabilities |
| `intelligence/gateway` | Provider selection, routing, health, budget enforcement | Prompt content, business logic |
| `intelligence/orchestration` | PromptContract, plan/step structures | Executing steps, choosing providers |
| `intelligence/memory` | Scoped memory records, retrieval, retention | Knowledge extraction (that's `capabilities/knowledge`) |
| `core` | Request lifecycle, intent, planning, dispatch, approval, turn state | Any capability's domain logic |
| `agents` | Agent configuration, lifecycle, sub-agent attenuation | Domain specialisation (that's configuration data) |
| `capabilities/*` | Exactly one declared `responsibility` | Anything another capability declares |
| `integrations/adapters/*` | One vendor's protocol translation | Business decisions, policy |
| `interfaces` | Transport, serialisation, auth middleware | Business logic of any kind |
| `clients` | Presentation | All business logic (§36, §38.19) |

### E.2 Dependency rules (normative)

1. **Downward only.** A module at layer N may import from layers `< N`. Never
   from `>= N`, except as stated below.
2. **No sideways imports** between packages inside `capabilities/`,
   `integrations/adapters/`, or `intelligence/providers/`. Capabilities compose
   through Core; adapters never know about each other.
3. **`core` may not import** `capabilities/`, `agents/`, `integrations/`, or
   `intelligence/providers/`. It imports contracts (L0) and resolves at runtime.
4. **`kernel` imports nothing** — not from the project, not from third parties.
   Standard library only, permanently.
5. **`contracts` contains no executable code.** Schemas and interface definitions
   only.
6. **Vendor names appear only** in `integrations/adapters/` and
   `intelligence/providers/`. A CI grep asserts this (with an allowlist for docs
   and lockfiles).
7. **`composition/` is the single allowlisted cross-layer importer.** Nothing
   else may import from a higher layer, ever.
8. **No circular imports**, at any granularity.
9. Every dependency direction rule is enforced by `tools/check_dependencies.py`
   in CI. A rule that is not machine-checked is a suggestion, not a rule.

### E.3 Anti-erosion mechanisms

- Import-direction check (rules 1–8) — CI-blocking.
- Capability manifest `responsibility` uniqueness — CI-blocking (prevents B.6/B.7
  class duplication).
- Vendor-name grep — CI-blocking.
- Generated architecture map (`docs/sentinel/architecture/map.json`) — regenerated
  each build; a diff without a corresponding ADR fails review.
- Public-symbol budget per module — a soft warning that flags god objects early.

---

## F. Capability Registry Design

### F.1 Purpose

The registry is the mechanism that makes §33 and §38.16 enforceable. It answers,
mechanically: *does something already own this responsibility?* If yes, adding a
second owner fails CI.

### F.2 Manifest fields

Every capability declares a manifest at
`sentinel/contracts/capability/manifests/<id>.yaml`.

| Field | Required | Purpose |
|---|---|---|
| `id` | ✔ | Stable, globally unique, snake_case. Never reused. |
| `version` | ✔ | Semantic version of the *contract*, not the implementation. |
| `name`, `purpose` | ✔ | Human-readable; `purpose` is one sentence. |
| `responsibility` | ✔ | **Unique across the registry.** The anti-duplication key. |
| `owner` | ✔ | Accountable module path + team/person. |
| `interface` | ✔ | Path to the L0 contract it satisfies. |
| `actions[]` | ✔ | Per action: `name`, `inputs`, `outputs`, `side_effect_class`, `required_scopes`, `idempotent`, `max_permission_level`. |
| `required_scopes` | ✔ | Union of scopes the capability may ever request. Ceiling for attenuation. |
| `max_permission_level` | ✔ | 0–4. Registry-enforced ceiling (see B.3). |
| `accepted_trust_tiers` | ✔ | Which input trust tiers it will process. |
| `data_classification` | ✔ | Highest classification it may touch. |
| `dependencies[]` | ✔ | Other capability ids + platform services. Must be acyclic. |
| `failure_behavior` | ✔ | `fail_closed` \| `fail_open` \| `degrade`, plus timeout, retry policy, circuit-breaker config. |
| `audit_events[]` | ✔ | Event types emitted. Validated against the audit schema. |
| `budget_class` | ✔ | Expected cost/latency profile for routing and quotas. |
| `availability` | ✔ | `stable` \| `beta` \| `experimental` \| `deprecated`. |
| `entitlement_key` | ✔ | Which entitlement gates it (`null` = always available). |
| `replacement_path` | ✔ | How to swap the implementation; for `deprecated`, the successor id. |
| `tests` | ✔ | Path to its contract test suite. Validated to exist. |

### F.3 Validation rules (CI-blocking)

1. Manifest validates against `capability.schema.json`.
2. `id` unique; `responsibility` unique (normalised).
3. `dependencies` all resolve and form a DAG.
4. `required_scopes` all exist in `contracts/policy/scopes.yaml`.
5. `side_effect_class` ∈ `{FINANCIAL, PROVISIONING, DESTRUCTIVE, EXECUTE_IRREVERSIBLE}`
   ⟹ `max_permission_level ≤ 3`.
6. `audit_events` validate against the audit event schema.
7. Declared `tests` path exists and is non-empty.
8. Every implementation package in `capabilities/` has a manifest, and every
   manifest has an implementation (or is marked `planned`).
9. `interface` path exists in L0.

### F.4 The anti-duplication gate

Before writing any new functionality, `tools/validate_manifests.py --search
"<responsibility phrase>"` reports overlapping existing responsibilities. A PR
adding a capability whose `responsibility` is a near-duplicate (normalised token
overlap above threshold) fails CI with the conflicting id, forcing an explicit
decision: extend the existing capability, or write an ADR justifying the split.

*This is the single most important governance mechanism in the proposal.* §34's
warnings about duplication and feature sprawl are otherwise unenforceable.

---

## G. Security Baseline

### G.1 Principles

Deny by default · least privilege · monotonic attenuation · fail closed on
security decisions · no ambient authority · every consequential action audited ·
secrets never in application storage · tenant isolation proven by test.

### G.2 Trust Tiers (kernel primitive — the response to B.11)

| Tier | Source | May instruct? | May authorize? |
|---|---|---|---|
| **T0 Platform** | System prompts, config, code | Yes | Yes (as policy) |
| **T1 Principal** | Authenticated user input this turn | Yes, within user's own scopes | Yes, up to user's scopes |
| **T2 Tenant** | Workspace docs, memory, prior turns, stored content | Informational only | **Never** |
| **T3 External** | Web pages, inbound email/chat, third-party payloads, OCR text | Informational only | **Never** |

**The Authority Rule.** *Authority never flows from content.* Only an
authenticated principal's request, evaluated by the PDP, authorises an action.
Consequences, all enforced in the dispatcher:

1. T2/T3 content is delimited and labelled in every prompt, never placed in
   instruction position.
2. A plan step whose provenance includes T2/T3 and whose `side_effect_class` is
   `EXECUTE_*` or above requires explicit human approval, regardless of the
   configured permission level. This is a hard override, not a default.
3. Content can never introduce a capability, scope, or tool not already granted
   for the turn. The available-tool set is fixed before untrusted content is read.
4. Provenance is tracked per plan step and recorded in audit.

### G.3 Identity, authentication, authorization, licensing, entitlements — kept separate (§11)

- **Identity** — who exists. Accounts, users, devices, agents-as-principals. No
  permission knowledge.
- **Authentication** — proving identity. Sessions, tokens, MFA, device
  credentials, pairing. Issues principals; grants nothing.
- **Authorization (PDP)** — a pure decision function over
  `(principal, scopes, resource, action, context)`. Deny by default.
- **Licensing** — commercial state of an account. Never consulted in business
  logic.
- **Entitlements** — the resolved capability/quota grants derived from licensing.
  Consulted at exactly one place: the capability invocation boundary.

Scope grammar: `<capability>:<action>:<resource_scope>` (e.g.
`research:execute:workspace`, `scm:create_pr:repo/acme/*`). Roles (§11: Owner,
Administrator, Manager, Employee, Contractor, Client, Guest) are **bundles of
scopes** — presentation and defaults only. Enforcement is always scope-based.

### G.4 Side-effect classes (kernel primitive)

`READ` · `ANALYZE` · `DRAFT` · `EXECUTE_REVERSIBLE` · `EXECUTE_IRREVERSIBLE` ·
`DESTRUCTIVE` · `FINANCIAL` · `PROVISIONING`

Mapping to §13's permission ladder:

| Class | Max autonomous level | Confirmation |
|---|---|---|
| READ, ANALYZE | 4 | none |
| DRAFT | 4 | none (nothing leaves the system) |
| EXECUTE_REVERSIBLE | 4 (rule-bounded, announced) | rule + notification |
| EXECUTE_IRREVERSIBLE | 3 | explicit approval |
| FINANCIAL, PROVISIONING | 3 | explicit approval + value ceiling |
| DESTRUCTIVE | 3 | explicit approval + typed confirmation + cooling-off |

### G.5 Sessions, tokens, revocation (response to B.17)

Access tokens ≤15 min · rotating refresh tokens with reuse detection ·
server-side session records · **per-principal session epoch** — revocation, role
change, device removal, or emergency lockout increments it and invalidates every
outstanding token · agent capability tokens are attenuated, tenant-bound,
correlation-bound, task-TTL, non-refreshable, and re-check the parent epoch at
each invocation.

### G.6 Tenant isolation

Tenant id is carried in the request context, never inferred from user input.
Every persistence query is scoped at the repository layer — no raw tenant-free
query may exist. Cross-tenant access is architecturally impossible for
capabilities: the attenuated token is bound to one tenant. Proven by a mandatory
isolation test suite (H.3) that includes the founder-principal case (B.18).

### G.7 Secrets & data

No credential in application storage (B.20). Envelope encryption with per-tenant
key derivation; TLS everywhere in transit; encryption at rest. Data
classification labels (`PUBLIC` / `INTERNAL` / `CONFIDENTIAL` / `RESTRICTED`)
drive retention, egress, and provider eligibility. Redaction at the logging
boundary — a structured logger that cannot serialise a secret type. Financial
integrations default to read-only, minimum scope, re-consent to widen, revocable
(§16).

### G.8 Supply chain (response to B.25)

Licence allowlist (MIT / BSD / Apache-2.0 / ISC / PSF; anything else needs an
ADR) · pinned, hash-locked lockfile · SBOM per build · dependency vulnerability
scan · secret scanning on every commit · static analysis · new dependency
requires written justification in the PR · clean-room clause in `CONTRIBUTING.md`.

### G.9 Rate limiting & abuse

Per-principal, per-tenant, per-capability rate limits. Budget envelopes (B.13) as
a hard ceiling. Recursion depth and fan-out bounds on sub-agents. Global platform
circuit breaker.

---

## H. Testing Strategy

### H.1 Philosophy

§38.9 — *test before trust*. Tests are organised by **what kind of failure they
prevent**, not by an arbitrary pyramid ratio.

### H.2 Test levels

| Level | Prevents | Scope | Speed | Gate |
|---|---|---|---|---|
| **L1 Unit** | Logic errors | One module, no I/O | <10ms | 80% line coverage overall |
| **L2 Contract** | Interface drift | One contract, both sides | fast | Every L0 contract has one |
| **L3 Policy** | Permission leakage | PDP, entitlements, attenuation, isolation | fast | **95% coverage, mandatory** |
| **L4 Integration** | Wiring errors | Multiple modules + fakes | seconds | Per subsystem |
| **L5 Adversarial** | Injection, confused deputy | Full dispatch path | seconds | Corpus must pass |
| **L6 Architecture** | Structural erosion | Static analysis of the tree | fast | **Blocking** |
| **L7 E2E smoke** | Total breakage | Deployed stack | minutes | Pre-release |

### H.3 Mandatory suites (cannot be waived)

1. **Policy golden tests** — an exhaustive table of
   `(principal, role, scope, resource, action) → expected decision`. Every new
   scope adds rows. A change in outcome must be an intentional, reviewed diff.
2. **Tenant isolation** — for every capability, prove tenant A cannot reach
   tenant B's data, including the founder/internal principal case (B.18).
3. **Attenuation monotonicity** — property test: a sub-agent's scope set is
   always a subset of its parent's, at arbitrary nesting depth.
4. **Revocation** — a revoked principal cannot complete an in-flight multi-step
   execution; the next step is denied.
5. **Adversarial corpus** — a maintained set of injection payloads (in web
   content, email bodies, document text, image OCR, filenames, integration
   payloads) asserting that none causes a tool invocation, scope escalation, or
   approval bypass. **Grows with every incident.**
6. **Architecture tests** — dependency direction, no cycles, manifest validity,
   responsibility uniqueness, vendor-name containment, `kernel` has zero
   dependencies, `core` imports no capability.

### H.4 Determinism

Unit and contract tests never touch the network — enforced by a socket-blocking
fixture, not by convention. Time is injected via `kernel/clock`; `now()` is never
called directly. Randomness is seeded. Model calls in tests go through a
deterministic fake adapter or recorded fixtures. **Zero flaky tests tolerated** —
a flaky test is quarantined and fixed, never re-run until green.

### H.5 Provider conformance suites

Every model provider adapter and every integration adapter must pass a shared
conformance suite proving identical behaviour against the neutral contract:
success, timeout, rate limit, auth failure, malformed response, partial/streamed
response, cancellation, idempotent retry. **An adapter that has not passed
conformance cannot be registered.** This is what makes §2's replaceability claim
real rather than hopeful.

### H.6 What is deliberately not tested in Phase 0

No load testing, no chaos engineering, no browser/UI testing, no mutation
testing. These arrive with the subsystems they measure.

---

## I. Observability Strategy

### I.1 Four streams, four stores

Per B.23 — ADR (git), Decision Log (tenant DB), Audit Log (append-only,
hash-chained), Telemetry (metrics/traces). Different retention, different
integrity, different access control. Never merged.

### I.2 Correlation

A `correlation_id` is generated at the L8 edge and propagated through every
layer, every model call, every adapter call, every audit record, and returned to
the client on both success and error. Nested work carries `parent_span_id` and
`root_correlation_id`. **The acceptance test for §30 is concrete:** given a
correlation id from a user-visible error, an engineer can reconstruct the full
path — intent, plan, each step, each policy decision, each provider call, each
retry, the failure, and the user-facing message — without reading application
source.

### I.3 Canonical structured log record

One structured event per meaningful operation, with: timestamp, level,
correlation/span ids, tenant, workspace, principal (id, type), agent id, capability
id + action, model + version, side-effect class, permission level, approval
reference, trust tiers of inputs, duration, outcome, error type + code, token
counts, cost, retry count, budget remaining. Free-text log lines are for
development only; production emits structured events. **Redaction is a property
of the logger, not the caller** — secret and PII types cannot be serialised.

### I.4 Metrics (initial set)

Request rate / latency / error rate by capability · provider latency, error rate,
fallback rate, health state · token and cost per tenant / capability / model ·
budget exhaustion events · policy denials by reason · approval queue depth and
wait time · durable step retries and dead letters · integration health · audit
write failures · adversarial-detection hits.

### I.5 Security events

Authn failure, authz denial, privilege change, revocation, lockout, founder-
entitlement use, cross-scope memory bridge, financial action, destructive action,
injection detection. These are audit records **and** metrics, and they are
fail-closed (B.22).

### I.6 Cost as a first-class signal

Token and currency cost are attributed per request, tenant, capability, agent,
and model — required for §4 cost-aware routing, §26 entitlement enforcement, and
B.13 budget control. Cost is measured from day one; retrofitting attribution is
painful.

---

## J. Architecture Decision Record System

### J.1 Scope

An ADR is required for: any dependency direction change, any new third-party
dependency, any new capability, any provider or vendor selection, any security or
permission model change, any deviation from this blueprint, and any change to the
build order.

An ADR is *not* required for: implementation detail within an established
boundary, bug fixes, refactors that preserve contracts.

### J.2 Location and lifecycle

`docs/sentinel/adr/NNNN-kebab-title.md`, zero-padded sequential, never renumbered,
never deleted. Statuses: `Proposed` → `Accepted` | `Rejected`; later
`Deprecated` | `Superseded by ADR-NNNN`. A superseded ADR stays in place with a
forward link — the record of *why we changed our mind* is the valuable part.

### J.3 Template

```markdown
# ADR-NNNN: <Title>

- **Status:** Proposed | Accepted | Rejected | Deprecated | Superseded by ADR-NNNN
- **Date:** YYYY-MM-DD
- **Deciders:** <names/roles>
- **Actor:** <who proposed>
- **Supersedes:** ADR-NNNN | none
- **Blueprint refs:** §N, §N

## Context
The forces at play: technical constraints, product requirements, prior decisions,
and what specifically triggered this decision now.

## Decision
What we are doing. Present tense, unambiguous, specific enough to be verifiable.

## Alternatives Considered
For each: what it was, why it was viable, why it was not chosen. A single
alternative of "do nothing" is acceptable only if genuinely evaluated.

## Consequences
### Positive
### Negative / accepted costs
### Neutral
### Risks introduced and how they are mitigated

## Compliance
Which Engineering Constitution items (§38.1–23) this decision upholds, and any it
strains — with justification.

## Verification
How we will know this decision was implemented: tests, CI checks, or metrics.

## Revisit Criteria
The conditions under which this decision should be reconsidered.
```

`Verification` and `Revisit Criteria` are additions beyond §28's list. Without
`Verification`, ADRs drift from reality; without `Revisit Criteria`, decisions
outlive their context.

### J.4 Runtime decision logs (distinct from ADRs)

Runtime routing decisions — why this model, this agent, this fallback, this
denial — are structured `DecisionRecord` rows in the tenant database, surfaced to
the user on request ("why did you do that?"). They are a product feature and a
debugging tool. They are not ADRs and share no storage with them.

---

## K. Phase 0 Acceptance Criteria

Phase 0 is complete when **all** of the following are true and verified. Each has
a stated verification method; a criterion that cannot be verified is not a
criterion.

| # | Criterion | Verified by |
|---|---|---|
| K1 | Directory tree from Section D exists, with a `README.md` in each top-level module stating its owned responsibility and its permitted dependencies. | Inspection + a test asserting every module dir has a README with the required sections |
| K2 | `tools/check_dependencies.py` enforces every rule in E.2 and fails the build on violation. | Deliberate violation fixtures fail CI |
| K3 | `capability.schema.json` exists, is documented, and validates. | Schema self-test |
| K4 | `tools/validate_manifests.py` implements all F.3 rules, including responsibility uniqueness and the F.5 permission-ceiling rule. | Invalid-manifest fixtures fail CI |
| K5 | At least two reference manifests exist for capabilities *not yet implemented* (`availability: planned`) to prove the schema is usable. | Validator passes |
| K6 | ADR template exists; ADR-0001 records the language/runtime decision; ADR-0002 records the layer model and dependency direction; ADR-0003 records the trust-tier and authority rule. | Files present, statuses `Accepted` |
| K7 | Coding standards, documentation standards, testing standards, and security standards documents exist in `docs/sentinel/standards/`. | Review |
| K8 | Lint, format, and strict type-checking configured; the (nearly empty) tree passes with zero warnings. | CI green |
| K9 | Test harness runs; the six architecture tests in H.3.6 exist and pass. | CI green |
| K10 | CI pipeline runs: format → lint → typecheck → architecture tests → unit tests → manifest validation → licence check → secret scan → SBOM. Every stage blocking. | CI green on a PR |
| K11 | Dependency licence allowlist enforced; lockfile pinned and hash-locked. | Disallowed-licence fixture fails CI |
| K12 | Secret scanning active on all commits; a planted test secret is caught. | Deliberate fixture |
| K13 | `tools/generate_arch_map.py` emits `docs/sentinel/architecture/map.json` describing modules, layers, dependencies, and capabilities; CI regenerates and fails on uncommitted drift. | CI green |
| K14 | Threat model document exists covering trust tiers, the authority rule, the confused-deputy scenario, and the top 10 abuse cases. | Review |
| K15 | `CONTRIBUTING.md` documents the clean-room policy, dependency-addition process, ADR requirement, and the anti-duplication gate. | Review |
| K16 | `kernel/` contains only the primitives named in D and has zero dependencies. | Architecture test |
| K17 | No production business logic exists anywhere in the tree. Phase 0 ships governance and scaffolding only. | Review — this is a *negative* criterion and is deliberately part of the definition of done |
| K18 | A new engineer can clone, run one setup command, and get a green build, following `docs/sentinel/standards/development.md`. | A person who has not seen the repo does it |

---

## L. Phase 0 Implementation Sequence

Fourteen steps, ordered so that each is verifiable before the next begins. Steps
1–2 are blocked on owner decisions (Section N).

| Step | Work | Blocked by |
|---|---|---|
| 1 | Record repository placement decision (ADR-0000) and create the isolated tree root. | N.1 |
| 2 | Record language/runtime/tooling decision (ADR-0001). Set up lint, format, strict types, test runner, lockfile. | N.2 |
| 3 | Create the directory skeleton from Section D with per-module `README.md` files declaring responsibility + permitted dependencies. | 1, 2 |
| 4 | Write `docs/sentinel/standards/`: coding, documentation, testing, security, development-setup. | 2 |
| 5 | Write the ADR template and ADR-0002 (layer model + dependency direction) and ADR-0003 (trust tiers + authority rule). | 3 |
| 6 | Build `tools/check_dependencies.py` + its violation fixtures + architecture tests. | 3, 5 |
| 7 | Write `capability.schema.json` and the capability registry design doc. | 5 |
| 8 | Build `tools/validate_manifests.py` including the anti-duplication gate; add two `planned` reference manifests. | 7 |
| 9 | Write `contracts/policy/scopes.yaml` — the initial permission vocabulary and role templates (declaration only; no PDP yet). | 7 |
| 10 | Write the threat model document (trust tiers, authority rule, abuse cases). | 5 |
| 11 | Build `tools/check_licences.py` + allowlist; configure SBOM generation and secret scanning. | 2 |
| 12 | Build `tools/generate_arch_map.py`; commit the initial `map.json`; add the drift check. | 6, 8 |
| 13 | Assemble the CI pipeline (K10) with every stage blocking; prove each gate with a deliberate-failure fixture. | 6, 8, 11, 12 |
| 14 | Write `CONTRIBUTING.md`; validate K18 with a clean clone; final Phase 0 review against Section K. | all |

**Estimated shape:** steps 1–5 are documentation and setup; 6–13 are tooling
(the only real code in Phase 0, and it is *build* tooling, not product code);
14 is verification. No product functionality is delivered in Phase 0 — that is
intentional and is criterion K17.

---

## M. Explicitly Deferred Work

Not built in Phase 0, by design. Listing them prevents both scope creep and the
worry that they were forgotten.

**Deferred to later phases (planned):**

| Deferred | Until | Why |
|---|---|---|
| Any capability implementation | Phase 6 | Contracts and registry must exist first |
| Model gateway implementation | Phase 2 | Needs config, telemetry, budget from Phase 1 |
| PDP implementation | Phase 1 | Phase 0 declares the vocabulary only |
| Persistence layer and migrations | Phase 1 | First real schema, first migration together |
| Durable execution engine | Phase 1 | Required before orchestration (B.15) |
| Memory subsystem | Phase 3 | Needs tenancy and persistence |
| Sentinel Core | Phase 4 | Needs gateway, memory, policy |
| Adaptive agents | Phase 5 | Needs Core |
| Integration adapters (incl. a Phantom adapter) | Phase 7 | Needs the integration gateway |
| Voice pipeline | Phase 10 | Independent of core correctness |
| Any UI, any theme, any animation | Phase 9–10 | §36 |
| Mobile clients | After Phase 9 | Core interfaces must be stable |
| Billing/payment integration | With Phase 1 entitlements, at the earliest | Licensing state can be seeded manually far longer than expected |

**Deliberately not planned at all yet (avoid speculative building):**

- Any vector database, embedding model, or RAG pipeline choice — deferred to
  Phase 3 with an ADR. Choosing now is choosing blind.
- Any web framework, ORM, or message queue — deferred to Phase 1 with an ADR.
  §39 explicitly forbids installing these speculatively.
- Multi-region, data residency, and HA topology — needs a compliance answer (N.6).
- Marketplace / third-party capability ecosystem — a large security surface, no
  current requirement.
- Fine-tuning, model hosting, self-hosted inference.
- Agent-to-agent protocols beyond parent/child attenuation.
- Real-time collaborative editing / multi-user concurrent sessions.
- Offline mode and local-first sync.
- SSO/SAML/SCIM — Enterprise plan concern, Phase 1 design must not preclude it.

---

## N. Questions Requiring Owner Decision

Ordered by how much they block Phase 0.

**N.1 — Repository placement. (Blocking, step 1.)**
This repository is Phantom, a working stdlib-only Python FX scanner with its own
dependency policy and release cadence. Options: (a) **separate repository for
Sentinel** — cleanest isolation, independent CI and dependency rules; (b)
**isolated `sentinel/` tree in this repo** — one place to look, but shared CI and
a confusing architecture map; (c) monorepo with formal workspace tooling —
correct at scale, overhead now.
**Recommendation: (a) a separate repository**, with Phantom integrated later via
an L7 adapter per §15. If the owner prefers one repo for convenience, (b) is
workable with independent CI workflows. I have written this proposal assuming (b)
so it is usable either way.

**N.2 — Language, runtime, and datastore. (Blocking, step 2.)**
Phase 0 cannot define lint, type-check, test, or CI standards without this.
**Recommendation: Python 3.12+ with strict static typing** for the backend —
it matches the existing codebase and the owner's evident familiarity, it is the
strongest ecosystem for AI/ML integration work, and strict typing plus the
architecture tests gives sufficient structural safety. Contracts are defined in
**language-neutral JSON Schema / OpenAPI** so TypeScript clients (Phase 9) can
generate types from the same source of truth without a rewrite. Datastore:
**PostgreSQL** (relational integrity for tenancy and permissions; JSON columns
where flexibility is needed; mature append-only and partitioning support for
audit). Both choices are recorded as ADRs and are revisitable.
*If the owner prefers a TypeScript-everywhere stack, that is defensible — one
language across backend and clients, better client story — but it weakens the AI
ecosystem story and does not reuse the existing Python codebase. Please choose.*

**N.3 — Deployment target and operating model. (Blocking for Phase 1, useful now.)**
Single-tenant self-hosted, multi-tenant SaaS, or both? This changes the tenancy
implementation substantially (schema-per-tenant vs row-level isolation), the
secrets architecture, and the licensing enforcement model. **Recommendation:
design contracts for multi-tenant, deploy single-tenant first** — multi-tenancy
is nearly impossible to retrofit, but running it is premature.

**N.4 — First dogfooding domain.**
§1 forbids hard-coding an industry, and this proposal honours that. But a first
*real* user validates the architecture far better than a synthetic one. Which
domain will the owner personally use first? This changes only the seed
configuration data and the first integration adapter, never the core.

**N.5 — Model provider set and budget.**
Which providers should the gateway target first, and what is the monthly spend
ceiling? Affects the fallback chain design and the initial budget envelopes. At
least two providers are needed at Phase 2 to prove neutrality is real.

**N.6 — Compliance and data residency targets.**
SOC 2? GDPR? Any regulated financial data (§16)? This materially affects audit
retention, encryption requirements, data residency, and subprocessor agreements.
It is far cheaper to build for a known target than to certify later. If the
answer is "none yet", say so explicitly and I will design for
GDPR-shaped-defaults without certification overhead.

**N.7 — Licensing of the Sentinel codebase itself.**
Proprietary, source-available, or open source? Determines the dependency licence
allowlist strictness (G.8) and the `CONTRIBUTING.md` clean-room clause.

**N.8 — Phantom's relationship to Sentinel.**
Confirm the reading in B.27: Phantom is an **existing system Sentinel integrates
with** (§15), not functionality Sentinel reimplements. If the owner instead
intends Sentinel to absorb Phantom's logic, that is a significant scope change
and needs an ADR, because it contradicts §15 and §38.16.

**N.9 — Team size and access model.**
Solo owner, or multiple engineers? Determines whether CI gates need to be
advisory or blocking, and how much process overhead is justified. This proposal
assumes blocking gates, which is right for a long-lived platform regardless of
team size.

---

## O. Final Blueprint Compliance Check

Every specification section, mapped to where this proposal addresses it. Numbers
in the Addressed column reference this document.

| § | Requirement | Addressed | Notes / deviations |
|---|---|---|---|
| 1 | Domain-agnostic | C.4 (agents are configuration), M | No industry appears in any contract; §6's trading example is deliberately absent from the design |
| 2 | Sentinel as orchestrator, replaceable components | C.1, C.2, C.3 | **Deviation:** pure neutrality softened to neutral-contract + capability negotiation (B.4) |
| 3 | Core coordinates 15 concerns, not a monolith | A.2, B.1, C.3 | **Deviation:** Core narrowed to lifecycle owner; the other concerns are separate modules it calls |
| 4 | Provider-neutral model gateway | C.4, B.4, B.13 | Cost awareness upgraded to cost *enforcement* |
| 5 | Prompt orchestration, all listed fields | C.4 | `PromptContract` is a structured object; `files_forbidden` enforced in code, not by prompt |
| 6 | Core + 3 adaptive agent slots | B.5, C.4 | **Deviation:** N slots; 3 is an entitlement default |
| 7 | Agent evolution engine — recommend, never act | F.2, G.4 | All 8 required explanation fields become the `Recommendation` record type in Phase 6 |
| 8 | Research engine, shared, cited, labelled | B.6, G.2, C.4 | Single owner; FACT/INFERENCE/… is a kernel type; T3 trust tier applied |
| 9 | Scoped memory with ownership/provenance/retention | B.12, B.16, E.1 | Explicit no-ambient-inheritance rule and `MemoryBridge` for cross-scope |
| 10 | Account → Org → Workspace hierarchy | B.12, G.6 | Tenant id never inferred from input |
| 11 | Identity/authn/authz/licensing/entitlements separate | G.3 | Roles are scope bundles; enforcement is always scope-based |
| 12 | Invitations, revocation, lockout | B.17, G.5 | Session epoch makes revocation actually immediate |
| 13 | Permission levels L0–L4 | B.2, G.4 | **Clarification:** L4 = unattended, never invisible; hard ceilings for irreversible/financial/destructive |
| 14 | Integration gateway via adapters | C.1, C.4, E.2 | Vendor names confined to adapter packages, CI-enforced |
| 15 | Integrate, do not replace | B.27, N.8 | Phantom is the first test of this principle |
| 16 | Financial data boundary | B.20, G.7, G.4 | No credential in app storage; read-only default; FINANCIAL capped at L3 |
| 17 | Provider-neutral source control | D (`capabilities/scm`), G.4 | Repo deletion = DESTRUCTIVE → typed confirmation + cooling-off |
| 18 | Visual intelligence pipeline | B.7, C.1 | Stateless processing capability; observation vs inference via assertion labels |
| 19 | Permission-aware visual gallery | B.7 | Gallery is a view over `content`, not a separate store — closes the cross-workspace leak |
| 20 | Unified communications, attention triage | B.8, B.6 | Split into `attention` + `notification`; inbound content is T3 |
| 21 | Alerts & notifications | B.8, E.1 | Transport concerns isolated from triage |
| 22 | Commerce & procurement | B.3, B.6 | Composes `research`; FINANCIAL ceiling prevents autopurchase |
| 23 | Voice architecture, replaceable providers | M | Deferred to Phase 10; adapter pattern already established, so no rework |
| 24 | Cross-platform, one Sentinel | C.1 (L8/L9), E.1 | Clients hold zero business logic — architecture test enforces it |
| 25 | Device pairing & sync | B.19, G.5 | Single-use short-TTL codes; device-bound keypairs; no secrets in QR |
| 26 | Licensing & entitlements as their own layer | G.3, B.18, B.13 | Entitlements consulted at exactly one boundary; founder access audited, not exempt |
| 27 | Intellectual integrity | C.4, kernel assertions | Tone is agent configuration; integrity is a kernel type and cannot be configured away |
| 28 | Decision logs | J.1, J.4, B.23 | Two distinct things: ADRs (build-time) and DecisionRecords (runtime) |
| 29 | Transparency & audit | C.3, G.4, I.1, B.22 | "Consequential" defined mechanically via side-effect class |
| 30 | Observability from the beginning | I.1–I.6 | Concrete acceptance test for traceability (I.2) |
| 31 | Failure engineering | F.2 (`failure_behavior`), B.15, H.5 | Failure behaviour is declared per capability and conformance-tested |
| 32 | Security is architecture | G.1–G.9, H.3 | **Extension:** trust tiers and the authority rule added (B.11) |
| 33 | Capability registry | F.1–F.4 | **Extension:** added trust tiers, side-effect class, data classification, entitlement key, budget class, tests path |
| 34 | Architecture health | E.3, K13 | Every listed hazard has a machine check, not just a warning |
| 35 | Installation & onboarding | K18 | Phase 0 proves it for developers; user onboarding is Phase 9 |
| 36 | Client/UI rule | E.1, E.2, M | No UI in Phase 0; capability-backed rendering rule stated |
| 37 | Build order | L, M | **Deviation:** persistence/migrations and durable execution added to Phase 1 (B.14, B.15) |
| 38 | Engineering constitution (23 items) | Throughout; ADR `Compliance` section requires per-decision mapping | Constitution compliance is a required ADR field, not a poster |
| 39 | First assignment: architecture only | This document | No production code written; no frameworks installed; no speculative features |
| 40 | Response format A–O | This document | Complete |

**Declared deviations from the specification, requiring owner sign-off:**

1. **§3** — Sentinel Core narrowed to a request-lifecycle owner (B.1).
2. **§2/§4** — Provider neutrality implemented as neutral-contract + capability
   negotiation rather than lowest-common-denominator uniformity (B.4).
3. **§6** — N agent slots, with 3 as an entitlement default rather than an
   architectural constant (B.5).
4. **§13** — Level 4 explicitly bounded and barred from irreversible, financial,
   provisioning, and destructive classes (B.2).
5. **§37** — Persistence/migrations and durable execution added to Phase 1 ahead
   of the Model Gateway (B.14, B.15).
6. **§32/§33** — Trust tiers and the authority rule added as a foundational
   security primitive not present in the specification (B.11).

Each will be recorded as an ADR on approval.

---

READY FOR OWNER REVIEW
