"""Canonical per-account FTMO capital-base persistence (zero-friction startup).

`initial_balance` in Session Edge means the **FTMO challenge STARTING capital** — the
fixed anchor of the static max-loss floor (`compliance.contract.ftmo_levels`:
``max_level = initial − maximum_loss_pct × initial``) and the PR-3J per-trade risk
budget (``candidate_risk_amount = risk_fraction × initial_balance``). It is NOT the
current balance/equity and must be **pinned** — deriving it from a changing live
balance would drift the loss floor and change live risk (H3).

This module is the ONE owner that lets the launcher establish that pinned value
without the operator re-typing it every start: it captures the value **once per MT5
account identity**, persists it immutably (atomic write, reusing
``bridge.atomic.atomic_write_text`` + ``bridge.serialize``), and reuses it on every
restart. It never re-reads the live balance for an already-initialized account, never
inherits another account's base, and fails closed on a malformed record.

It adds NO trade authority and does NOT change any risk/FTMO formula — it only
determines the number the launcher passes as ``SESSION_EDGE_INITIAL_BALANCE`` (exactly
as ``--initial-balance`` did before), which the existing fail-closed config validates.
"""

from __future__ import annotations

from pathlib import Path

from ..bridge import serialize
from ..bridge.atomic import atomic_write_text

CAPITAL_SCHEMA_VERSION = 1

SOURCE_CLI = "operator_cli"                 # explicit --initial-balance on first init
SOURCE_FIRST_INIT = "first_init_capture"    # zero-friction: captured current DEMO balance once
SOURCE_REINIT = "reinitialize"              # explicit operator reset (--reinitialize)


class CapitalBaseError(RuntimeError):
    """Raised on a malformed/unreadable capital record. Fail closed."""


def account_key(login, server):
    """Stable identity for one MT5 account (login @ server). Both required."""
    if login in (None, "") or server in (None, ""):
        return None
    return f"{login}@{server}"


def mask_account(login):
    """A display-safe account identifier (never the password): masks all but the last
    four digits of the login number."""
    s = str(login) if login is not None else ""
    if len(s) <= 4:
        return "****"
    return "***" + s[-4:]


