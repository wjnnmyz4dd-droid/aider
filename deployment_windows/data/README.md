# data/

Reserved for a future market-data component. **Nothing in this release
reads from or writes to this folder today** -- `phantom/
market_data_ingestion/` (ADR-033 Part 1) exists as a standalone,
tested package, but it is not wired into any live entry point (see
`../KNOWN_GAPS.md` section 1), so there is no live OHLC bar cache or
historical-data store to put here yet.

This folder exists (rather than being created silently on first run)
so the release package's root structure is complete and inspectable
before you ever run `install.py`. `logs/` and `state/` are the two
folders Phantom's current runtime actually uses -- see
`WINDOWS_OPERATOR_GUIDE.md`.
