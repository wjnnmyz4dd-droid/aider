# Phase 3D — Recommended Settings for Demo Testing

- **Trading profile:** `london_conservative` — the profile already
  configured and validated in this phase (reduced risk limits, London
  session window `07:00-16:00 UTC`). Do not switch to an aggressive
  profile until the conservative profile has completed a full demo
  period cleanly.
- **Account type:** MT5 **demo** account only. Do not attach the EA to a
  funded or live account at this stage.
- **Symbol/timeframe:** Start with a single liquid major (EURUSD) on M15,
  matching this phase's validated warmup path (50-bar M15 requirement),
  before expanding to the profile's full allowed-pair list.
- **Broker:** Use the same broker/server you intend to use for eventual
  funded trading — feed quality and `WebRequest` allow-listing behavior
  can differ between brokers.
- **Bridge/API key:** Use the generated `.bridge_api_key.secret` value;
  do not hand-edit it or share it outside your own machine.
- **Magic number:** Keep `bridge.magic_number` and `runtime.magic_number`
  identical (already enforced by `config_loader.py`'s validation) — do
  not create a second EA instance with a different magic number pointed
  at the same Bridge process.
- **Monitoring cadence:** Check `health_check.py` at least once per
  trading day, ideally at both session open and close, for the whole demo
  period.
