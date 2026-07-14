"""Maps each provider's own free-text category/impact strings onto the
existing, unmodified `titan_protocol.market_intelligence.models.NewsCategory`/
`NewsImpact` enums (ADR-033 SS4.3). An unmapped/unrecognized value fails
safe to `NewsCategory.OTHER`/`NewsImpact.HIGH` -- HIGH, not LOW, because
an unclassifiable impact must be treated as the more cautious case,
never silently assumed harmless."""

from __future__ import annotations

from titan_protocol.market_intelligence.models import NewsCategory, NewsImpact

_CATEGORY_MAP = {
    "central bank": NewsCategory.CENTRAL_BANK,
    "interest rate decision": NewsCategory.INTEREST_RATE_DECISION,
    "cpi": NewsCategory.CPI,
    "consumer price index": NewsCategory.CPI,
    "ppi": NewsCategory.PPI,
    "producer price index": NewsCategory.PPI,
    "nonfarm payrolls": NewsCategory.NFP,
    "nfp": NewsCategory.NFP,
    "gdp": NewsCategory.GDP,
    "gross domestic product": NewsCategory.GDP,
    "pmi": NewsCategory.PMI,
    "purchasing managers index": NewsCategory.PMI,
    "employment": NewsCategory.EMPLOYMENT,
    "unemployment rate": NewsCategory.EMPLOYMENT,
    "retail sales": NewsCategory.RETAIL_SALES,
    "inflation": NewsCategory.INFLATION,
    "fomc": NewsCategory.FOMC,
    "federal open market committee": NewsCategory.FOMC,
    "ecb": NewsCategory.ECB,
    "european central bank": NewsCategory.ECB,
    "boe": NewsCategory.BOE,
    "bank of england": NewsCategory.BOE,
    "boj": NewsCategory.BOJ,
    "bank of japan": NewsCategory.BOJ,
    "rba": NewsCategory.RBA,
    "reserve bank of australia": NewsCategory.RBA,
    "rbnz": NewsCategory.RBNZ,
    "reserve bank of new zealand": NewsCategory.RBNZ,
    "boc": NewsCategory.BOC,
    "bank of canada": NewsCategory.BOC,
    "snb": NewsCategory.SNB,
    "swiss national bank": NewsCategory.SNB,
}

_IMPACT_MAP = {
    "low": NewsImpact.LOW,
    "medium": NewsImpact.MEDIUM,
    "moderate": NewsImpact.MEDIUM,
    "high": NewsImpact.HIGH,
}


def map_category(raw_category: str) -> NewsCategory:
    return _CATEGORY_MAP.get(raw_category.strip().lower(), NewsCategory.OTHER)


def map_impact(raw_impact: str) -> NewsImpact:
    return _IMPACT_MAP.get(raw_impact.strip().lower(), NewsImpact.HIGH)


__all__ = ["map_category", "map_impact"]
