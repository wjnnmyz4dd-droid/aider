"""Phase 3A - boundary validation (static, whole-system).

Confirms across the strategy engine, the filesystem bridge and the MT5 execution
adapter: no networking, no broker APIs outside MT5, no AI/ML, no strategy
execution inside the EA, and no duplicated core logic (single source of truth).
"""

from __future__ import annotations

from pathlib import Path

PKG = Path(__file__).resolve().parents[2]          # forex_swing_orb/
ENGINE = PKG / "run_dir" / "code"
BRIDGE = PKG / "bridge"
EA = PKG / "ea_mt5"


def _py(*dirs):
    out = []
    for d in dirs:
        out += [p for p in d.rglob("*.py") if "tests" not in p.parts]
    return out


def _mql(d):
    return list(d.glob("*.mq5")) + list(d.glob("*.mqh"))


# -- no networking anywhere in production sources ---------------------------
NET_TOKENS = ("WebRequest(", "SocketCreate(", "SocketConnect(", "SocketSend(",
              "SocketRead(", "SocketTlsHandshake(", "SendFTP(", "SendMail(",
              "InternetOpen", "wininet", "://", "import socket", "socket.socket",
              "import requests", "requests.get", "requests.post", "urllib",
              "http.client", "httpx", "aiohttp", "websocket")


def test_no_networking_whole_system():
    srcs = _py(ENGINE, BRIDGE, EA) + _mql(EA)
    for src in srcs:
        text = src.read_text()
        for tok in NET_TOKENS:
            assert tok not in text, f"{src.relative_to(PKG)} contains net token '{tok}'"


def test_no_localhost_or_rest_endpoints():
    # concrete endpoint tokens only (prose like "no REST/RPC" is allowed)
    for src in _py(ENGINE, BRIDGE, EA) + _mql(EA):
        low = src.read_text().lower()
        for tok in ("localhost", "127.0.0.1", "0.0.0.0", "http://", "https://"):
            assert tok not in low, f"{src.relative_to(PKG)} references '{tok}'"


# -- no AI / ML / LLM anywhere ---------------------------------------------
AI_TOKENS = ("import torch", "tensorflow", "import sklearn", "from sklearn",
             "openai", "anthropic", "transformers", "llama", "gpt-", "predict(",
             "model.fit(", "keras", "xgboost", "lightgbm", "embedding(")


def test_no_ai_ml_llm():
    for src in _py(ENGINE, BRIDGE, EA) + _mql(EA):
        low = src.read_text().lower()
        for tok in AI_TOKENS:
            assert tok.lower() not in low, f"{src.relative_to(PKG)} contains AI token '{tok}'"


# -- no strategy execution / broker-SDK inside the EA ----------------------
EA_STRATEGY_TOKENS = ("iMA(", "iRSI(", "iATR(", "iStochastic(", "iCustom(",
                      "iBands(", "iMACD(", "CopyRates(", "CopyBuffer(",
                      "CopyTicks(", "iClose(", "iHigh(", "iLow(", "iOpen(",
                      "iBars(", "IndicatorCreate(")


def test_ea_has_no_strategy_or_indicator_apis():
    for src in _mql(EA):
        text = src.read_text()
        for tok in EA_STRATEGY_TOKENS:
            assert tok not in text, f"{src.name} uses strategy/indicator API '{tok}'"


def test_ea_uses_only_mt5_broker_api():
    """No non-MT5 broker SDK tokens leak into the EA."""
    foreign = ("fix.", "FIX4", "cTrader", "Interactive Brokers", "ib_insync",
               "oanda", "binance", "ccxt", "alpaca")
    for src in _mql(EA) + _py(EA):
        low = src.read_text().lower()
        for tok in foreign:
            assert tok.lower() not in low, f"{src.name} references foreign broker '{tok}'"


def test_ea_has_no_external_process_execution():
    for src in _mql(EA):
        low = src.read_text().lower()
        for tok in ("shellexecute", "python", "system(", "wine", "popen"):
            assert tok not in low, f"{src.name} shells out via '{tok}'"


# -- no duplicated core logic (single source of truth) ---------------------
def _count_defs(pattern, *dirs):
    import re
    rx = re.compile(pattern, re.MULTILINE)
    total = 0
    for src in _py(*dirs):
        total += len(rx.findall(src.read_text()))
    return total


def test_single_serializer_validator_resolver():
    # exactly one canonical serializer, one integrity digest, one deterministic
    # result_id, one transport validator, one dedup resolver in the whole system
    assert _count_defs(r"^def canonical_json\b", BRIDGE) == 1
    assert _count_defs(r"^def compute_integrity_digest\b", BRIDGE) == 1
    assert _count_defs(r"^def result_id\b", BRIDGE) == 1
    assert _count_defs(r"^def validate_record\b", BRIDGE) == 1
    assert _count_defs(r"^class SeenResolver\b", BRIDGE) == 1
    # the adapter reuses them - it defines none of its own
    assert _count_defs(r"^def canonical_json\b", EA) == 0
    assert _count_defs(r"^def validate_record\b", EA) == 0
    assert _count_defs(r"^class SeenResolver\b", EA) == 0


def test_adapter_reuses_bridge_not_reimplements():
    """The reference execution consumer imports the bridge's single components."""
    txt = (EA / "execution_consumer.py").read_text()
    assert "from ..bridge" in txt
    assert "from ..bridge.consumer import Consumer" in txt
    # it does not define a parallel Consumer/validator/serializer
    assert "def canonical_json" not in txt
    assert "class Consumer" not in txt
