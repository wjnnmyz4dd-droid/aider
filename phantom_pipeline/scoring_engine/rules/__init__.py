"""Auto-discovered scoring rule package (ADR-004 §5, §15).

`registry.discover_rule_classes()` import-scans every module in this
package for concrete `ScoringRule` subclasses — nothing here is imported
or listed explicitly by the engine itself.
"""
