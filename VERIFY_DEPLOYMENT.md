# Verify Deployment

How to confirm a copied `DEPLOYMENT_PACKAGE/` is actually working on the
VPS, before trusting it with a demo (PAPER) or funded (LIVE) account.

**Tests are not shipped in this package** (`COPY_TO_VPS.md`'s explicit
exclusion list) — the full `1264/1264`-test suite, `validate.py`'s 13
checks, and `scripts/check_architecture.py` must already have passed
**on the source repository, before this package was built**. Confirm
that was actually done rather than assumed:

## 1. Confirm the package's provenance

```
type VERSION.txt
```

Cross-check the commit hash against the source repository's own CI/test
results for that exact commit — this package is only as trustworthy as
the validation that commit already passed upstream. If you cannot
confirm that, stop here and get a package built from a commit you can
verify.

## 2. Compile check (on the VPS itself)

A clean checkout can still fail on a VPS missing a system dependency —
run this on the VPS, not just on the machine that built the package:

```
python -m compileall phantom_pipeline
```

Must report no errors.

## 3. Dependency check

```
pip install -r requirements.txt
python -c "import MetaTrader5; print('MetaTrader5 OK')"
```

If this fails, `MT5Adapter`/`MarketDataAdapter` cannot connect to a real
terminal — every profile beyond a DEV smoke test needs this to succeed.

## 4. DEV smoke test (construction-only, no live connection required to start)

```
scripts\start_phantom.bat DEV
```

Expected: every stage engine constructs without raising, and the
printed `ServiceStatus` list appears (an `mt5_terminal: CRASHED` entry
here is expected and correct if the MT5 terminal is not yet running or
not yet logged in — it means `MT5Adapter.connect()` itself works and
correctly reports failure, not that the wiring is broken; re-run after
starting/logging in to the terminal to confirm it flips to `RUNNING`).

## 5. Configuration validation check

For whichever profile you intend to run:

```
scripts\start_phantom.bat PAPER
```

(or `LIVE`) — with an incomplete `config\PAPER.env`/`LIVE.env`, confirm
it **fails** with a clear `[ERROR]` list naming exactly what's missing
(this is `ConfigurationManager.validate` working correctly, not a bug).
Fill in the missing fields and re-run until it proceeds past
configuration validation.

## 6. PAPER profile connectivity check

With a real MT5 **demo** account configured:

```
scripts\start_phantom.bat PAPER
```

Expected: `[PAPER] connected.` printed, followed by cycle activity.
Confirm in the MT5 terminal itself that the connected account is
genuinely the demo account you intended — `PaperTradingRunner`'s own
`confirm_demo_account` probe is the safety net, but an operator
double-check before the first real cycle is still worthwhile. Let it run
a few cycles, then Ctrl+C and confirm the console prints
`[PAPER] stopped gracefully.`

## 7. LIVE profile go-live check

With a real MT5 **live** account configured (only once PAPER validation
above has run clean for as long as your own risk process requires):

```
scripts\start_phantom.bat LIVE
```

Expected: `[LIVE] DeploymentValidator: all_passed=True` with all 10
checks printed as `PASS`, including `emergency_stop_functional`. If any
check prints `FAIL`, **do not proceed** — read `LIVE_DEPLOYMENT_GUIDE.md`
§5 for what each check means and resolve it before re-running.

Remember (see `START_PHANTOM.md` §4): a clean `LIVE` run here confirms
the deployment is *ready*, not that it is *actively trading* — no
continuous live-order scheduler ships in this codebase yet.

## 8. Backup verification

Confirm at least one backup was taken and verified since this
deployment (`DISASTER_RECOVERY.md` §3):

```
python -c "from phantom_pipeline.deployment import BackupManager; m = BackupManager(r'C:\phantom_backups'); print('see DISASTER_RECOVERY.md for verify_integrity usage against your own manifest')"
```

## 9. Sign-off

Do not consider a deployment verified until steps 1–7 have each been
performed by a human operator who read the actual output — a script
that merely "ran without a Python traceback" is not the same as a
deployment that passed every check in this document. Use
`OPERATOR_CHECKLIST.md` for the ongoing (post-verification) daily
checklist.
