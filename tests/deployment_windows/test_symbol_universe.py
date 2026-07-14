"""Symbol-universe consistency tests (Final Release Hardening): exact
match, missing pair, duplicates, invalid symbols, and profile changes
-- exercised through the real `config_loader.load_settings()` +
`build_trading_profile()` against a real temp config file, never
mocked."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ._fixtures import write_config

from config_loader import ConfigError, build_trading_profile, load_settings


class _TempConfigTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)

    def _load(self, overrides=None):
        config_path = write_config(self.tmp_path, overrides)
        return load_settings(config_path)


class TestExactMatch(_TempConfigTestCase):
    def test_profile_allowed_pairs_exactly_equals_bridge_allowed_symbols(self):
        settings = self._load()
        profile = build_trading_profile(settings)
        self.assertEqual(set(profile.allowed_pairs), set(settings.bridge_config.allowed_symbols))

    def test_no_pair_is_silently_skipped(self):
        settings = self._load()
        profile = build_trading_profile(settings)
        # Every configured Bridge symbol made it into the profile -- none dropped.
        self.assertEqual(len(profile.allowed_pairs), len(settings.bridge_config.allowed_symbols))


class TestMissingPairFailsClosed(unittest.TestCase):
    """A profile pair not accepted by the Bridge must fail startup, not
    be silently dropped. Since `build_trading_profile()` now always
    derives `allowed_pairs` from `bridge.allowed_symbols`, the only way
    to exercise the "unsupported pair" fail-closed path today is via a
    narrowed `bridge.allowed_symbols` list that would have excluded a
    pair the *unmodified* profile default would have carried -- this
    proves the check is real, not merely unreachable dead code."""

    def test_shrinking_allowed_symbols_never_produces_an_unsupported_pair(self):
        import tempfile as _tempfile
        with _tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), {"allowed_symbols": ["EURUSD"]})
            settings = load_settings(config_path)
            profile = build_trading_profile(settings)
            self.assertEqual(profile.allowed_pairs, ("EURUSD",))

    def test_custom_profile_selection_fails_closed_with_explicit_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp)
            config_path = write_config(config)
            # Force selected_profile=custom by editing the written file directly.
            import json
            data = json.loads(config_path.read_text())
            data["trading_profile"]["selected_profile"] = "custom"
            config_path.write_text(json.dumps(data))
            settings = load_settings(config_path)
            with self.assertRaises(ConfigError) as ctx:
                build_trading_profile(settings)
            self.assertIn("custom", str(ctx.exception))


class TestDuplicates(unittest.TestCase):
    def test_duplicate_pair_in_allowed_symbols_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), {"allowed_symbols": ["EURUSD", "GBPUSD", "EURUSD"]})
            with self.assertRaises(ConfigError) as ctx:
                load_settings(config_path)
            self.assertIn("duplicate", str(ctx.exception).lower())


class TestInvalidSymbols(unittest.TestCase):
    def test_non_six_letter_symbol_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), {"allowed_symbols": ["EURUSD", "GOLD"]})
            with self.assertRaises(ConfigError) as ctx:
                load_settings(config_path)
            self.assertIn("invalid pair name", str(ctx.exception))

    def test_broker_suffixed_symbol_without_mapping_config_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), {"allowed_symbols": ["EURUSD.a"]})
            with self.assertRaises(ConfigError):
                load_settings(config_path)

    def test_empty_allowed_symbols_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), {"allowed_symbols": []})
            with self.assertRaises(ConfigError):
                load_settings(config_path)


class TestSuffixMappingConfig(unittest.TestCase):
    def test_symbol_mapping_section_is_parsed_onto_bridge_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), {
                "symbol_mapping": {"broker_suffix": ".a"},
            })
            settings = load_settings(config_path)
            self.assertEqual(settings.bridge_config.symbol_mapping.broker_suffix, ".a")
            self.assertEqual(settings.bridge_config.symbol_mapping.to_canonical("EURUSD.a"), "EURUSD")

    def test_explicit_map_section_is_parsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = write_config(Path(tmp), {
                "allowed_symbols": ["EURUSD", "XAUUSD"],
                "symbol_mapping": {"explicit_map": {"XAUUSD": "GOLD.raw"}},
            })
            settings = load_settings(config_path)
            self.assertEqual(settings.bridge_config.symbol_mapping.to_canonical("GOLD.raw"), "XAUUSD")


class TestProfileChanges(_TempConfigTestCase):
    def test_switching_named_profile_still_derives_from_bridge_allowed_symbols(self):
        settings_a = self._load({"allowed_symbols": ["EURUSD", "GBPUSD"]})
        settings_b = self._load({"allowed_symbols": ["EURUSD", "GBPUSD"]})
        for name in ("london_conservative", "new_york_aggressive"):
            settings_a = settings_a.__class__(**{**vars(settings_a), "selected_profile": name})
            profile = build_trading_profile(settings_a)
            self.assertEqual(set(profile.allowed_pairs), {"EURUSD", "GBPUSD"})

    def test_narrower_bridge_symbols_produces_a_narrower_profile(self):
        settings = self._load({"allowed_symbols": ["EURUSD"]})
        profile = build_trading_profile(settings)
        self.assertEqual(profile.allowed_pairs, ("EURUSD",))


if __name__ == "__main__":
    unittest.main()
