"""Session Edge — Phase 3A end-to-end system validation.

Validation and test harness ONLY. No production features, no strategy logic, no
bridge/EA behaviour changes. This package drives the accepted components
(strategy engine -> filesystem bridge -> execution adapter -> mock MT5) through
deterministic scenarios, failure injection, restart recovery, load, determinism
and boundary checks, and produces the validation report.

Failure injection is performed with test-time monkeypatching of the standard
library and component seams; it never modifies production code.
"""
