"""Auto-discovered playbook package (ADR-003 §7).

`registry.discover_playbook_classes()` import-scans every module in this
package for concrete `Playbook` subclasses — nothing here is imported or
listed explicitly by the engine itself.
"""
