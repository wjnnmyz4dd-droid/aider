"""Operator session-selection front-end (zero-friction UX) — NOT a session authority.

This module makes "which sessions are active?" easy to choose and remember, WITHOUT
becoming a second session-eligibility authority. The single authority stays exactly
where it was: runtime.config -> session.model.SessionModel (validated, fail-closed),
which the producer consumes via session.profiles.profiles_for. This module only:

  * NORMALIZES an operator selection deterministically (one normalizer, reused by the
    launcher CLI) — upper-case, dedup, canonical order, 'ALL' expansion, fail-closed on
    unknown/empty;
  * PERSISTS the chosen selection (like runtime.mt5_terminal / runtime.capital already
    persist the terminal + capital base) so a normal restart needs no flags or env
    edits;
  * RESOLVES the effective selection with deterministic precedence
    (explicit CLI > persisted > default LONDON).

Whatever it resolves is written into SESSION_EDGE_ENABLED_SESSIONS for the children,
and runtime.config re-validates it independently (defense in depth). Nothing here
decides eligibility, times, or geometry.
"""

from __future__ import annotations

from pathlib import Path

from ..bridge import serialize
from ..bridge.atomic import atomic_write_text
from ..session.profiles import SUPPORTED_SESSION_IDS

SELECTION_SCHEMA_VERSION = 1
SELECTION_FILE = "sessions.json"
DEFAULT_SESSIONS = ("LONDON",)


class SessionSelectionError(ValueError):
    """Raised when an operator session selection cannot be normalized safely (fail
    closed) — unknown session name, empty selection, or a corrupt persisted file."""


def normalize_sessions(raw):
    """The ONE session-selection normalizer. Accepts a comma/space string or a
    list/tuple. Returns a deterministic, deduplicated, canonically-ordered tuple.
    'ALL' expands to EXACTLY the four canonical profiles. Raises SessionSelectionError
    on an unknown or empty selection (fail closed) — never silently substitutes."""
    if raw is None:
        raise SessionSelectionError("no sessions selected")
    if isinstance(raw, (list, tuple)):
        tokens = [str(t).strip().upper() for t in raw]
    else:
        tokens = [t.strip().upper() for t in str(raw).replace(",", " ").split()]
    tokens = [t for t in tokens if t]
    if not tokens:
        raise SessionSelectionError("no sessions selected")
    if "ALL" in tokens:
        return tuple(SUPPORTED_SESSION_IDS)
    unknown = [t for t in tokens if t not in SUPPORTED_SESSION_IDS]
    if unknown:
        raise SessionSelectionError(
            f"unknown session(s): {unknown} "
            f"(supported: {list(SUPPORTED_SESSION_IDS)} or ALL)")
    # canonical order; dedup
    return tuple(s for s in SUPPORTED_SESSION_IDS if s in set(tokens))


def selection_store_path(home=None):
    """Stable, pre-connect persistence location (one file, owned solely by this
    module) — the same ~/.session_edge home the terminal selection uses."""
    base = Path(home) if home is not None else Path.home()
    return base / ".session_edge" / SELECTION_FILE


def load_persisted(store_path):
    """Return the persisted canonical session tuple, or None if no selection has been
    saved yet. A file that EXISTS but is corrupt/unknown FAILS CLOSED (raises) rather
    than silently reverting to a different session — an absent file is 'no selection
    yet' (the caller may use its default), which is different from 'invalid selection'."""
    try:
        text = Path(store_path).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    ok, obj = serialize.loads(text)
    if not ok or not isinstance(obj, dict):
        raise SessionSelectionError(
            f"persisted session selection is corrupt at {store_path} "
            f"(re-select with --sessions to repair)")
    sessions = obj.get("sessions")
    # normalize() re-validates the stored value; unknown/empty raises (fail closed)
    return normalize_sessions(sessions)


def persist(store_path, sessions, now_iso):
    """Atomically record the (already-normalized) session selection for next run."""
    p = Path(store_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(p, serialize.canonical_json({
        "schema_version": SELECTION_SCHEMA_VERSION,
        "sessions": list(sessions),
        "saved_at": now_iso,
    }))
    return tuple(sessions)


def resolve(cli_raw, store_path, *, default=DEFAULT_SESSIONS, now_iso=None,
            persist_cli=True):
    """Resolve the effective session selection. Deterministic precedence:

        explicit CLI  >  persisted selection  >  default (LONDON)

    An explicit CLI selection is normalized and (by default) persisted so the next
    plain restart reuses it — true zero-friction. A present-but-invalid persisted file
    fails closed (load_persisted raises). Returns (sessions_tuple, source) where source
    is one of 'cli' | 'persisted' | 'default'. Never silently substitutes a different
    session for an invalid selection."""
    if cli_raw not in (None, ""):
        sessions = normalize_sessions(cli_raw)
        if persist_cli:
            persist(store_path, sessions, now_iso or "")
        return sessions, "cli"
    persisted = load_persisted(store_path)      # may raise on corrupt file (fail closed)
    if persisted:
        return persisted, "persisted"
    return normalize_sessions(default), "default"
