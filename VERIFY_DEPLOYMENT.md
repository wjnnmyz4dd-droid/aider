# Verify Deployment

How to confirm a copied Titan Protocol release is actually working on
the VPS, before trusting it with a demo (PAPER) or funded (LIVE)
account. This supersedes the earlier `DEPLOYMENT_PACKAGE/`-based
workflow this document used to describe — that directory no longer
exists in this repository.

**Tests are not shipped in this package** (see `COPY_TO_VPS.md`'s
exclusion list) — the full test suite must already have passed **on the
source repository, before this package was built**. Confirm that was
actually done rather than assumed:

## 1. Confirm the package's provenance

```
type RELEASE_MANIFEST.json
```

Cross-check `source_commit_sha` against the source repository's own
test results for that exact commit — this package is only as
trustworthy as the validation that commit already passed upstream. If
you cannot confirm that, stop here and get a package built from a
commit you can verify.

## 2. Run install.py

```
cd C:\TitanProtocol
python install.py
```

`install.py` itself is the verification harness — it actually
constructs the real `BridgeEngine`, binds the configured transport
(socket by default; also binds an automatic HTTP fallback listener per
ADR-034 Amendment 3 whenever transport is socket), constructs the
Runtime Orchestrator and all 5 core engines, constructs the Reliability
Engine, and copies + personalizes the MT5 EA files — each against the
real object, not a mock. It writes `INSTALLATION_REPORT.md` summarizing
every step's real outcome. Read that report; do not assume success from
"it printed no traceback" alone.

## 3. Run health_check.py

```
python health_check.py
```

Reports, among other things:

- `active transport` — whichever transport (`socket`/`http`) is
  actually configured.
- `bridge reachable (<transport>)` and, when transport is `socket`,
  `HTTP fallback listener reachable` — confirms the automatic fallback
  listener a socket-transport EA can fall back to is actually up.
- `MT5 bridge connectivity (EA heartbeat)` — checks the Bridge's real
  signal that the EA has actually heartbeated, not just that the port
  is open. This will read **FAIL** until you've attached the EA in MT5
  — that is expected before step 5 below, not a defect.
- `magic number consistency (bridge/runtime)` and `EA .set file
  consistency` — catches configuration drift between the live Bridge
  config and the personalized `.set` file MT5 will load.
- `queue health` — the real Bridge command-queue depth against your
  configured degraded/critical thresholds.
- `market-data readiness` and `news provider failover` — real status
  from the live-cycle loop's market-data and news-provider engines;
  both require a running, connected EA reporting real bars before they
  can read HEALTHY.

Overall status will read **DEGRADED**, not FAILED, until a real MT5 EA
is attached and reporting — see `KNOWN_GAPS.md` for exactly which
conditions gate DEGRADED vs FAILED.

## 4. Compile and attach the EA in MT5

Follow `WINDOWS_OPERATOR_GUIDE.md` §4–5: compile `TitanProtocolEA.mq5`
in MetaEditor (confirm **"0 error(s)"**), attach it to a demo chart
first, and load the personalized `TitanProtocolEA.set`. If transport is
socket (the default), confirm the socket address is allow-listed under
MT5 → **Tools → Options → Expert Advisors**; if transport is HTTP (the
explicit rollback), confirm the URL is allow-listed there instead.

## 5. Confirm real EA connectivity

Re-run `python health_check.py`. Expect:

- `MT5 bridge connectivity (EA heartbeat)` now **PASS**.
- Check MT5's own "Experts" tab (bottom panel of the Terminal window)
  for the EA's log lines confirming successful Bridge calls. If the EA
  logs repeated `SocketConnect`/`WebRequest` failures, re-check the
  allow-list step above before assuming a Bridge-side problem.
- After a few minutes of real bars arriving, `market-data readiness`
  should show `fresh`/`accepted` counts increasing for your configured
  pairs.

Confirm in MT5 itself that the connected account is genuinely the demo
account you intended before letting this run unattended.

## 6. LIVE go-live check

Only once PAPER/demo validation above has run clean for as long as your
own risk process requires, repeat steps 2–5 against a real MT5 **live**
account. Status will still read DEGRADED by design (see
`KNOWN_GAPS.md`'s residual limitations) — DEGRADED here describes known,
documented scope boundaries, not an unresolved defect blocking go-live.
Do not proceed if any check reports an outcome not explained by
`KNOWN_GAPS.md`.

## 7. Backup verification

Confirm at least one backup was taken per `COPY_TO_VPS.md` §2 before
this deployment went live, and that it is non-empty and roughly the
expected size.

## 8. Sign-off

Do not consider a deployment verified until steps 1–6 have each been
performed by a human operator who read the actual output — "it ran
without a traceback" is not the same as a deployment that passed every
check in this document.
