# Titan Protocol Installation Report

**This is a template, not a real report.** `install.py` generates the real
`INSTALLATION_REPORT.md` (same folder) after it actually runs, with every
row reflecting what genuinely happened on your machine -- it is never
copied from this file. This template exists purely so you can see the
shape of that report, and what each outcome label means, before running
`install.py` for the first time.

Generated: `<ISO-8601 timestamp of the real install.py run>`
Overall result: `SUCCESS` | `INCOMPLETE -- see FAILED step(s) below`

| Step | Outcome | Detail |
|---|---|---|
| Verify running from the full release package | OK / FAILED | Confirms `titan_protocol/` and `mt5/` sit next to `install.py` |
| Create configuration | OK / FAILED | Copies `config/titan_protocol_config.example.json` to `titan_protocol_config.json` if missing |
| Generate Bridge API key | OK / FAILED | Generates and stores a local shared secret if one doesn't already exist |
| Run deploy.py (venv, dependencies, folders, compile, import smoke test) | OK / FAILED | Runs deploy.py's own 9-step sequence |
| Copy + personalize MT5 EA files | OK / SKIPPED / FAILED | SKIPPED is not fatal -- see the detail column for what to do manually |
| Verify Bridge | OK / FAILED | Actually binds the Bridge HTTP server and confirms it's reachable |
| Verify Runtime | OK / FAILED | Actually constructs all 5 core engines + RuntimeOrchestrator |
| Verify Reliability | OK / FAILED | Actually calls ReliabilityEngine.evaluate_health() |
| Verify news providers (Trading Economics primary / Forex Factory backup) | INFO | Always informational -- reports that this component does not exist yet (see KNOWN_GAPS.md) |
| Create desktop shortcuts | OK / SKIPPED / FAILED | SKIPPED (not a failure) on anything other than real Windows |
| Launch Titan Protocol | OK / FAILED | Starts Titan Protocol the same way `python start.py` does |

## What OK / INFO / SKIPPED / FAILED mean

- **OK**: verified for real in this run.
- **INFO**: reported honestly, not a pass/fail -- the news-provider check
  reports a real, pre-existing gap rather than fabricating success.
- **SKIPPED**: not fatal to installation, but not completed -- follow the
  detail column to finish it manually (e.g. MT5 folder ambiguity, non-Windows
  shortcut creation).
- **FAILED**: a real problem; installation is not complete until this is fixed.

## Next steps

1. Open MT5.
2. Compile TitanProtocolEA.mq5 in MetaEditor (F4 in MT5, then F7) -- this
   installer cannot do this for you; it requires the real MetaEditor GUI.
3. Attach TitanProtocolEA to a demo chart, and click Load in its settings
   dialog to load the personalized TitanProtocolEA.set (already filled in
   with the generated API key and matching magic number).
4. Run `python health_check.py` to confirm `[PASS] MT5 bridge connectivity
   (EA heartbeat)` once the EA is attached and running.

See `KNOWN_GAPS.md` for what this deployment layer honestly cannot do yet
(a live trading-cycle loop, and Trading Economics/Forex Factory news
provider verification) and `WINDOWS_OPERATOR_GUIDE.md` for full detail.
