# Deployment Manifest — Source -> VPS Destination

**Status: HISTORICAL.** `DEPLOYMENT_PACKAGE/` was removed from this
repository once the Python `deployment_windows/` installer superseded
it — the current release's file manifest is `RELEASE_MANIFEST.json`,
generated fresh inside each built ZIP. This document maps a now-removed
directory's contents and does not describe anything present in the
repository today.

Every file in `DEPLOYMENT_PACKAGE/`, mapped to its destination on the
Windows VPS, assuming `C:\phantom\` as the install root (per
`VPS_SETUP_GUIDE.md`). Adjust the drive/root prefix if your VPS uses a
different install path — the relative structure after `C:\phantom\`
never changes.

```
SOURCE (relative to DEPLOYMENT_PACKAGE/)                               -> DESTINATION (on VPS)
----------------------------------------                               -> ---------------------
VERSION.txt                                                            -> C:\phantom\VERSION.txt
config/dev.env.template                                                -> C:\phantom\config\dev.env.template
config/live.env.template                                               -> C:\phantom\config\live.env.template
config/paper.env.template                                              -> C:\phantom\config\paper.env.template
phantom_pipeline/__init__.py                                           -> C:\phantom\phantom_pipeline\__init__.py
phantom_pipeline/analytics/__init__.py                                 -> C:\phantom\phantom_pipeline\analytics\__init__.py
phantom_pipeline/analytics/attribution.py                              -> C:\phantom\phantom_pipeline\analytics\attribution.py
phantom_pipeline/analytics/checks.py                                   -> C:\phantom\phantom_pipeline\analytics\checks.py
phantom_pipeline/analytics/config.py                                   -> C:\phantom\phantom_pipeline\analytics\config.py
phantom_pipeline/analytics/engine.py                                   -> C:\phantom\phantom_pipeline\analytics\engine.py
phantom_pipeline/analytics/logging_sink.py                             -> C:\phantom\phantom_pipeline\analytics\logging_sink.py
phantom_pipeline/analytics/metrics.py                                  -> C:\phantom\phantom_pipeline\analytics\metrics.py
phantom_pipeline/analytics/models.py                                   -> C:\phantom\phantom_pipeline\analytics\models.py
phantom_pipeline/analytics/performance.py                              -> C:\phantom\phantom_pipeline\analytics\performance.py
phantom_pipeline/analytics/store.py                                    -> C:\phantom\phantom_pipeline\analytics\store.py
phantom_pipeline/compliance_engine/__init__.py                         -> C:\phantom\phantom_pipeline\compliance_engine\__init__.py
phantom_pipeline/compliance_engine/checks.py                           -> C:\phantom\phantom_pipeline\compliance_engine\checks.py
phantom_pipeline/compliance_engine/config.py                           -> C:\phantom\phantom_pipeline\compliance_engine\config.py
phantom_pipeline/compliance_engine/engine.py                           -> C:\phantom\phantom_pipeline\compliance_engine\engine.py
phantom_pipeline/compliance_engine/logging_sink.py                     -> C:\phantom\phantom_pipeline\compliance_engine\logging_sink.py
phantom_pipeline/compliance_engine/metrics.py                          -> C:\phantom\phantom_pipeline\compliance_engine\metrics.py
phantom_pipeline/compliance_engine/models.py                           -> C:\phantom\phantom_pipeline\compliance_engine\models.py
phantom_pipeline/compliance_engine/state_store.py                      -> C:\phantom\phantom_pipeline\compliance_engine\state_store.py
phantom_pipeline/dashboard/__init__.py                                 -> C:\phantom\phantom_pipeline\dashboard\__init__.py
phantom_pipeline/dashboard/config.py                                   -> C:\phantom\phantom_pipeline\dashboard\config.py
phantom_pipeline/dashboard/engine.py                                   -> C:\phantom\phantom_pipeline\dashboard\engine.py
phantom_pipeline/dashboard/logging_sink.py                             -> C:\phantom\phantom_pipeline\dashboard\logging_sink.py
phantom_pipeline/dashboard/metrics.py                                  -> C:\phantom\phantom_pipeline\dashboard\metrics.py
phantom_pipeline/dashboard/models.py                                   -> C:\phantom\phantom_pipeline\dashboard\models.py
phantom_pipeline/dashboard/prometheus_adapter.py                       -> C:\phantom\phantom_pipeline\dashboard\prometheus_adapter.py
phantom_pipeline/dashboard/prometheus_port.py                          -> C:\phantom\phantom_pipeline\dashboard\prometheus_port.py
phantom_pipeline/data_pipeline/__init__.py                             -> C:\phantom\phantom_pipeline\data_pipeline\__init__.py
phantom_pipeline/data_pipeline/bars.py                                 -> C:\phantom\phantom_pipeline\data_pipeline\bars.py
phantom_pipeline/data_pipeline/config.py                               -> C:\phantom\phantom_pipeline\data_pipeline\config.py
phantom_pipeline/data_pipeline/gaps.py                                 -> C:\phantom\phantom_pipeline\data_pipeline\gaps.py
phantom_pipeline/data_pipeline/health.py                               -> C:\phantom\phantom_pipeline\data_pipeline\health.py
phantom_pipeline/data_pipeline/historical.py                           -> C:\phantom\phantom_pipeline\data_pipeline\historical.py
phantom_pipeline/data_pipeline/ingest.py                               -> C:\phantom\phantom_pipeline\data_pipeline\ingest.py
phantom_pipeline/data_pipeline/logging_sink.py                         -> C:\phantom\phantom_pipeline\data_pipeline\logging_sink.py
phantom_pipeline/data_pipeline/market_data_adapter.py                  -> C:\phantom\phantom_pipeline\data_pipeline\market_data_adapter.py
phantom_pipeline/data_pipeline/metrics.py                              -> C:\phantom\phantom_pipeline\data_pipeline\metrics.py
phantom_pipeline/data_pipeline/models.py                               -> C:\phantom\phantom_pipeline\data_pipeline\models.py
phantom_pipeline/data_pipeline/normalize.py                            -> C:\phantom\phantom_pipeline\data_pipeline\normalize.py
phantom_pipeline/data_pipeline/pipeline.py                             -> C:\phantom\phantom_pipeline\data_pipeline\pipeline.py
phantom_pipeline/data_pipeline/quality.py                              -> C:\phantom\phantom_pipeline\data_pipeline\quality.py
phantom_pipeline/data_pipeline/replay.py                               -> C:\phantom\phantom_pipeline\data_pipeline\replay.py
phantom_pipeline/data_pipeline/trace.py                                -> C:\phantom\phantom_pipeline\data_pipeline\trace.py
phantom_pipeline/deployment/__init__.py                                -> C:\phantom\phantom_pipeline\deployment\__init__.py
phantom_pipeline/deployment/backup_manager.py                          -> C:\phantom\phantom_pipeline\deployment\backup_manager.py
phantom_pipeline/deployment/config_manager.py                          -> C:\phantom\phantom_pipeline\deployment\config_manager.py
phantom_pipeline/deployment/deployment_manager.py                      -> C:\phantom\phantom_pipeline\deployment\deployment_manager.py
phantom_pipeline/deployment/deployment_validator.py                    -> C:\phantom\phantom_pipeline\deployment\deployment_validator.py
phantom_pipeline/deployment/logging_manager.py                         -> C:\phantom\phantom_pipeline\deployment\logging_manager.py
phantom_pipeline/deployment/models.py                                  -> C:\phantom\phantom_pipeline\deployment\models.py
phantom_pipeline/deployment/monitoring.py                              -> C:\phantom\phantom_pipeline\deployment\monitoring.py
phantom_pipeline/deployment/service_manager.py                         -> C:\phantom\phantom_pipeline\deployment\service_manager.py
phantom_pipeline/execution_validator/__init__.py                       -> C:\phantom\phantom_pipeline\execution_validator\__init__.py
phantom_pipeline/execution_validator/checks.py                         -> C:\phantom\phantom_pipeline\execution_validator\checks.py
phantom_pipeline/execution_validator/config.py                         -> C:\phantom\phantom_pipeline\execution_validator\config.py
phantom_pipeline/execution_validator/engine.py                         -> C:\phantom\phantom_pipeline\execution_validator\engine.py
phantom_pipeline/execution_validator/idempotency_store.py              -> C:\phantom\phantom_pipeline\execution_validator\idempotency_store.py
phantom_pipeline/execution_validator/logging_sink.py                   -> C:\phantom\phantom_pipeline\execution_validator\logging_sink.py
phantom_pipeline/execution_validator/metrics.py                        -> C:\phantom\phantom_pipeline\execution_validator\metrics.py
phantom_pipeline/execution_validator/models.py                         -> C:\phantom\phantom_pipeline\execution_validator\models.py
phantom_pipeline/knowledge/__init__.py                                 -> C:\phantom\phantom_pipeline\knowledge\__init__.py
phantom_pipeline/knowledge/config.py                                   -> C:\phantom\phantom_pipeline\knowledge\config.py
phantom_pipeline/knowledge/embeddings.py                               -> C:\phantom\phantom_pipeline\knowledge\embeddings.py
phantom_pipeline/knowledge/engine.py                                   -> C:\phantom\phantom_pipeline\knowledge\engine.py
phantom_pipeline/knowledge/ingestion.py                                -> C:\phantom\phantom_pipeline\knowledge\ingestion.py
phantom_pipeline/knowledge/logging_sink.py                             -> C:\phantom\phantom_pipeline\knowledge\logging_sink.py
phantom_pipeline/knowledge/memory.py                                   -> C:\phantom\phantom_pipeline\knowledge\memory.py
phantom_pipeline/knowledge/metrics.py                                  -> C:\phantom\phantom_pipeline\knowledge\metrics.py
phantom_pipeline/knowledge/models.py                                   -> C:\phantom\phantom_pipeline\knowledge\models.py
phantom_pipeline/knowledge/retriever.py                                -> C:\phantom\phantom_pipeline\knowledge\retriever.py
phantom_pipeline/knowledge/search.py                                   -> C:\phantom\phantom_pipeline\knowledge\search.py
phantom_pipeline/knowledge/vector_store.py                             -> C:\phantom\phantom_pipeline\knowledge\vector_store.py
phantom_pipeline/mt5_bridge/__init__.py                                -> C:\phantom\phantom_pipeline\mt5_bridge\__init__.py
phantom_pipeline/mt5_bridge/broker_adapter.py                          -> C:\phantom\phantom_pipeline\mt5_bridge\broker_adapter.py
phantom_pipeline/mt5_bridge/checks.py                                  -> C:\phantom\phantom_pipeline\mt5_bridge\checks.py
phantom_pipeline/mt5_bridge/config.py                                  -> C:\phantom\phantom_pipeline\mt5_bridge\config.py
phantom_pipeline/mt5_bridge/engine.py                                  -> C:\phantom\phantom_pipeline\mt5_bridge\engine.py
phantom_pipeline/mt5_bridge/execution_id.py                            -> C:\phantom\phantom_pipeline\mt5_bridge\execution_id.py
phantom_pipeline/mt5_bridge/idempotency_store.py                       -> C:\phantom\phantom_pipeline\mt5_bridge\idempotency_store.py
phantom_pipeline/mt5_bridge/logging_sink.py                            -> C:\phantom\phantom_pipeline\mt5_bridge\logging_sink.py
phantom_pipeline/mt5_bridge/metrics.py                                 -> C:\phantom\phantom_pipeline\mt5_bridge\metrics.py
phantom_pipeline/mt5_bridge/models.py                                  -> C:\phantom\phantom_pipeline\mt5_bridge\models.py
phantom_pipeline/mt5_bridge/mt5_adapter.py                             -> C:\phantom\phantom_pipeline\mt5_bridge\mt5_adapter.py
phantom_pipeline/orchestrator.py                                       -> C:\phantom\phantom_pipeline\orchestrator.py
phantom_pipeline/paper_trading/__init__.py                             -> C:\phantom\phantom_pipeline\paper_trading\__init__.py
phantom_pipeline/paper_trading/account_tracker.py                      -> C:\phantom\phantom_pipeline\paper_trading\account_tracker.py
phantom_pipeline/paper_trading/forward_test_engine.py                  -> C:\phantom\phantom_pipeline\paper_trading\forward_test_engine.py
phantom_pipeline/paper_trading/paper_trading_runner.py                 -> C:\phantom\phantom_pipeline\paper_trading\paper_trading_runner.py
phantom_pipeline/paper_trading/prop_firm_validator.py                  -> C:\phantom\phantom_pipeline\paper_trading\prop_firm_validator.py
phantom_pipeline/paper_trading/report_generator.py                     -> C:\phantom\phantom_pipeline\paper_trading\report_generator.py
phantom_pipeline/paper_trading/session_manager.py                      -> C:\phantom\phantom_pipeline\paper_trading\session_manager.py
phantom_pipeline/paper_trading/validation_dashboard.py                 -> C:\phantom\phantom_pipeline\paper_trading\validation_dashboard.py
phantom_pipeline/position_manager/__init__.py                          -> C:\phantom\phantom_pipeline\position_manager\__init__.py
phantom_pipeline/position_manager/checks.py                            -> C:\phantom\phantom_pipeline\position_manager\checks.py
phantom_pipeline/position_manager/config.py                            -> C:\phantom\phantom_pipeline\position_manager\config.py
phantom_pipeline/position_manager/engine.py                            -> C:\phantom\phantom_pipeline\position_manager\engine.py
phantom_pipeline/position_manager/execution_id.py                      -> C:\phantom\phantom_pipeline\position_manager\execution_id.py
phantom_pipeline/position_manager/logging_sink.py                      -> C:\phantom\phantom_pipeline\position_manager\logging_sink.py
phantom_pipeline/position_manager/metrics.py                           -> C:\phantom\phantom_pipeline\position_manager\metrics.py
phantom_pipeline/position_manager/models.py                            -> C:\phantom\phantom_pipeline\position_manager\models.py
phantom_pipeline/position_manager/state_store.py                       -> C:\phantom\phantom_pipeline\position_manager\state_store.py
phantom_pipeline/research_desk/__init__.py                             -> C:\phantom\phantom_pipeline\research_desk\__init__.py
phantom_pipeline/research_desk/config.py                               -> C:\phantom\phantom_pipeline\research_desk\config.py
phantom_pipeline/research_desk/dashboard.py                            -> C:\phantom\phantom_pipeline\research_desk\dashboard.py
phantom_pipeline/research_desk/debate.py                               -> C:\phantom\phantom_pipeline\research_desk\debate.py
phantom_pipeline/research_desk/explainable.py                          -> C:\phantom\phantom_pipeline\research_desk\explainable.py
phantom_pipeline/research_desk/institutional_review.py                 -> C:\phantom\phantom_pipeline\research_desk\institutional_review.py
phantom_pipeline/research_desk/logging_sink.py                         -> C:\phantom\phantom_pipeline\research_desk\logging_sink.py
phantom_pipeline/research_desk/market_research.py                      -> C:\phantom\phantom_pipeline\research_desk\market_research.py
phantom_pipeline/research_desk/metrics.py                              -> C:\phantom\phantom_pipeline\research_desk\metrics.py
phantom_pipeline/research_desk/models.py                               -> C:\phantom\phantom_pipeline\research_desk\models.py
phantom_pipeline/research_desk/strategy_research.py                    -> C:\phantom\phantom_pipeline\research_desk\strategy_research.py
phantom_pipeline/research_desk/trade_journal.py                        -> C:\phantom\phantom_pipeline\research_desk\trade_journal.py
phantom_pipeline/research_desk/trade_thesis.py                         -> C:\phantom\phantom_pipeline\research_desk\trade_thesis.py
phantom_pipeline/risk_engine/__init__.py                               -> C:\phantom\phantom_pipeline\risk_engine\__init__.py
phantom_pipeline/risk_engine/config.py                                 -> C:\phantom\phantom_pipeline\risk_engine\config.py
phantom_pipeline/risk_engine/constraints.py                            -> C:\phantom\phantom_pipeline\risk_engine\constraints.py
phantom_pipeline/risk_engine/engine.py                                 -> C:\phantom\phantom_pipeline\risk_engine\engine.py
phantom_pipeline/risk_engine/logging_sink.py                           -> C:\phantom\phantom_pipeline\risk_engine\logging_sink.py
phantom_pipeline/risk_engine/metrics.py                                -> C:\phantom\phantom_pipeline\risk_engine\metrics.py
phantom_pipeline/risk_engine/models.py                                 -> C:\phantom\phantom_pipeline\risk_engine\models.py
phantom_pipeline/scanner/__init__.py                                   -> C:\phantom\phantom_pipeline\scanner\__init__.py
phantom_pipeline/scanner/composite.py                                  -> C:\phantom\phantom_pipeline\scanner\composite.py
phantom_pipeline/scanner/config.py                                     -> C:\phantom\phantom_pipeline\scanner\config.py
phantom_pipeline/scanner/logging_sink.py                               -> C:\phantom\phantom_pipeline\scanner\logging_sink.py
phantom_pipeline/scanner/metrics.py                                    -> C:\phantom\phantom_pipeline\scanner\metrics.py
phantom_pipeline/scanner/models.py                                     -> C:\phantom\phantom_pipeline\scanner\models.py
phantom_pipeline/scanner/quality.py                                    -> C:\phantom\phantom_pipeline\scanner\quality.py
phantom_pipeline/scanner/scanner.py                                    -> C:\phantom\phantom_pipeline\scanner\scanner.py
phantom_pipeline/scanner/session.py                                    -> C:\phantom\phantom_pipeline\scanner\session.py
phantom_pipeline/scanner/structure.py                                  -> C:\phantom\phantom_pipeline\scanner\structure.py
phantom_pipeline/scanner/swing.py                                      -> C:\phantom\phantom_pipeline\scanner\swing.py
phantom_pipeline/scanner/trend.py                                      -> C:\phantom\phantom_pipeline\scanner\trend.py
phantom_pipeline/scanner/volatility.py                                 -> C:\phantom\phantom_pipeline\scanner\volatility.py
phantom_pipeline/scoring_engine/__init__.py                            -> C:\phantom\phantom_pipeline\scoring_engine\__init__.py
phantom_pipeline/scoring_engine/config.py                              -> C:\phantom\phantom_pipeline\scoring_engine\config.py
phantom_pipeline/scoring_engine/engine.py                              -> C:\phantom\phantom_pipeline\scoring_engine\engine.py
phantom_pipeline/scoring_engine/logging_sink.py                        -> C:\phantom\phantom_pipeline\scoring_engine\logging_sink.py
phantom_pipeline/scoring_engine/metrics.py                             -> C:\phantom\phantom_pipeline\scoring_engine\metrics.py
phantom_pipeline/scoring_engine/models.py                              -> C:\phantom\phantom_pipeline\scoring_engine\models.py
phantom_pipeline/scoring_engine/ranking.py                             -> C:\phantom\phantom_pipeline\scoring_engine\ranking.py
phantom_pipeline/scoring_engine/registry.py                            -> C:\phantom\phantom_pipeline\scoring_engine\registry.py
phantom_pipeline/scoring_engine/rule.py                                -> C:\phantom\phantom_pipeline\scoring_engine\rule.py
phantom_pipeline/scoring_engine/rules/__init__.py                      -> C:\phantom\phantom_pipeline\scoring_engine\rules\__init__.py
phantom_pipeline/scoring_engine/rules/directional_clarity.py           -> C:\phantom\phantom_pipeline\scoring_engine\rules\directional_clarity.py
phantom_pipeline/scoring_engine/rules/evidence_count.py                -> C:\phantom\phantom_pipeline\scoring_engine\rules\evidence_count.py
phantom_pipeline/scoring_engine/rules/reason_code_presence.py          -> C:\phantom\phantom_pipeline\scoring_engine\rules\reason_code_presence.py
phantom_pipeline/scoring_engine/rules/supporting_observation_count.py  -> C:\phantom\phantom_pipeline\scoring_engine\rules\supporting_observation_count.py
phantom_pipeline/strategy_engine/__init__.py                           -> C:\phantom\phantom_pipeline\strategy_engine\__init__.py
phantom_pipeline/strategy_engine/config.py                             -> C:\phantom\phantom_pipeline\strategy_engine\config.py
phantom_pipeline/strategy_engine/engine.py                             -> C:\phantom\phantom_pipeline\strategy_engine\engine.py
phantom_pipeline/strategy_engine/logging_sink.py                       -> C:\phantom\phantom_pipeline\strategy_engine\logging_sink.py
phantom_pipeline/strategy_engine/metrics.py                            -> C:\phantom\phantom_pipeline\strategy_engine\metrics.py
phantom_pipeline/strategy_engine/models.py                             -> C:\phantom\phantom_pipeline\strategy_engine\models.py
phantom_pipeline/strategy_engine/playbook.py                           -> C:\phantom\phantom_pipeline\strategy_engine\playbook.py
phantom_pipeline/strategy_engine/playbooks/__init__.py                 -> C:\phantom\phantom_pipeline\strategy_engine\playbooks\__init__.py
phantom_pipeline/strategy_engine/playbooks/liquidity_reversal.py       -> C:\phantom\phantom_pipeline\strategy_engine\playbooks\liquidity_reversal.py
phantom_pipeline/strategy_engine/playbooks/orb.py                      -> C:\phantom\phantom_pipeline\strategy_engine\playbooks\orb.py
phantom_pipeline/strategy_engine/playbooks/range_reversal.py           -> C:\phantom\phantom_pipeline\strategy_engine\playbooks\range_reversal.py
phantom_pipeline/strategy_engine/playbooks/session_breakout.py         -> C:\phantom\phantom_pipeline\strategy_engine\playbooks\session_breakout.py
phantom_pipeline/strategy_engine/playbooks/trend_continuation.py       -> C:\phantom\phantom_pipeline\strategy_engine\playbooks\trend_continuation.py
phantom_pipeline/strategy_engine/registry.py                           -> C:\phantom\phantom_pipeline\strategy_engine\registry.py
phantom_pipeline/watchdog/__init__.py                                  -> C:\phantom\phantom_pipeline\watchdog\__init__.py
phantom_pipeline/watchdog/alerting.py                                  -> C:\phantom\phantom_pipeline\watchdog\alerting.py
phantom_pipeline/watchdog/checks.py                                    -> C:\phantom\phantom_pipeline\watchdog\checks.py
phantom_pipeline/watchdog/config.py                                    -> C:\phantom\phantom_pipeline\watchdog\config.py
phantom_pipeline/watchdog/engine.py                                    -> C:\phantom\phantom_pipeline\watchdog\engine.py
phantom_pipeline/watchdog/logging_sink.py                              -> C:\phantom\phantom_pipeline\watchdog\logging_sink.py
phantom_pipeline/watchdog/metrics.py                                   -> C:\phantom\phantom_pipeline\watchdog\metrics.py
phantom_pipeline/watchdog/models.py                                    -> C:\phantom\phantom_pipeline\watchdog\models.py
phantom_pipeline/watchdog/real_recovery_executor.py                    -> C:\phantom\phantom_pipeline\watchdog\real_recovery_executor.py
phantom_pipeline/watchdog/recovery_executor.py                         -> C:\phantom\phantom_pipeline\watchdog\recovery_executor.py
phantom_pipeline/watchdog/state_store.py                               -> C:\phantom\phantom_pipeline\watchdog\state_store.py
phantom_pipeline/watchdog/trace.py                                     -> C:\phantom\phantom_pipeline\watchdog\trace.py
requirements.txt                                                       -> C:\phantom\requirements.txt
scripts/start_phantom.bat                                              -> C:\phantom\scripts\start_phantom.bat
scripts/start_phantom.py                                               -> C:\phantom\scripts\start_phantom.py
scripts/stop_phantom.bat                                               -> C:\phantom\scripts\stop_phantom.bat
```

## Important notes

- **`config/*.env.template` destinations are templates, not live config.**
  Copy each to `C:\phantom\config\<profile>.env` and fill in real values
  on the VPS — never overwrite an existing `C:\phantom\config\*.env` with
  a template (per `COPY_TO_VPS.md` §3).
- **`phantom_pipeline/` is a full-directory replace**, not a file-by-file
  merge: per `COPY_TO_VPS.md` §3, delete `C:\phantom\phantom_pipeline\`
  entirely and copy this package's `phantom_pipeline/` over it, only
  after the step-2 backup is confirmed.
- Total files mapped above: 182 (matches `DEPLOYMENT_AUDIT.md`'s count).
