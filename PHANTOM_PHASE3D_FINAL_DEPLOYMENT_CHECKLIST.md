# Phase 3D — Final Deployment Checklist

For the user's own real Windows/MT5 environment. Complete every item in
order; do not skip ahead if an earlier item fails.

- [ ] Download and extract `titan_protocol_windows_complete_release.zip`
      to `C:\TitanProtocol` (or your chosen install root).
- [ ] Run `python install.py` from that folder. Confirm it reports success
      for every step (config generation, secret generation, folder
      creation).
- [ ] Run `python install_mt5_files.py`. Confirm it finds and lists your
      MT5 terminal's data folder.
- [ ] Copy `TitanProtocolEA.mq5` into that terminal's `MQL5\Experts\`
      folder (the installer does this automatically if it found your
      terminal — verify the file is actually there, not just the
      installer script itself).
- [ ] Open MetaEditor, open `TitanProtocolEA.mq5`, compile it. Confirm
      zero compile errors.
- [ ] Attach the compiled EA to an EURUSD M15 chart (or your primary
      configured pair/timeframe).
- [ ] In the EA's Inputs tab, confirm `ApiKey` is filled in (copy the
      value from `.bridge_api_key.secret` in your install folder if
      blank) and `MagicNumber` matches your `titan_protocol_config.json`'s
      `bridge.magic_number`.
- [ ] Enable "Algo Trading" in MT5's toolbar.
- [ ] Check the MT5 Experts log for
      `"TitanProtocolEA initialized. Symbol=... Magic=..."` with no
      errors after it.
- [ ] Run `python start.py` from your install folder. Confirm it reports
      DEGRADED (not FAILED) after startup.
- [ ] Run `python health_check.py` and confirm:
  - `MT5 bridge connectivity (EA heartbeat)` becomes PASS within ~30
    seconds of the EA initializing.
  - `market-data readiness` shows warmup counts climbing toward
    `ready` for your configured pair(s) as new M15 bars close.
- [ ] Leave it running through at least one full session window (e.g. the
      London session for `london_conservative`) and re-run
      `health_check.py` — confirm warmup eventually reaches `ready` for
      your primary pair without any manual restart.
- [ ] Confirm `live trading cycle active` reports your primary pair as
      evaluated (not permanently skipped) once warmup/freshness clear.
- [ ] Do **not** enable a funded account at this stage — proceed to the
      demo-testing period first (see Recommended Settings and Recommended
      Timeline documents).
