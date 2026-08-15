# Sentinel AI — Approved Architecture Baseline v1.0

**Status:** APPROVED BASELINE — pending one blocking provisioning action (§C)
**Supersedes:** `ARCHITECTURE_PROPOSAL.md` (2026-08-15)
**Authority:** Owner Review Resolution, COMMAND 002
**Date:** 2026-08-15
**Scope:** Architecture and governance definition only. No production code.

> **Repository placement notice.** Owner decision N.1 mandates that Sentinel
> live in its own repository. This document currently resides in an unrelated
> repository (`aider`, which hosts the Phantom project) because that is the only
> repository in scope for the authoring session. **These artifacts are
> transitional.** Phase 0 Step 0 migrates them into the Sentinel repository and
> removes them from here. Sentinel has, and will have, **no dependency on,
> relationship to, or awareness of Phantom or any other project in this
> repository.**

---

## Table of Contents

- [A. Owner Decisions Incorporated](#a-owner-decisions-incorporated)
- [B. Remaining Contradictions](#b-remaining-contradictions)
- [C. Remaining Owner Decisions](#c-remaining-owner-decisions)
- [D. Final Layer Model](#d-final-layer-model)
- [E. Final Module Ownership Table](#e-final-module-ownership-table)
- [F. Final Capability Registry Schema](#f-final-capability-registry-schema)
- [G. Final Trust & Authority Model](#g-final-trust--authority-model)
- [H. Final Clean-Room & Dependency Policy](#h-final-clean-room--dependency-policy)
- [I. Final Testing & Architecture-Erosion Strategy](#i-final-testing--architecture-erosion-strategy)
- [J. Final Observability & Audit Strategy](#j-final-observability--audit-strategy)
- [K. Final ADR System](#k-final-adr-system)
- [L. Final Phase 0 Acceptance Criteria](#l-final-phase-0-acceptance-criteria)
- [M. Final Phase 0 Implementation Sequence](#m-final-phase-0-implementation-sequence)
- [N. Explicitly Deferred Work](#n-explicitly-deferred-work)
- [O. Updated Blueprint Compliance Check](#o-updated-blueprint-compliance-check)
- [P. Phase 0 Readiness Verdict](#p-phase-0-readiness-verdict)

---

## A. Owner Decisions Incorporated

| Decision | Ruling | Architectural change made |
|---|---|---|
| **D1** Core scope | Approved | Core owns request lifecycle + orchestration coordination only. Layer L4 in §D. Enforced by `ARCH-03` (Core may not import capabilities/agents/integrations/providers). |
| **D2** Provider neutrality | Approved: neutral contracts + capability negotiation | `ProviderCapabilities` descriptor added to the intelligence contract set (Phase 2 artifact). Callers state requirements, never provider names. Provider-specific features permitted **inside adapters only**, surfaced as declared optional capabilities. Enforced by `ARCH-06` (vendor-name containment) + provider conformance suite. |
| **D3** N adaptive agents | Approved | No numeric agent constant may exist outside entitlement seed data. `3` is the `agents.slots` default for the initial plan. Sub-agents follow the identical rule via `agents.subagent_slots`. Enforced by `ARCH-11` (magic-constant scan of agent/core modules). |
| **D4** Level 4 autonomy bounded | Approved, list extended | `SideEffectClass` enum extended with `PERMISSION_CHANGE`, `CREDENTIAL_CHANGE`, `SECURITY_POLICY_CHANGE`. All seven prohibited classes are hard-capped at `max_permission_level: 3` by registry invariant `INV-09`. A manifest violating this fails CI — policy cannot disagree with the constitution. |
| **D5** Persistence & durable execution first | Approved | `platform/persistence` and `platform/execution` are Phase 1 deliverables, sequenced **before** `intelligence/gateway`. Their L0 contracts are drafted in Phase 0 (contract only, no implementation). |
| **D6** Trust tiers + Authority Rule | Approved and **elevated to foundational** | Promoted from a security control to a kernel primitive (`kernel/trust.py`) and to Constitution item §38.24. Six machine-enforced invariants `AUTH-01`…`AUTH-06` in §G. Adversarial corpus is a blocking Phase 0 harness. |
| **§2** New constitution rule | Adopted as §38.25 | *"A rule that is not mechanically enforced where practical is only a suggestion."* Implemented via the **Rule Enforcement Classification** (§I.2): every normative rule in this baseline carries Class A/B/C. See contradiction **NC-1** — the rule needed a guard against misuse. |
| **N.1** Separate repository | Approved | Sentinel gets its own repository, history, CI, ADRs, dependency policy, release process, security controls, licensing records. No unrelated project is merged in. Repository tree in §D.4. **Blocking provisioning action, see §C.** |
| **N.2** Python 3.12+ strict typing; language-neutral contracts; PostgreSQL as initial target | Approved with qualification | Backend: Python 3.12+, strict type checking, zero-warning gate. Contracts: JSON Schema + OpenAPI in `contracts/`, no Python types as the source of truth — generated bindings only. Persistence: accessed exclusively through repository contracts; PostgreSQL-specific behavior confined to the infrastructure adapter. See **NC-4** for the qualification's practical limit. |
| **N.3** Multi-tenant SaaS from the start | Approved | Tenant boundary is mandatory in all twelve named domains (§E, `tenant_scoped` column). `TenantId` is a kernel type; it can never be inferred from user input. Machine-tested — but see **NC-3** for what Phase 0 can and cannot verify. |
| **N.4** Domain neutrality | Approved | No profession, industry, or domain term appears in any layer L0–L5. Validation domains are seed configuration only. Enforced by `ARCH-12` (domain-vocabulary scan of L0–L5). |
| **N.5** Two materially different AI providers eventually | Approved | Deferred to Phase 2. Phase 0 requires **no** provider selection and installs **no** provider SDK. The Model Gateway's seven demonstration requirements are recorded as Phase 2 acceptance criteria in §N. |
| **N.6** No certification target | Approved | Privacy- and security-conscious defaults; no certification-specific infrastructure. **Explicit prohibition added:** no document, UI string, marketing text, or code comment may claim a compliance status Sentinel has not achieved. |
| **N.7** Proprietary commercial | Approved | Licence allowlist narrowed to permissive-only, commercial-distribution-safe. Copyleft (GPL/AGPL/LGPL) and source-available (BSL/SSPL/Elastic) are **denied by default**; any exception needs an ADR *and* a legal note. Ten-field dependency register, §H. |
| **N.8** External project boundary — **CORRECTION** | Applied | All Phantom references removed from the forward-looking architecture. Sentinel does not absorb, depend on, or reference Phantom or any other external system. Future external systems connect only through the generic Integration Gateway (L7) via capability contracts. The superseded proposal is annotated at its head. |
| **N.9** CI gates blocking | Approved | Architecture, security, testing, dependency, licensing, and capability-registry gates are all blocking, single developer or not. No relaxed standard for AI-generated code; §H.5 adds an AI-authorship control. |
| **§12** Clean-room provenance | Adopted | Full policy in §H, including a machine-readable approved-dependency register enforced against the lockfile (Class A) and an authorship attestation (Class C). |
| **§13** Kernel rule correction | Applied | "Imports nothing, ever" replaced by: *the kernel has zero Sentinel application-layer dependencies and depends only on explicitly approved foundational runtime/standard-library facilities.* Allowlist starts empty; additions require an ADR. Enforced by `ARCH-05`. |
| **§15** Financial safety boundary | Preserved | `FINANCIAL` side-effect class capped at L3; read-only default posture; no financial credential in application storage; external financial systems remain external. |
| **§16** Capability ownership | Preserved + strengthened | Responsibility uniqueness is CI-blocking with a **machine-readable ADR waiver** (`INV-06`), because an ADR that CI cannot read is not an exception mechanism — see **NC-2**. |
| **§17** Dependency direction | Preserved | Eight rules, all Class A, enforced by `ARCH-01`…`ARCH-08`. Composition root is the single declared wiring boundary. |
| **§18** Observability/audit separation | Preserved + strengthened | Four concerns separated (§J). Audit never transits the telemetry pipeline. Security-critical audit is fail-closed. Redaction is a property of the emitter type, not caller discipline. |
| **§19** Two decision-record concepts | Preserved | ADRs (git, engineering) and Runtime Decision Records (tenant DB, user-visible) — separate stores, separate scopes, no shared code path. New: user-visible denial explanations use abstract reason codes, not policy internals (**NC-6**). |
| **§20** Architecture erosion testing | Preserved + expanded | `tests/architecture/` with twelve blocking checks, §I.3. |
| **§21** Phase 0 non-product | Preserved | Phase 0 delivers governance, contracts, and build tooling only. Criterion **L17** is a negative criterion: the absence of product logic is part of "done". |

---

## B. Remaining Contradictions

Six issues introduced or left unresolved by the owner decisions. None is fatal;
all have a recommended resolution, and each resolution is reflected in the
baseline below.

### NC-1 — The mechanical-enforcement rule can be read as licensing non-compliance

**Issue.** §2's new constitution rule ends with *"…is only a suggestion."* Read
literally, it tells an engineer that any rule they cannot automate is optional.
Several of Sentinel's most important rules are only partially automatable: the
Authority Rule at runtime, "no business logic in clients," the clean-room
authorship policy, and semantic (not syntactic) capability-responsibility
overlap.

**Impact.** The rule intended to *strengthen* enforcement becomes the standard
justification for skipping the hardest rules — exactly inverting its purpose.
This is the most likely way this baseline degrades in practice.

**Recommended resolution.** Adopt the rule with a mandatory classification.
Every normative rule in Sentinel carries exactly one enforcement class, and
**no rule may be unclassified**:

| Class | Meaning | Requirement |
|---|---|---|
| **A — Machine-enforced** | Automated check, CI-blocking | Default. A rule that *can* be Class A **must** be Class A. |
| **B — Machine-detected** | Automated signal, non-blocking, requires triage | Permitted only where false positives are unavoidable; must have a named triage owner. |
| **C — Manual gate** | Human review against a written checklist | Requires (i) a documented reason automation is impractical, (ii) a named accountable reviewer, (iii) a PR-template checklist item, (iv) a revisit date. |

A Class C rule is **not** a suggestion — it is a rule with a human enforcement
mechanism. Downgrading a rule from A to C requires an ADR. Constitution §38.25
is recorded with this classification attached, so the sentence cannot be quoted
without it.

### NC-2 — "Fails CI unless an approved ADR resolves it" is not machine-checkable as written

**Issue.** §16 requires duplicate capability responsibility to fail CI *unless*
an ADR resolves the conflict. CI cannot evaluate a prose ADR.

**Impact.** Either the waiver path is unimplementable (and the rule becomes
all-or-nothing, so engineers work around it by wording `responsibility` fields
evasively), or it is implemented as an unchecked comment — a permanent hole in
the single mechanism protecting against capability duplication.

**Recommended resolution.** Make the waiver machine-readable. A manifest
claiming an exception declares:

```yaml
responsibility_overlap:
  conflicts_with: [capability_id_a, capability_id_b]
  waiver_adr: ADR-0042
```

The validator (`INV-06`) then requires: the ADR file exists; its `Status` is
`Accepted`; its front-matter `waives_overlap` field lists **both** capability
ids; and the conflicting manifests reference the same ADR. Any missing link
fails the build. The ADR remains the human artifact; the link is mechanical.

### NC-3 — "Tenant isolation must be machine-tested" cannot be fully satisfied in Phase 0

**Issue.** §5 requires tenant isolation to be machine-tested across twelve
domains including persistence, memory, files, and device sync. §21 forbids
implementing persistence, memory, files, and device sync in Phase 0. You cannot
data-test isolation for subsystems that do not exist.

**Impact.** Left unaddressed, Phase 0 either overreaches into product
implementation (violating §21) or ships claiming an isolation guarantee it has
not demonstrated (violating §8's honesty requirement and §38.14).

**Recommended resolution.** Split the requirement across phases explicitly and
state precisely what each phase proves:

- **Phase 0 (static, achievable now):** `TenantId` exists as a kernel type;
  every persistence/memory/content contract signature in L0 carries a tenant
  parameter — verified by `ARCH-09`, which parses the contract definitions and
  fails on any tenant-free data-access signature; the isolation test *harness*
  and its fixture skeleton exist and run (with zero implementations registered,
  it trivially passes, and it fails loudly the moment an implementation is
  registered without an isolation case).
- **Phase 1 onward (behavioral):** every registered repository implementation
  must have a passing cross-tenant negative test, including the founder/internal
  principal case, before it can be registered. This is a Phase 1 gate, recorded
  now as a Phase 1 acceptance criterion so it cannot be quietly skipped.

Phase 0 therefore claims exactly this: *no data-access contract can be written
without a tenant boundary.* Nothing more.

### NC-4 — "No PostgreSQL-specific behavior" would weaken the security properties it is meant to protect

**Issue.** §4 correctly separates infrastructure from architecture. But several
PostgreSQL features are the *safest available implementations* of requirements
this baseline mandates: row-level security as defence-in-depth for tenant
isolation, transactional outbox and `SELECT … FOR UPDATE SKIP LOCKED` for
durable execution, advisory locks for idempotency, and `pgcrypto` for envelope
encryption. A blanket prohibition pushes toward hand-rolled equivalents that are
weaker and less reviewed.

**Impact.** The rule as stated could reduce security and reliability while
appearing to increase portability — portability that, for a SaaS platform with
no stated multi-database requirement, has low real value.

**Recommended resolution.** Scope the prohibition precisely, which I read as its
intent: **business logic** (L1, L3–L7) must not depend on PostgreSQL semantics —
Class A, enforced by `ARCH-07` (no SQL, no driver import, no dialect-specific
type outside `platform/persistence/adapters/`). **Infrastructure adapters inside
`platform/persistence` and `platform/execution` may use PostgreSQL-specific
features**, each recorded in a single running ADR (`ADR-0006: Approved
PostgreSQL feature usage`) listing the feature, why it was chosen, and the
portable fallback if the database is ever replaced. This preserves "the database
is infrastructure, not architecture" while not forbidding the infrastructure from
doing its job well. **Requires owner ratification of ADR-0006's standing form**;
listed in §C as a non-blocking ratification.

### NC-5 — Removing the external-integration exemplar leaves neutrality unproven until Phase 7

**Issue.** N.8's correction is right and I have applied it fully. But my previous
proposal used a concrete external system as the proof that the Integration
Gateway's neutrality was real rather than theoretical. That proof is now absent,
and §7's two-provider requirement covers only the *Model* Gateway, not the
*Integration* Gateway.

**Impact.** The Integration Gateway could reach Phase 7 with a single adapter,
at which point its abstraction will have been shaped by exactly one vendor —
the standard way a "neutral" interface turns out to be a vendor's API with the
names changed.

**Recommended resolution.** Mirror the two-provider rule at the integration
layer, without naming anyone now: **the Integration Gateway's contract may not
be declared stable until at least two adapters in materially different
categories (e.g. two of: communication, calendar, source control, storage,
project management) pass the shared conformance suite.** Vendor selection stays
deferred to Phase 7. Recorded as a Phase 7 acceptance criterion in §N.

### NC-6 — Tenant-visible denial explanations can leak policy internals

**Issue.** §19 requires Runtime Decision Records to explain, to the user, *why a
capability was denied*. Detailed denial reasons are a known information-
disclosure vector: they can confirm that a resource exists in another tenant,
reveal the exact policy predicate to probe against, or expose entitlement
structure useful for bypass.

**Impact.** A transparency feature becomes an authorization-oracle.

**Recommended resolution.** Two-layer denial records. The **audit record**
(restricted) captures the full policy evaluation: rule id, predicate, principal
scopes, resource. The **runtime decision record** (tenant-visible) carries an
abstract reason code from a closed vocabulary — `NOT_ENTITLED`,
`INSUFFICIENT_PERMISSION`, `APPROVAL_REQUIRED`, `BUDGET_EXCEEDED`,
`TRUST_TIER_BLOCKED`, `NOT_FOUND_OR_NOT_PERMITTED` — plus a remediation hint.
Critically, "resource does not exist" and "resource exists but is not yours"
must both map to `NOT_FOUND_OR_NOT_PERMITTED`. Enforced by `INV-11`: the
tenant-visible reason field is a closed enum in the schema, so free text cannot
be emitted.

### NC-7 — Device trust and tenant isolation are orthogonal and must not be conflated

**Issue.** §5 lists "device synchronization" as a tenant-bounded domain. But a
device belongs to a *person*, and one person may legitimately act in a personal
account and two organizations from the same laptop. If a device is modeled as
tenant-scoped, cross-tenant continuity breaks; if it is modeled as
account-scoped with ambient access, tenant isolation breaks.

**Impact.** Getting this wrong means either a broken multi-org experience or an
isolation hole in exactly the subsystem (§5) singles out.

**Recommended resolution.** Two separate records, both required:

- `DeviceTrust` — **account-scoped.** Establishes that this hardware is a
  trusted endpoint for this human: device keypair, name, registration time,
  last seen, revocation state.
- `DeviceWorkspaceGrant` — **tenant-scoped.** Establishes that this trusted
  device may sync a *specific* workspace's state, granted and revocable by that
  tenant's administrator independently of the account owner.

Sync is authorized only when both exist and neither is revoked. An org admin can
therefore cut a device off from org data without touching the user's personal
account, and a user can revoke their own lost laptop everywhere at once.
Recorded as ADR-0009.

---

## C. Remaining Owner Decisions

Two items. One blocks Phase 0; one does not.

### C.1 — BLOCKING: Sentinel repository provisioning

Decision N.1 is settled in principle — Sentinel gets its own repository. What
remains is the provisioning act, and Phase 0 Step 0 cannot execute without it.
Three concrete inputs are needed:

1. **Repository owner and name.** Recommendation: `<owner>/sentinel-platform`
   (`sentinel` alone is heavily used and will collide in search and tooling;
   the suffix also leaves room for future `sentinel-clients`, `sentinel-docs`).
2. **Visibility.** Recommendation: **private.** Per N.7 Sentinel is proprietary
   commercial software; a public repository would conflict with that and cannot
   be undone retroactively — the history remains mirrored.
3. **Authorization and access.** I cannot create the repository unilaterally
   (creating repositories is an outward-facing action requiring your explicit
   go-ahead), and the current session's GitHub scope covers only the unrelated
   `aider` repository. Either create it yourself and add it to this session's
   scope, or tell me to create it with the name and visibility above.

Until this exists, no Phase 0 artifact can be committed to its correct home.

### C.2 — NON-BLOCKING: Ratify the standing form of ADR-0006 (PostgreSQL feature usage)

Per **NC-4**, I recommend that PostgreSQL-specific features be permitted *inside
the persistence and execution infrastructure adapters only*, catalogued in a
single running ADR with a portable-fallback note per feature. This can be
ratified when Phase 1 begins; Phase 0 is unaffected. Flagged now because it is a
qualification on your N.2 ruling and should not be adopted silently.

**No other decisions are required.** Toolchain specifics (package manager, type
checker, formatter, test runner, CI provider) are engineering choices within the
approved Python direction and will be recorded as ADRs rather than escalated.

---

## D. Final Layer Model

### D.1 Layers and permitted dependency direction

Dependencies flow **downward only**. There are exactly two exceptions, both
explicit and both machine-enforced.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ L9  CLIENTS            desktop · web · mobile · device surfaces             │
│                        presentation only — zero business logic              │
├─────────────────────────────────────────────────────────────────────────────┤
│ L8  INTERFACES         transport · serialization · authn middleware ·       │
│                        streaming · webhooks · rate limiting                 │
├─────────────────────────────────────────────────────────────────────────────┤
│ L7  INTEGRATIONS       integration gateway  │  external provider adapters   │
│                        (vendor names permitted ONLY in adapters)            │
├─────────────────────────────────────────────────────────────────────────────┤
│ L6  CAPABILITIES       one package per declared responsibility              │
│                        no sideways imports between capabilities             │
├─────────────────────────────────────────────────────────────────────────────┤
│ L5  AGENTS             adaptive agent runtime · sub-agent attenuation       │
├─────────────────────────────────────────────────────────────────────────────┤
│ L4  CORE               request lifecycle · intent · planning · dispatch     │
│                        (policy enforcement point) · approval gate · state   │
├─────────────────────────────────────────────────────────────────────────────┤
│ L3  INTELLIGENCE       model gateway │ model provider adapters │            │
│                        orchestration │ memory                               │
├─────────────────────────────────────────────────────────────────────────────┤
│ L2  PLATFORM           config · identity · authn · authz(PDP) · tenancy ·   │
│                        entitlements · secrets · audit · telemetry ·         │
│                        persistence · execution · registry                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ L1  KERNEL             ids · TenantId · errors · result · clock ·           │
│                        trust tiers · side-effect classes · assertion        │
│                        labels · redaction types                             │
│                        zero Sentinel app-layer deps; approved runtime only  │
├─────────────────────────────────────────────────────────────────────────────┤
│ L0  CONTRACTS          JSON Schema · OpenAPI · capability manifests ·       │
│                        event schemas · scope vocabulary · interface defs    │
│                        language-neutral; NO executable code                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ▲
        ┌───────────────────────────┴───────────────────────────┐
        │  COMPOSITION ROOT  (sentinel/composition/)            │
        │  The ONLY module permitted to import across layers.   │
        │  Wires implementations into the registry at startup.  │
        │  Contains no logic beyond construction and binding.   │
        │  Allowlisted by name in the dependency checker.       │
        └───────────────────────────────────────────────────────┘
```

### D.2 The two permitted exceptions

**Exception 1 — the composition root.** `sentinel/composition/` may import from
any layer. It exists solely to construct implementations and bind them into the
registry. It is allowlisted by exact path in `tools/check_dependencies.py`, and
`ARCH-08` fails the build if it contains conditional logic, business rules, or
more than construction/binding statements.

**Exception 2 — runtime resolution via contracts.** Core (L4) must *invoke*
capabilities (L6) — an upward call. This is not an upward *import*. Core imports
the L0 contract, calls `registry.resolve(capability_id, version)`, and receives
an object satisfying that contract. **Core has zero compile-time knowledge of
any capability, agent, integration, or provider.** The same inversion governs
L4→L5, L6→L7, and L3-gateway→L3-providers.

This is the load-bearing detail of the whole design: it is what makes D1's
"strict module boundaries" mechanically true rather than aspirational.

### D.3 Enforcement mapping

| Rule | Check | Class |
|---|---|---|
| Downward-only imports | `ARCH-01` | A |
| No dependency cycles | `ARCH-02` | A |
| Core imports no capability/agent/integration/provider | `ARCH-03` | A |
| No sideways imports among capabilities / adapters / providers | `ARCH-04` | A |
| Kernel boundary (§13 wording) | `ARCH-05` | A |
| Vendor names confined to adapters | `ARCH-06` | A |
| No SQL/driver/dialect outside persistence adapters | `ARCH-07` | A |
| Composition root is construction-only | `ARCH-08` | A |
| Every data-access contract carries a tenant parameter | `ARCH-09` | A |
| Contracts contain no executable code | `ARCH-10` | A |
| No agent-count constants outside entitlement seed | `ARCH-11` | A |
| No domain/industry vocabulary in L0–L5 | `ARCH-12` | B |

### D.4 Repository tree (Sentinel repository, standalone)

```
sentinel-platform/
├─ contracts/                        # L0 — language-neutral, no executable code
│  ├─ capability/
│  │  ├─ capability.schema.json      # the manifest schema (§F)
│  │  └─ manifests/                  # one .yaml per capability
│  ├─ events/                        # audit · runtime-decision · telemetry schemas
│  ├─ api/                           # OpenAPI: client ↔ platform
│  ├─ policy/scopes.yaml             # permission vocabulary + role templates
│  └─ interfaces/                    # abstract interface definitions per subsystem
│
├─ src/sentinel/
│  ├─ kernel/                        # L1
│  ├─ platform/                      # L2
│  │  ├─ config/ identity/ authn/ authz/ tenancy/ entitlements/ secrets/
│  │  ├─ audit/ telemetry/ registry/
│  │  ├─ persistence/                #   contracts + adapters/ (PG-specific here only)
│  │  └─ execution/                  #   durable steps, idempotency, retries
│  ├─ intelligence/                  # L3 — gateway/ providers/ orchestration/ memory/
│  ├─ core/                          # L4
│  ├─ agents/                        # L5
│  ├─ capabilities/                  # L6
│  ├─ integrations/                  # L7 — gateway/ adapters/
│  ├─ interfaces/                    # L8
│  └─ composition/                   # wiring boundary — allowlisted
│
├─ clients/                          # L9 — empty until Phase 9; own toolchains
│
├─ tests/
│  ├─ architecture/                  # ARCH-01..12 — blocking, first-class
│  ├─ unit/ contract/ policy/ integration/ adversarial/
│
├─ tools/
│  ├─ check_dependencies.py  validate_manifests.py  check_licences.py
│  ├─ check_dependency_register.py   generate_arch_map.py  check_rule_classes.py
│
├─ docs/
│  ├─ architecture/                  # layer map · request lifecycle · map.json
│  ├─ adr/                           # ADR-TEMPLATE.md · NNNN-*.md
│  ├─ standards/                     # coding · docs · testing · security · dev-setup
│  ├─ security/                      # threat model · trust model · abuse cases
│  ├─ dependencies/                  # REGISTER.md + approved.yaml (§H)
│  └─ capabilities/                  # generated capability catalogue
│
├─ .github/workflows/ci.yml
├─ CONTRIBUTING.md  LICENSE  NOTICE  SECURITY.md  README.md
```

---

## E. Final Module Ownership Table

Every module owns exactly one concept. No concept has two owners.
`Tenant-scoped` marks modules that must carry a tenant boundary per N.3.

| Module | Responsibility (single) | May depend on | Must never depend on | Tenant-scoped |
|---|---|---|---|---|
| `contracts/` | The authoritative, language-neutral definition of every interface, schema, and vocabulary | nothing | everything (it is a leaf) | n/a |
| `kernel/` | Primitive types shared by all layers: ids, `TenantId`, errors, result, clock, trust tiers, side-effect classes, assertion labels, redaction types | approved runtime/stdlib facilities only (allowlist, initially empty) | any Sentinel layer L2–L9; any third-party package not on the kernel allowlist | no (defines the type) |
| `platform/config` | Resolved, validated configuration values | kernel | any L3+ module; secrets material | no |
| `platform/identity` | Who exists: accounts, users, devices, agents-as-principals | kernel, contracts | authz, entitlements, licensing, any L3+ | yes |
| `platform/authn` | Proving identity: sessions, tokens, epochs, device credentials, pairing | kernel, identity, secrets | authz (it grants nothing), capabilities | yes |
| `platform/authz` | **The PDP.** All authorization decisions, as a pure function | kernel, contracts/policy | identity stores, entitlements storage, persistence, any L3+ | yes |
| `platform/tenancy` | Tenant/organization/workspace resolution and boundary enforcement | kernel, identity | capabilities, agents, any L3+ | yes (defines it) |
| `platform/entitlements` | Licensing state → capability and quota grants | kernel, contracts | authz internals, business logic of any capability | yes |
| `platform/secrets` | Secret storage, envelope encryption, per-tenant key derivation, materialization | kernel | audit, telemetry, any L3+ | yes |
| `platform/audit` | Tamper-evident record of consequential actions | kernel, contracts/events | telemetry (never), capabilities | yes |
| `platform/telemetry` | Operational logs, metrics, traces, correlation propagation | kernel, contracts/events | audit (never), secrets material | yes (label only) |
| `platform/persistence` | Durable storage access behind repository contracts | kernel, contracts, tenancy | any L3+ module; business rules | yes |
| `platform/execution` | Durable step execution: idempotency, retries, backoff, resumption | kernel, persistence, telemetry | planning, capability semantics, model gateway | yes |
| `platform/registry` | Loading, validating, indexing capability manifests; runtime resolution | kernel, contracts | the capabilities it indexes | no |
| `intelligence/gateway` | Provider selection, routing, health, fallback, budget enforcement, cost attribution | kernel, platform/*, `intelligence/providers` **contracts** | provider adapter implementations (resolved at runtime); prompt content; business logic | yes |
| `intelligence/providers/*` | One model vendor's protocol translation | kernel, gateway contracts | each other; core; capabilities; business logic | no |
| `intelligence/orchestration` | `PromptContract`, plan and step structures | kernel, contracts | executing steps; choosing providers | yes |
| `intelligence/memory` | Scoped memory records: write, retrieve, retain, delete, provenance | kernel, platform/persistence, tenancy | knowledge extraction; capabilities; core | yes |
| `core/` | Request lifecycle, intent resolution, plan construction, dispatch (PEP), approval gating, turn state | kernel, contracts, platform/*, intelligence/* | `capabilities/`, `agents/`, `integrations/`, `intelligence/providers/*` — all resolved at runtime | yes |
| `agents/` | Agent configuration, lifecycle, sub-agent authority attenuation | kernel, contracts, platform/*, intelligence/* | any specific capability; any domain vocabulary | yes |
| `capabilities/*` | Exactly one declared `responsibility` from the registry | kernel, contracts, platform/*, intelligence/*, integrations **contracts** | any other capability; core; agents; adapter implementations | yes |
| `integrations/gateway` | Capability-contract → adapter dispatch, health, conformance enforcement | kernel, contracts, platform/* | adapter implementations (runtime-resolved); capabilities | yes |
| `integrations/adapters/*` | One external vendor's protocol translation | kernel, gateway contracts | each other; core; capabilities; business decisions | no |
| `interfaces/` | Transport, serialization, authn middleware, streaming, rate limiting | kernel, contracts, platform/*, core | capabilities; agents; adapters; business logic of any kind | yes |
| `composition/` | Construction and binding of implementations into the registry | everything (sole exception) | nothing conditional — no logic beyond wiring | n/a |
| `clients/` | Presentation | published contracts only (`contracts/api`) | every `src/sentinel/` module; all business logic | yes |

---

## F. Final Capability Registry Schema

The registry is the authoritative mechanism for capability ownership (§16). A
capability that is not in the registry does not exist; one that is cannot
duplicate another's responsibility.

### F.1 Manifest fields

Location: `contracts/capability/manifests/<id>.yaml`.

| Field | Req | Type | Purpose |
|---|:--:|---|---|
| `id` | ✔ | `snake_case` | Globally unique, stable, **never reused** |
| `version` | ✔ | semver | Version of the *contract*, not the implementation |
| `name` | ✔ | string | Human label |
| `purpose` | ✔ | string (1 sentence) | What it is for |
| `responsibility` | ✔ | string | **Unique across the registry.** The anti-duplication key |
| `responsibility_overlap` | — | object | Waiver: `{conflicts_with: [...], waiver_adr: ADR-NNNN}` (NC-2) |
| `owner` | ✔ | string | Accountable module path + person/role |
| `interface` | ✔ | path | The L0 contract it satisfies |
| `actions[]` | ✔ | list | Per action: `name`, `inputs`, `outputs`, `side_effect_class`, `required_scopes`, `idempotent`, `max_permission_level` |
| `required_scopes[]` | ✔ | list | Union of scopes it may ever request — the attenuation ceiling |
| `max_permission_level` | ✔ | 0–4 | Registry-enforced autonomy ceiling |
| `accepted_trust_tiers[]` | ✔ | T0–T3 | Which input trust tiers it will process |
| `emits_trust_tier` | ✔ | T0–T3 | Trust tier of its *output* — propagates provenance |
| `data_classification` | ✔ | enum | Highest classification it may touch |
| `tenant_scoped` | ✔ | bool | Whether it touches tenant data (almost always true) |
| `dependencies[]` | ✔ | list | Other capability ids + platform services. Must form a DAG |
| `failure_behavior` | ✔ | object | `mode: fail_closed\|fail_open\|degrade`, timeout, retry policy, circuit breaker |
| `audit_events[]` | ✔ | list | Event types emitted; validated against the audit schema |
| `budget_class` | ✔ | enum | Expected cost/latency profile, for routing and quotas |
| `availability` | ✔ | enum | `planned\|experimental\|beta\|stable\|deprecated` |
| `entitlement_key` | ✔ | string\|null | Which entitlement gates it (`null` = always available) |
| `replacement_path` | ✔ | string | How to swap the implementation; successor id if deprecated |
| `tests` | ✔ | path | Its contract test suite; must exist and be non-empty |

### F.2 Validation invariants (all Class A, all CI-blocking)

| ID | Invariant |
|---|---|
| `INV-01` | Manifest validates against `capability.schema.json` |
| `INV-02` | `id` is unique and has never been used by a different capability (checked against a retired-id ledger) |
| `INV-03` | `responsibility` is unique after normalization (lowercase, stopword-stripped, lemmatized) |
| `INV-04` | Normalized-token overlap with any existing `responsibility` above threshold fails **unless** a valid `responsibility_overlap` waiver is present |
| `INV-05` | `dependencies` all resolve to existing ids and form a DAG (no cycles) |
| `INV-06` | A `responsibility_overlap` waiver resolves to an existing ADR whose `Status: Accepted` and whose `waives_overlap` front-matter lists **every** id in `conflicts_with`, reciprocally |
| `INV-07` | Every scope in `required_scopes` and in each action exists in `contracts/policy/scopes.yaml` |
| `INV-08` | Each action's `required_scopes` ⊆ the capability's `required_scopes` |
| `INV-09` | `side_effect_class` ∈ {`FINANCIAL`, `PROVISIONING`, `DESTRUCTIVE`, `EXECUTE_IRREVERSIBLE`, `PERMISSION_CHANGE`, `CREDENTIAL_CHANGE`, `SECURITY_POLICY_CHANGE`} ⟹ `max_permission_level ≤ 3` (D4) |
| `INV-10` | Each action's `max_permission_level` ≤ the capability's `max_permission_level` |
| `INV-11` | Every `audit_events` entry validates against the audit event schema; any tenant-visible reason field uses the closed reason-code enum (NC-6) |
| `INV-12` | `tests` path exists and contains at least one test |
| `INV-13` | Every implementation package under `capabilities/` has a manifest, and every manifest with `availability ≠ planned` has an implementation |
| `INV-14` | `interface` resolves to an existing L0 contract |
| `INV-15` | `accepted_trust_tiers` includes T3 ⟹ the capability declares an adversarial test suite (G, `AUTH-06`) |
| `INV-16` | `tenant_scoped: true` ⟹ every action signature in the referenced interface carries a tenant parameter (links to `ARCH-09`) |

### F.3 The anti-duplication gate in practice

Before adding functionality:
`tools/validate_manifests.py --search "<responsibility phrase>"` reports
overlapping existing responsibilities. A PR that introduces an overlap fails CI
naming the conflicting id, forcing an explicit choice: extend the existing
capability, or write the waiver ADR. **This is the primary defence against the
feature sprawl and duplication that the blueprint prohibits**, and per NC-2 its
exception path is now machine-verifiable rather than honour-system.

---

## G. Final Trust & Authority Model

**Constitution status:** foundational (§38.24). This section is normative.

### G.1 Trust tiers

| Tier | Definition | Examples | May instruct? | May authorize? |
|---|---|---|:--:|:--:|
| **T0 Platform** | Trusted Sentinel code, approved configuration, system policy | system prompts, policy rules, capability manifests | Yes | Yes (as policy) |
| **T1 Principal** | Authenticated user instructions within granted authority | the user's message this turn, an explicit approval response | Yes, bounded by the principal's own scopes | Yes, up to the principal's scopes |
| **T2 Tenant Content** | Workspace documents, stored memory, prior content, internal knowledge | notes, memory records, previous turns, uploaded internal docs | **Informational only** | **Never** |
| **T3 External Content** | Anything originating outside the tenant | web pages, inbound email/chat, third-party payloads, OCR output, uploaded external documents, external metadata, integration responses | **Informational only** | **Never** |

### G.2 The Authority Rule

> **Authority never flows upward from T2 or T3.**
> Retrieved content is information. It is not authorization.
> Authority originates only from an authenticated principal (T1) evaluated
> against explicit platform policy (T0).

Untrusted content **cannot**: grant scopes · expand tool or capability access ·
change permissions · override platform policy · modify security boundaries ·
authorize consequential actions · circumvent approval requirements.

### G.3 Machine-enforced invariants

| ID | Invariant | Enforcement | Class |
|---|---|---|:--:|
| `AUTH-01` | **Capability set is frozen before untrusted content is read.** The set of capabilities and scopes available to a turn is computed from principal + policy + entitlements and sealed *before* any T2/T3 content enters the context. A post-seal mutation attempt raises a security error and is audited. | Runtime assertion on the sealed set + unit tests on the dispatcher | A |
| `AUTH-02` | **Provenance is tracked per plan step.** Each step records the trust tiers of every input that contributed to it. Tier propagates: an output derived from T3 input is at best T3 (see `emits_trust_tier`). | Type-level tagging in `kernel/trust.py`; step schema requires `provenance_tiers` | A |
| `AUTH-03` | **T2/T3 provenance + side effect ≥ EXECUTE_* ⟹ explicit human approval,** regardless of configured permission level. This is a hard override that user configuration cannot disable. | Dispatcher check + policy golden tests | A |
| `AUTH-04` | **Untrusted content is never placed in instruction position.** All T2/T3 content is delimited, labelled with its tier and source, and passed as data. | Enforced in the prompt-assembly type: raw string concatenation into instruction slots is not expressible in the API | A |
| `AUTH-05` | **No scope may be introduced by content.** Scope sets are constructed only from principal, policy, and entitlements — never parsed from text, tool output, or model output. | `ARCH`-level check: no scope construction outside `platform/authz`; runtime assertion | A |
| `AUTH-06` | **Every T3-accepting capability ships an adversarial suite.** Registry `INV-15` refuses registration otherwise. | `validate_manifests.py` + the adversarial corpus run | A |

### G.4 Side-effect classes and the autonomy ladder (D4 final)

`READ` · `ANALYZE` · `DRAFT` · `EXECUTE_REVERSIBLE` · `EXECUTE_IRREVERSIBLE` ·
`DESTRUCTIVE` · `FINANCIAL` · `PROVISIONING` · `PERMISSION_CHANGE` ·
`CREDENTIAL_CHANGE` · `SECURITY_POLICY_CHANGE`

| Class | Max autonomous level | Required confirmation |
|---|:--:|---|
| READ, ANALYZE | 4 | none |
| DRAFT | 4 | none (nothing leaves the system) |
| EXECUTE_REVERSIBLE | 4 | pre-declared bounded rule **and** announcement (never silent) |
| EXECUTE_IRREVERSIBLE | 3 | explicit approval |
| FINANCIAL, PROVISIONING | 3 | explicit approval + value/scope ceiling |
| DESTRUCTIVE | 3 | explicit approval + typed confirmation + cooling-off |
| PERMISSION_CHANGE, CREDENTIAL_CHANGE, SECURITY_POLICY_CHANGE | 3 | explicit approval + re-authentication |

Level 4 means **unattended, never invisible**: every L4 action is announced and
audited with the id of the rule that triggered it.

### G.5 Principals and attenuation

Agents, sub-agents, and capability invocations are **first-class principals
acting on behalf of** a user, never *as* the user. Each execution receives an
attenuated capability token:

```
scopes = user_scopes ∩ capability_required_scopes ∩ entitlement_grants ∩ task_scope
```

bound to one tenant, one correlation id, a task-length TTL, non-refreshable, and
re-validated against the parent session epoch at every invocation. **Attenuation
is monotonic** — a sub-agent can never hold a scope its parent lacked, at any
nesting depth. Verified by a property test (`policy/test_attenuation.py`).

### G.6 Financial safety boundary (§15, preserved)

Default posture for financial integrations: minimum necessary access · read-only
where practical · explicit authorization to widen · immediate revocability.
No banking, brokerage, tax, payment, or other financial credential is held in
application storage; integration tokens live in `platform/secrets` and are
materialized short-lived at call time. Financial external systems remain
external systems — Sentinel coordinates them, never assumes ownership of them.

---

## H. Final Clean-Room & Dependency Policy

### H.1 Clean-room principle

Sentinel is an original clean-room implementation. Inspiration may come from
public concepts, research, documentation, open-source projects, product
patterns, and industry practice. **Inspiration does not authorize copying.**

Prohibited without exception:
- Copying code from an inspiration source into Sentinel unless that code enters
  as an approved third-party dependency under H.2.
- Asking an AI coding system to reproduce another project's source code.
- Imitating distinctive proprietary implementation details to obtain equivalent
  functionality.

Required: build equivalent capabilities from Sentinel's own requirements and
contracts. Where a third-party component is incorporated, preserve required
notices and attribution in `NOTICE`.

### H.2 Third-party dependency register

Every intentionally incorporated package is recorded in
`docs/dependencies/REGISTER.md` (human) and `docs/dependencies/approved.yaml`
(machine), with ten fields:

`name` · `exact_version` · `source` (canonical URL + resolved artifact hash) ·
`license` · `purpose` · `why_needed` (including what was considered instead) ·
`approval_status` + `approving_adr` · `commercial_compatibility` (with
attribution / modification / distribution obligations stated explicitly) ·
`security_history` (known CVEs, disclosure responsiveness, maintenance health) ·
`replacement_strategy` (difficulty, candidate alternatives, estimated effort).

### H.3 Licence policy (N.7 — proprietary commercial)

| Category | Licences | Status |
|---|---|---|
| Permitted | MIT, BSD-2/3, Apache-2.0, ISC, PSF, Unlicense, CC0 | Allowed with register entry |
| Denied by default | LGPL, MPL, EPL | Requires ADR + explicit legal note |
| Denied | GPL, AGPL, SSPL, BSL, Elastic, "source-available", non-commercial, unlicensed | Not permitted |

Apache-2.0 attribution and NOTICE obligations are satisfied in the repository
`NOTICE` file. **No compliance or certification status may be claimed anywhere
in the product, documentation, or marketing that Sentinel has not achieved**
(N.6).

### H.4 Enforcement

| Control | Mechanism | Class |
|---|---|:--:|
| Every lockfile entry appears in `approved.yaml` with a matching version | `tools/check_dependency_register.py`, CI-blocking | A |
| Licence of every resolved dependency ∈ permitted set | `tools/check_licences.py` | A |
| Lockfile is pinned and hash-locked | CI verifies the lock is current and hashed | A |
| SBOM generated per build and retained | CI artifact | A |
| Dependency vulnerability scan | CI, blocking on high/critical | A |
| Secret scanning on every commit | CI, blocking | A |
| Kernel dependency allowlist (starts empty; ADR to extend) | `ARCH-05` | A |
| New dependency has a register entry + written justification in the PR | PR template + `check_dependency_register.py` | A |
| No copied third-party code; no reproduction prompts | Authorship attestation, H.5 | **C** |

### H.5 AI-authorship control (N.9)

AI-generated code receives no relaxed standard. Two additional controls, both
Class C with a named reviewer, because they are not automatable:

1. **Explainability requirement.** Any contributed block the author cannot
   explain purely from Sentinel's own contracts and requirements must be
   rewritten. "It works and I got it from somewhere" is a rejection.
2. **PR attestation checklist.** Each PR affirms: no code was copied from an
   inspiration source; no reproduction of another project's implementation was
   requested; every new dependency is registered; every new rule carries an
   enforcement class.

These are documented in `CONTRIBUTING.md` with the reason automation is
impractical and a revisit date, per NC-1.

---

## I. Final Testing & Architecture-Erosion Strategy

### I.1 Test levels

| Level | Prevents | Scope | Gate |
|---|---|---|---|
| **Unit** | Logic errors | one module, no I/O | 80% line coverage overall |
| **Contract** | Interface drift | one L0 contract, both sides | every contract has one |
| **Policy** | Permission leakage | PDP, entitlements, attenuation, isolation | **95% coverage, mandatory** |
| **Integration** | Wiring errors | multiple modules + fakes | per subsystem |
| **Adversarial** | Injection, confused deputy, authority escalation | full dispatch path | corpus must pass, **blocking** |
| **Architecture** | Structural erosion | static analysis of the tree | **blocking** (§I.3) |
| **Conformance** | Adapter divergence | one adapter vs the neutral contract | required before registration |
| **E2E smoke** | Total breakage | deployed stack | pre-release |

### I.2 Rule Enforcement Classification (resolves NC-1)

Every normative rule in Sentinel carries Class **A** (machine-enforced,
blocking), **B** (machine-detected, triaged), or **C** (manual gate with named
reviewer, checklist item, documented reason, and revisit date). **No rule may be
unclassified.** A rule that can be Class A must be Class A; downgrading requires
an ADR. `tools/check_rule_classes.py` verifies that every rule listed in the
standards documents has a class and, for Class C, all four required attributes.

### I.3 Architecture erosion tests (`tests/architecture/`, all blocking)

`ARCH-01` dependency direction · `ARCH-02` no cycles · `ARCH-03` Core imports no
capability/agent/integration/provider · `ARCH-04` no sideways imports ·
`ARCH-05` kernel boundary · `ARCH-06` vendor-name containment · `ARCH-07` no
SQL/driver/dialect outside persistence adapters · `ARCH-08` composition root is
construction-only · `ARCH-09` every data-access contract carries a tenant
parameter · `ARCH-10` contracts contain no executable code · `ARCH-11` no
agent-count constants outside entitlement seed · `ARCH-12` no domain vocabulary
in L0–L5 (Class B).

Plus registry checks `INV-01`…`INV-16`, architecture-map drift, and
missing/invalid manifests.

**Every architecture check ships with a deliberate-violation fixture proving the
check actually fails.** A gate that has never been observed to fail is not a
gate.

### I.4 Mandatory security suites

1. **Policy golden tables** — exhaustive `(principal, role, scope, resource,
   action) → decision`. Outcome changes must be intentional, reviewed diffs.
2. **Tenant isolation** — Phase 0 delivers the static guarantee and the harness
   (NC-3); Phase 1 onward, every registered repository implementation needs a
   passing cross-tenant negative test **including the founder/internal principal
   case** before registration.
3. **Attenuation monotonicity** — property test at arbitrary nesting depth.
4. **Revocation** — a revoked principal cannot complete an in-flight multi-step
   execution.
5. **Adversarial corpus** — injection payloads in web content, email bodies,
   document text, image OCR, filenames, and integration payloads, asserting none
   causes a tool invocation, scope grant, permission change, approval bypass, or
   post-seal capability mutation. **The corpus grows with every incident.**

### I.5 Determinism

No network in unit or contract tests — enforced by a socket-blocking fixture,
not convention. Time injected via `kernel/clock`; direct `now()` is a lint
error. Randomness seeded. Model calls use a deterministic fake adapter. **Zero
flaky tests tolerated**: a flake is quarantined and fixed, never re-run until
green.

---

## J. Final Observability & Audit Strategy

### J.1 Four separate concerns, four stores

| Concern | Question | Store | Retention | Integrity | Access |
|---|---|---|---|---|---|
| **Operational logs** | What happened technically? | log backend | days–weeks | none | operators |
| **Metrics** | Is it healthy and fast? | metrics backend | weeks–months | none | operators |
| **Traces** | Where did the time go? | tracing backend | days | none | operators |
| **Audit** | Who did what, with what authority, when, and was it approved? | append-only, hash-chained per tenant | compliance-driven | tamper-evident | restricted, self-auditing |

**Audit is not logging.** It never transits the telemetry pipeline, never shares
a sink, and is not sampled. Telemetry failure cannot erase an audit record:
audit writes go to a durable local append-only journal synchronously, then ship
asynchronously to the audit store.

**Fail-closed audit events:** authorization denial, permission change,
credential change, security-policy change, revocation, emergency lockout,
founder/internal entitlement use, cross-scope memory bridge, financial action,
destructive action, approval grant or bypass attempt, post-seal capability
mutation attempt. If the journal write fails, the action fails. Everything else
is fail-open with a dropped-record metric.

### J.2 Correlation and redaction

A `correlation_id` is minted at the L8 edge, propagated through every layer,
model call, adapter call, and audit record, and returned to the client on
success and error alike. Nested work carries `parent_span_id` and
`root_correlation_id`.

**Redaction is a property of the emitter type, not caller discipline.** Secret
and PII-bearing kernel types are not serializable by the telemetry encoder;
attempting to emit one is a type error, not a runtime hope. Correlation
identifiers let an engineer reconstruct a lifecycle **without** exposing content.

**Acceptance test for observability:** given a correlation id from a
user-visible error, an engineer reconstructs intent → plan → each step → each
policy decision → each provider call → each retry → the failure → the
user-facing message, **without reading application source and without seeing
tenant content.**

### J.3 Runtime Decision Records (§19, distinct from ADRs)

Tenant-visible explanations of Sentinel's runtime choices — why this model, why
this agent recommendation, why a denial, why a fallback, why approval was
required. Stored per-tenant, never co-located with ADRs, never sharing a code
path with audit.

Per **NC-6**, denial explanations use a **closed reason-code vocabulary** —
`NOT_ENTITLED`, `INSUFFICIENT_PERMISSION`, `APPROVAL_REQUIRED`,
`BUDGET_EXCEEDED`, `TRUST_TIER_BLOCKED`, `NOT_FOUND_OR_NOT_PERMITTED` — plus a
remediation hint. Full policy evaluation detail goes to the restricted audit
record only. "Does not exist" and "exists but not yours" are indistinguishable
to the caller.

---

## K. Final ADR System

### K.1 When an ADR is required

Dependency-direction changes · new third-party dependencies · new capabilities ·
capability responsibility-overlap waivers · provider or vendor selection ·
security, permission, or trust-model changes · kernel allowlist additions ·
PostgreSQL feature adoption (ADR-0006) · rule enforcement-class downgrades ·
deviations from this baseline · build-order changes · licensing-model changes.

Not required for: implementation detail inside an established boundary, bug
fixes, refactors that preserve contracts.

### K.2 Mechanics

`docs/adr/NNNN-kebab-title.md`, zero-padded sequential, never renumbered, never
deleted. `Proposed` → `Accepted` | `Rejected`; later `Deprecated` |
`Superseded by ADR-NNNN`, always with a forward link — the record of changing
one's mind is the valuable part.

Machine-readable front matter (so CI can use it, per NC-2):

```yaml
---
id: ADR-0042
status: Accepted          # Proposed | Accepted | Rejected | Deprecated | Superseded
date: 2026-08-15
deciders: [owner]
supersedes: null
superseded_by: null
blueprint_refs: [§33, §38.16]
waives_overlap: []        # capability ids, when this ADR waives INV-04
rule_class_downgrade: []  # rule ids downgraded from A, when applicable
---
```

Body sections: **Context** · **Decision** · **Alternatives Considered** (each
with why not) · **Consequences** (positive / accepted costs / neutral / risks +
mitigations) · **Compliance** (which Constitution items it upholds, and any it
strains, with justification) · **Verification** (the test, CI check, or metric
proving it was implemented) · **Revisit Criteria**.

`Verification` and `Revisit Criteria` go beyond the blueprint's list
deliberately: without the first, ADRs drift from reality; without the second,
decisions outlive their context.

### K.3 Initial ADR set (written in Phase 0)

| ADR | Subject |
|---|---|
| 0000 | Separate Sentinel repository; no unrelated project merged (N.1, N.8) |
| 0001 | Python 3.12+ with strict static typing; language-neutral contracts (N.2) |
| 0002 | Nine-layer model, dependency direction, composition root (D1, §17) |
| 0003 | Trust tiers and the Authority Rule as foundational (D6, §14) |
| 0004 | Capability Registry as the authority for capability ownership (§16) |
| 0005 | Rule Enforcement Classification A/B/C (§2 + NC-1) |
| 0006 | Approved PostgreSQL feature usage in infrastructure adapters (NC-4) — *standing ADR, extended over time* |
| 0007 | Multi-tenant-from-the-start; phased isolation verification (N.3 + NC-3) |
| 0008 | Proprietary licence; permissive-only dependency policy (N.7) |
| 0009 | Device trust vs workspace grant separation (NC-7) |
| 0010 | Clean-room provenance policy and AI-authorship controls (§12, N.9) |

---

## L. Final Phase 0 Acceptance Criteria

Phase 0 is complete when all criteria hold. Each states its verification
mechanism; a criterion without one is not a criterion.

| # | Criterion | Verification mechanism |
|---|---|---|
| **L01** | Sentinel repository exists, is private, is independent, and contains no unrelated project | Inspection; `ARCH` suite runs green in the new repository's CI |
| **L02** | Directory tree per §D.4 exists; every top-level module has a `README.md` declaring its single responsibility, permitted dependencies, and forbidden dependencies | `tests/architecture/test_module_readmes.py` asserts presence and required sections |
| **L03** | Python 3.12+ toolchain configured: formatter, linter, strict type checker, test runner, pinned hash-locked lockfile | CI green with **zero warnings** on the (near-empty) tree |
| **L04** | `tools/check_dependencies.py` implements `ARCH-01`…`ARCH-04`, `ARCH-08` | Deliberate-violation fixtures fail CI (one per check) |
| **L05** | `ARCH-05` kernel boundary enforced; kernel allowlist file exists and is empty | Fixture: a kernel module importing L2 fails; a kernel module importing a non-allowlisted package fails |
| **L06** | `ARCH-06`, `ARCH-07`, `ARCH-09`, `ARCH-10`, `ARCH-11` implemented; `ARCH-12` implemented as Class B | One deliberate-violation fixture per check |
| **L07** | `capability.schema.json` exists, is documented, and self-validates | Schema self-test in CI |
| **L08** | `tools/validate_manifests.py` implements `INV-01`…`INV-16`, including the machine-readable overlap waiver | Invalid-manifest fixture set — at least one per invariant — fails CI |
| **L09** | At least two reference manifests exist with `availability: planned`, plus one deliberate overlap pair proving `INV-04`/`INV-06` | Validator passes on the valid pair, fails on the unwaived overlap, passes on the waived overlap |
| **L10** | `contracts/policy/scopes.yaml` defines the initial scope vocabulary and role templates (declaration only, no PDP) | Schema validation; `INV-07` resolves against it |
| **L11** | L0 contract stubs exist for persistence and durable execution (contracts only, zero implementation) | `ARCH-09`/`ARCH-10` pass; no implementation module exists |
| **L12** | ADRs 0000–0010 written, `Status: Accepted`, front matter schema-valid | `tools/validate_adrs.py` in CI |
| **L13** | Standards documents exist: coding, documentation, testing, security, development setup — every normative rule carries an enforcement class | `tools/check_rule_classes.py` fails on any unclassified rule or incomplete Class C entry |
| **L14** | Threat model exists in `docs/security/`: trust tiers, Authority Rule, confused-deputy scenario, top-10 abuse cases, and the `AUTH-01`…`AUTH-06` invariants with their planned enforcement points | Review against a written checklist (Class C, named reviewer) |
| **L15** | Adversarial corpus harness exists and runs, seeded with at least 20 injection payloads across all six input channels | Harness executes in CI; a canary payload that *should* be caught is caught by the harness's own self-test |
| **L16** | Tenant isolation: `TenantId` kernel type exists; `ARCH-09` passes; the isolation test harness and fixture skeleton run | CI green; fixture proves `ARCH-09` fails on a tenant-free data-access signature |
| **L17** | **No product business logic exists anywhere in the tree** — no Core behavior, no gateway, no agents, no memory, no capabilities, no integrations, no UI, no database behavior | Negative criterion. Verified by review plus `ARCH-13`: no module outside `kernel/`, `platform/registry`, and `tools/` contains executable logic beyond type and contract definitions |
| **L18** | Dependency register (`REGISTER.md` + `approved.yaml`) exists; `check_dependency_register.py` and `check_licences.py` are blocking | Fixtures: an unregistered package fails; a GPL package fails |
| **L19** | SBOM generation, dependency vulnerability scan, and secret scanning active and blocking | Planted test secret is caught; a known-vulnerable pinned fixture fails |
| **L20** | `tools/generate_arch_map.py` emits `docs/architecture/map.json` (modules, layers, dependencies, capabilities, rule classes); CI fails on uncommitted drift | Drift fixture fails CI |
| **L21** | CI pipeline runs, every stage blocking: format → lint → typecheck → architecture → unit → policy → manifests → ADR validation → rule classes → dependency register → licences → vulnerability scan → secret scan → SBOM → arch-map drift | Green on a real PR; each gate has a proven failure fixture |
| **L22** | `CONTRIBUTING.md` documents clean-room policy, dependency approval, ADR requirement, anti-duplication gate, enforcement classes, and the AI-authorship attestation; `SECURITY.md`, `LICENSE`, `NOTICE` present | Review (Class C, named reviewer) |
| **L23** | A person who has not seen the repository clones it, runs one documented setup command, and gets a green build | Performed and recorded |

---

## M. Final Phase 0 Implementation Sequence

Steps with their dependencies. Steps sharing a dependency set may run in
parallel.

| Step | Work | Depends on | Satisfies |
|:--:|---|---|---|
| **0** | **Provision the Sentinel repository** (private, independent). Migrate the baseline docs out of the transitional location; remove them from the unrelated repository. | **§C.1 — owner action** | L01 |
| **1** | ADR-0000 (repository), ADR-0001 (language/contracts), ADR-0008 (licence policy) | 0 | L12 (partial) |
| **2** | Toolchain: formatter, linter, strict type checker, test runner, pinned hash-locked lockfile, minimal CI skeleton | 1 | L03 |
| **3** | Directory skeleton per §D.4 with per-module `README.md` (responsibility / may depend on / must never depend on) | 1 | L02 |
| **4** | ADR-0002 (layers), ADR-0005 (enforcement classes), ADR-0003 (trust & authority) | 3 | L12 |
| **5** | Standards documents, every rule carrying an enforcement class; `tools/check_rule_classes.py` | 2, 4 | L13 |
| **6** | `tools/check_dependencies.py` + `ARCH-01`…`ARCH-08` + one violation fixture each | 3, 4 | L04, L05, L06 (partial) |
| **7** | `kernel/` type-only skeleton: ids, `TenantId`, errors, result, clock, trust tiers, side-effect classes, assertion labels, redaction types. **Types and contracts only — no behavior.** | 6 | L05, L16 (partial), L17 |
| **8** | `capability.schema.json` + registry design doc + ADR-0004 | 4 | L07, L12 |
| **9** | `tools/validate_manifests.py` (`INV-01`…`INV-16`) + invalid-manifest fixture set + reference manifests incl. the overlap pair | 8 | L08, L09 |
| **10** | `contracts/policy/scopes.yaml`; L0 contract stubs for persistence and durable execution; `ARCH-09`, `ARCH-10` | 7, 8 | L10, L11, L06 |
| **11** | ADR-0007 (tenancy), ADR-0009 (device trust); tenant isolation harness + fixture skeleton | 7, 10 | L16 |
| **12** | Threat model document; adversarial corpus harness + ≥20 seeded payloads; `AUTH` invariant enforcement points documented | 4, 7 | L14, L15 |
| **13** | ADR-0010 (clean-room); dependency register + `approved.yaml`; `check_dependency_register.py`; `check_licences.py`; `validate_adrs.py` | 2, 5 | L12, L18 |
| **14** | SBOM, vulnerability scan, secret scanning, with fixtures | 13 | L19 |
| **15** | `ARCH-11`, `ARCH-12`, `ARCH-13`; `generate_arch_map.py` + committed `map.json` + drift check | 6, 9 | L06, L17, L20 |
| **16** | Full CI assembly: all stages blocking, each with a proven failure fixture | 6, 9, 13, 14, 15 | L21 |
| **17** | `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE`, `NOTICE`; ADR-0006 standing form drafted for Phase 1 ratification | 5, 13 | L22, C.2 |
| **18** | Clean-clone verification by a fresh party; final review against every criterion in §L | all | L23 |

**Critical path:** 0 → 1 → 2 → 3 → 6 → 7 → 10 → 11/12 → 16 → 18.
Steps 8–9 (registry) and 13–14 (supply chain) run parallel to 10–12.

**Total product functionality delivered by Phase 0: none.** That is criterion
L17 and it is intentional.

---

## N. Explicitly Deferred Work

### N.1 Deferred to a named later phase

| Deferred | Phase | Acceptance criterion recorded now |
|---|:--:|---|
| Persistence implementation + migrations | 1 | Every registered repository has a passing cross-tenant negative test incl. the founder principal (NC-3) |
| Durable execution engine | 1 | Idempotency property tests; resumption-after-restart test |
| PDP implementation | 1 | Policy golden tables at 95% coverage |
| Identity, authn, tenancy, entitlements, audit, telemetry | 1 | Revocation invalidates in-flight executions |
| Model Gateway + orchestration | 2 | Demonstrates provider switching, capability discovery, fallback, provider-feature isolation, failure handling, model/version identification, cost attribution — across **two materially different providers** (N.5) |
| Memory | 3 | Scope tree with no ambient inheritance; deletion cascades to derived artifacts |
| Sentinel Core | 4 | Single dispatch path; `AUTH-01`…`AUTH-06` enforced at runtime |
| Adaptive agents + sub-agents | 5 | Attenuation monotonicity at arbitrary depth; no agent-count constant |
| Shared capabilities | 6 | Each has a unique registry responsibility |
| Integration Gateway + adapters | 7 | Contract may not be declared stable until **two adapters in materially different categories** pass conformance (NC-5) |
| Cross-device platform + sync | 8 | `DeviceTrust` × `DeviceWorkspaceGrant` both required (NC-7) |
| Desktop/web clients | 9 | Zero business logic in clients, mechanically checked |
| Voice, themes, UI polish, mobile | 10 | — |

### N.2 Deliberately not planned at all yet

No vector database, embedding model, or RAG design (choosing now is choosing
blind) · no web framework, ORM, message queue, or provider SDK · no multi-region
or residency topology · no third-party capability marketplace · no fine-tuning
or self-hosted inference · no agent-to-agent protocol beyond parent/child
attenuation · no real-time collaboration · no offline/local-first sync · no
billing integration · no SSO/SAML/SCIM (Phase 1 must not preclude it) · no
certification-specific infrastructure (N.6).

---

## O. Updated Blueprint Compliance Check

Original blueprint §§1–40 plus COMMAND 002 §§1–21.

| Source | Requirement | Status | Where |
|---|---|---|---|
| §1, C002 §6 | Domain-neutral | ✔ | `ARCH-12`; agents are configuration |
| §2, C002 D2 | Sentinel orchestrates; components replaceable | ✔ | §D; conformance suites |
| §3, C002 D1 | Core coordinates without monolith | ✔ | §D.2, `ARCH-03` |
| §4, C002 §7 | Provider-neutral model gateway | ✔ deferred to P2 | §N.1 |
| §5 | Prompt orchestration, all declared fields | ✔ contract in P0/P2 | `PromptContract`; `files_forbidden` code-enforced |
| §6, C002 D3 | N adaptive agents, 3 as entitlement | ✔ | `ARCH-11` |
| §7 | Evolution engine recommends, never acts | ✔ | `INV-09`; recommendation record P6 |
| §8 | Research shared, cited, labelled | ✔ deferred to P6 | assertion labels in kernel |
| §9 | Scoped memory, provenance, retention, deletion | ✔ deferred to P3 | no ambient inheritance |
| §10, C002 §5 | Account → Org → Workspace; multi-tenant | ✔ | §E `tenant_scoped`; NC-3 |
| §11 | Identity/authn/authz/licensing/entitlements separate | ✔ | §E — five distinct modules |
| §12 | Invitations, revocation, lockout | ✔ deferred to P1 | session epoch |
| §13, C002 D4 | Permission levels, bounded L4 | ✔ | §G.4, `INV-09` |
| §14, C002 §10 | Integration gateway via adapters; external systems stay external | ✔ | §D, `ARCH-06`, NC-5 |
| §15 | Integrate, do not replace | ✔ | §G.6; no external system is a dependency |
| §16, C002 §15 | Financial boundary | ✔ | §G.6 |
| §17 | Provider-neutral source control | ✔ deferred to P6/P7 | DESTRUCTIVE ladder |
| §18, §19 | Visual pipeline; permission-aware gallery | ✔ deferred to P6 | single `content` owner |
| §20, §21 | Communications; attention vs notification split | ✔ deferred to P6 | separate responsibilities |
| §22 | Commerce composes research | ✔ deferred to P6 | `INV-04` prevents duplicate retrieval owner |
| §23 | Voice replaceable | ✔ deferred to P10 | adapter pattern established |
| §24 | Cross-platform, one Sentinel | ✔ | L9 has zero business logic |
| §25, NC-7 | Device pairing & sync | ✔ deferred to P8 | ADR-0009 |
| §26 | Licensing/entitlements own layer | ✔ | single boundary; founder access audited, never exempt |
| §27 | Intellectual integrity | ✔ | assertion labels are kernel types; tone configurable, integrity not |
| §28, C002 §19 | Two decision-record concepts | ✔ | §K, §J.3, NC-6 |
| §29 | Transparency & audit | ✔ | §J.1 fail-closed list |
| §30, C002 §18 | Observability from the beginning | ✔ | §J.2 acceptance test |
| §31 | Failure engineering | ✔ | `failure_behavior` per capability; durable execution P1 |
| §32, C002 D6 §14 | Security is architecture | ✔ | §G, `AUTH-01`…`AUTH-06` |
| §33, C002 §16 | Capability registry | ✔ | §F, `INV-01`…`INV-16` |
| §34, C002 §20 | Architecture health / erosion | ✔ | §I.3, twelve blocking checks |
| §35 | Installation & onboarding | ✔ partial | L23 covers developers; user onboarding P9 |
| §36, C002 §21 | UI replaceable; no UI in Phase 0 | ✔ | L17 |
| §37, C002 D5 | Build order with persistence/execution first | ✔ | §M, §N.1 |
| §38 | Engineering constitution | ✔ extended | **§38.24** Authority Rule (D6); **§38.25** mechanical enforcement (C002 §2 + NC-1) |
| §39 | Architecture only, no speculative deps | ✔ | zero dependencies added |
| C002 §2 | Mechanical-enforcement rule | ✔ with guard | §I.2, NC-1 |
| C002 §3 | Separate repository | ✔ pending provisioning | §C.1 |
| C002 §4 | Python 3.12+, neutral contracts, PG as infrastructure | ✔ with qualification | NC-4, ADR-0006 |
| C002 §8 | No certification claims | ✔ | §H.3 prohibition |
| C002 §9 | Commercial licensing | ✔ | §H.2, §H.3 |
| C002 §11 | Blocking CI, no AI exemption | ✔ | §H.5, all gates blocking |
| C002 §12 | Clean-room provenance | ✔ | §H |
| C002 §13 | Kernel wording correction | ✔ | §E, `ARCH-05` |
| C002 §17 | Dependency direction | ✔ | §D.3 |

**Constitution additions ratified by this baseline:**
- **§38.24** — Authority never flows from content. External or retrieved content
  is information, not authority.
- **§38.25** — A rule that is not mechanically enforced where practical is only a
  suggestion; therefore every rule carries an enforcement class, and no rule may
  be unclassified.

---

## P. Phase 0 Readiness Verdict

**NOT READY FOR PHASE 0 IMPLEMENTATION**

Exactly one blocking item remains, and it is a provisioning action rather than a
design question:

> **Blocking: §C.1 — Sentinel repository provisioning.**
> Owner decision N.1 mandates a separate repository. It does not yet exist, and
> the authoring session's write scope covers only an unrelated repository.
> Required from the owner: (1) repository owner/name — recommended
> `<owner>/sentinel-platform`; (2) visibility — recommended **private**, per the
> proprietary licensing decision, and not reversible after the fact; (3) either
> create it and add it to this session's scope, or authorize me to create it.

Nothing else blocks. All six deviations are approved and incorporated, all nine
original owner decisions are resolved, the seven new contradictions surfaced by
this review have recommended resolutions already reflected in the baseline, and
§C.2 (ADR-0006's standing form) is a Phase 1 ratification that does not gate
Phase 0.

**The moment the repository exists and is in scope, Step 0 executes and Phase 0
proceeds through §M without further owner input.**
