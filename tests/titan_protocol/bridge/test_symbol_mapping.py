"""Tests for `SymbolMapping` -- broker-native <-> canonical symbol
normalization (Final Release Hardening, symbol-universe consistency)."""

from __future__ import annotations

import unittest

from titan_protocol.bridge.symbol_mapping import SymbolMapping


class TestIdentityDefault(unittest.TestCase):
    def test_no_config_is_a_pure_identity_mapping(self):
        mapping = SymbolMapping()
        self.assertEqual(mapping.to_canonical("EURUSD"), "EURUSD")
        self.assertEqual(mapping.to_broker("EURUSD"), "EURUSD")


class TestSuffixMapping(unittest.TestCase):
    def test_suffix_stripped_to_canonical(self):
        mapping = SymbolMapping(broker_suffix=".a")
        self.assertEqual(mapping.to_canonical("EURUSD.a"), "EURUSD")

    def test_suffix_added_to_broker(self):
        mapping = SymbolMapping(broker_suffix=".a")
        self.assertEqual(mapping.to_broker("EURUSD"), "EURUSD.a")

    def test_symbol_without_the_suffix_passes_through_unchanged(self):
        mapping = SymbolMapping(broker_suffix=".a")
        self.assertEqual(mapping.to_canonical("EURUSD"), "EURUSD")


class TestPrefixMapping(unittest.TestCase):
    def test_prefix_stripped_to_canonical(self):
        mapping = SymbolMapping(broker_prefix="m.")
        self.assertEqual(mapping.to_canonical("m.EURUSD"), "EURUSD")

    def test_prefix_added_to_broker(self):
        mapping = SymbolMapping(broker_prefix="m.")
        self.assertEqual(mapping.to_broker("EURUSD"), "m.EURUSD")


class TestCombinedPrefixAndSuffix(unittest.TestCase):
    def test_both_applied_together(self):
        mapping = SymbolMapping(broker_prefix="m.", broker_suffix=".raw")
        self.assertEqual(mapping.to_canonical("m.EURUSD.raw"), "EURUSD")
        self.assertEqual(mapping.to_broker("EURUSD"), "m.EURUSD.raw")


class TestExplicitMapTakesPriority(unittest.TestCase):
    def test_explicit_entry_overrides_the_suffix_rule(self):
        mapping = SymbolMapping(broker_suffix=".a", explicit_map={"XAUUSD": "GOLD.a"})
        self.assertEqual(mapping.to_canonical("GOLD.a"), "XAUUSD")
        self.assertEqual(mapping.to_broker("XAUUSD"), "GOLD.a")
        # Unrelated pairs still go through the suffix rule.
        self.assertEqual(mapping.to_canonical("EURUSD.a"), "EURUSD")

    def test_explicit_map_is_defensively_copied(self):
        source = {"XAUUSD": "GOLD.a"}
        mapping = SymbolMapping(explicit_map=source)
        source["EURUSD"] = "EURUSD.x"
        self.assertNotIn("EURUSD", mapping.explicit_map)


if __name__ == "__main__":
    unittest.main()