def _pos_float(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


class CapitalBaseStore:
    """Immutable, per-account capital-base records persisted to one JSON file
    (``{"records": {key: record}}``). Multiple accounts on one terminal coexist; each
    account's base is written at most once (unless an explicit reinitialize replaces
    it). Read is fail-closed: a corrupt file raises rather than silently resetting."""

    def __init__(self, path):
        self.path = Path(path)

    def _read_all(self):
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except OSError as exc:
            raise CapitalBaseError(f"capital record unreadable: {self.path} ({exc})")
        ok, obj = serialize.loads(text)
        if not ok or not isinstance(obj, dict) or not isinstance(obj.get("records"), dict):
            raise CapitalBaseError(f"capital record malformed: {self.path}")
        return obj["records"]

    def get(self, key):
        """Validated record for ``key`` or None. Raises on a malformed store or a
        present-but-invalid record (fail closed — never a silent zero)."""
        if key is None:
            return None
        rec = self._read_all().get(key)
        if rec is None:
            return None
        if not isinstance(rec, dict) or _pos_float(rec.get("initial_balance")) is None \
                or rec.get("account_key") != key:
            raise CapitalBaseError(f"capital record for {key} is invalid/mismatched")
        return rec

    def other_keys(self, key):
        """Keys for OTHER accounts already stored (used to flag an account change)."""
        return sorted(k for k in self._read_all() if k != key)

    def set(self, key, record):
        """Atomically upsert one account's record (merges with other accounts)."""
        records = {}
        try:
            records = dict(self._read_all())
        except CapitalBaseError:
            records = {}                    # a corrupt store is replaced only on explicit write
        records[key] = record
        atomic_write_text(self.path, serialize.canonical_json({"records": records}))
        return record


def _record(key, login, server, initial_balance, currency, source, now_iso):
    return {
        "schema_version": CAPITAL_SCHEMA_VERSION,
        "account_key": key,
        "account_login": login,
        "account_server": server,
        "initial_balance": float(initial_balance),
        "currency": currency,
        "source": source,
        "captured_at": now_iso,
    }


class Resolution:
    """Outcome of resolving the pinned capital base. ``ok`` gates startup."""

    def __init__(self, ok, *, initial_balance=None, source=None, message="",
                 persisted=False, reason=None):
        self.ok = ok
        self.initial_balance = initial_balance
        self.source = source
        self.message = message
        self.persisted = persisted
        self.reason = reason


def resolve_capital_base(store, *, login, server, currency, current_balance,
                         cli_initial, reinitialize, now_iso):
    """Determine the pinned FTMO capital base for the connected account, persisting it
    on first initialization. PURE w.r.t. MT5 (all inputs injected). Precedence:

      1. ``--reinitialize N``  -> explicit reset: pin & persist N (overwrites).
      2. persisted record      -> use it (pinned); a conflicting ``--initial-balance``
                                  FAILS CLOSED (never silently overwrites).
      3. ``--initial-balance N`` (no record) -> pin & persist N (explicit first init).
      4. no record, no flag    -> capture the current DEMO balance ONCE, pin & persist
                                  (Section C-B; DEMO first-run convenience).

    Fails closed (ok=False) when the account identity is unresolved, a supplied value
    is non-positive, or (4) has no positive current balance to capture."""
    key = account_key(login, server)
    if key is None:
        return Resolution(False, reason="ACCOUNT IDENTITY UNAVAILABLE",
                          message="Could not read the MT5 account login/server; cannot "
                                  "establish a capital base. Ensure MT5 is logged in.")

    if reinitialize is not None:
        v = _pos_float(reinitialize)
        if v is None:
            return Resolution(False, reason="INVALID REINITIALIZE VALUE",
                              message="--reinitialize must be a positive number.")
        store.set(key, _record(key, login, server, v, currency, SOURCE_REINIT, now_iso))
        return Resolution(True, initial_balance=v, source=SOURCE_REINIT, persisted=True,
                          message=f"Capital base RE-INITIALIZED to {v:,.2f} for {mask_account(login)}.")

    existing = store.get(key)               # may raise CapitalBaseError -> caller fails closed
    if existing is not None:
        pinned = float(existing["initial_balance"])
        cli = _pos_float(cli_initial) if cli_initial is not None else None
        if cli is not None and cli != pinned:
            return Resolution(False, reason="CAPITAL BASE CONFLICT",
                              message=(f"A pinned capital base of {pinned:,.2f} already "
                                       f"exists for {mask_account(login)}. Refusing to "
                                       f"silently overwrite it with {cli:,.2f}. Re-run with "
                                       f"--reinitialize {cli:g} to change it deliberately."))
        return Resolution(True, initial_balance=pinned, source=existing.get("source", "persisted"),
                          persisted=False,
                          message=f"Capital base {pinned:,.2f} (pinned for {mask_account(login)}).")

    # No record for this account yet -> first initialization.
    changed = bool(store.other_keys(key))   # a DIFFERENT account was used before
    prefix = ("ACCOUNT CHANGED — initializing a NEW capital base (previous account bases "
              "are never reused). ") if changed else ""

    cli = _pos_float(cli_initial) if cli_initial is not None else None
    if cli is not None:
        store.set(key, _record(key, login, server, cli, currency, SOURCE_CLI, now_iso))
        return Resolution(True, initial_balance=cli, source=SOURCE_CLI, persisted=True,
                          message=f"{prefix}Capital base set to {cli:,.2f} (operator-provided) "
                                  f"and pinned for {mask_account(login)}.")

    v = _pos_float(current_balance)
    if v is None:
        return Resolution(False, reason="CAPITAL BASE NOT ESTABLISHED",
                          message=(f"{prefix}No pinned capital base for {mask_account(login)} "
                                   f"and the current account balance is unavailable. Re-run "
                                   f"with --initial-balance <your FTMO starting capital>."))
    store.set(key, _record(key, login, server, v, currency, SOURCE_FIRST_INIT, now_iso))
    return Resolution(True, initial_balance=v, source=SOURCE_FIRST_INIT, persisted=True,
                      message=(f"{prefix}FIRST RUN for {mask_account(login)}: captured the current "
                               f"DEMO balance {v:,.2f} as the pinned capital base. This assumes the "
                               f"account is at its starting capital; if the true FTMO starting "
                               f"capital differs, re-run with --reinitialize <N>."))
