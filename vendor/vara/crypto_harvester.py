"""
Vara.CRYPTO — Cryptocurrency & Digital Assets Domain Harvester

Sources modelled (simulated; swap fetch() for live calls):
  - CoinGecko / CoinMarketCap (prices, market cap, dominance)
  - On-chain metrics (exchange flows, whale moves)
  - Protocol / DeFi news

Extends base_harvester.BaseDomainHarvester.
"""

from __future__ import annotations
from typing import List, Optional
from base_harvester import BaseDomainHarvester, HarvestedSignal


class CryptoHarvester(BaseDomainHarvester):
    PLANE = "crypto"

    DEFAULT_KEYWORDS = [
        "bitcoin", "ethereum", "crypto", "blockchain", "defi", "stablecoin",
        "exchange", "wallet", "token", "NFT", "layer 2", "L2", "rollup",
        "SEC", "regulation", "ETF", "halving", "mining", "hashrate",
    ]

    def fetch(self, keywords: List[str], sweep_hours: int) -> List[HarvestedSignal]:
        """
        Placeholder fetch. Replace with live CoinGecko / RSS / on-chain calls.
        Returns empty list so the pipeline stays safe when live sources are offline.
        """
        return []


def harvest_crypto(keywords: list, sweep_hours: int, **kwargs) -> list:
    h = CryptoHarvester()
    return h.harvest(keywords or CryptoHarvester.DEFAULT_KEYWORDS, sweep_hours)
