"""Unit tests for /score 'signal' parsing (phantom_institutional._parse_signal_direction).

Covers the required cases: BUY, SELL, 1, -1, numeric strings, invalid string,
null, missing field, and bool. Run under an env with flask+numpy available:

    python -m unittest tests.test_score_signal

Importing phantom_institutional writes a startup log to ~/Documents, so we
ensure that directory exists first (it exists on the target Windows VPS).
"""

import os
os.makedirs(os.path.join(os.path.expanduser("~"), "Documents"), exist_ok=True)

import unittest
import phantom_institutional as P

parse = P._parse_signal_direction


class TestSignalDirection(unittest.TestCase):
    # --- valid: numeric contract (what the scoring path enforces) ---
    def test_int_buy(self):
        self.assertEqual(parse(1), (1, None))

    def test_int_sell(self):
        self.assertEqual(parse(-1), (-1, None))

    def test_numeric_string_buy(self):
        self.assertEqual(parse("1"), (1, None))

    def test_numeric_string_sell(self):
        self.assertEqual(parse("-1"), (-1, None))

    def test_float(self):
        self.assertEqual(parse(1.0), (1, None))

    # --- valid: BUY/SELL words (defensive; not reachable through /score
    #     because score_trade coerces via int() upstream) ---
    def test_word_buy(self):
        self.assertEqual(parse("BUY"), (1, None))

    def test_word_sell(self):
        self.assertEqual(parse("SELL"), (-1, None))

    def test_word_buy_padded_lowercase(self):
        self.assertEqual(parse("  buy "), (1, None))

    # --- invalid: must report an error (endpoint returns HTTP 400) ---
    def test_invalid_string(self):
        d, e = parse("XYZ")
        self.assertIsNone(d)
        self.assertIsInstance(e, str)

    def test_null(self):
        d, e = parse(None)
        self.assertIsNone(d)
        self.assertIsInstance(e, str)

    def test_missing_field(self):
        # a missing key -> dict.get returns None -> same as null
        d, e = parse({}.get("signal"))
        self.assertIsNone(d)
        self.assertIsInstance(e, str)

    def test_bool_rejected(self):
        # JSON true/false must not be treated as int 1/0
        d, e = parse(True)
        self.assertIsNone(d)
        self.assertIsInstance(e, str)


if __name__ == "__main__":
    unittest.main()
