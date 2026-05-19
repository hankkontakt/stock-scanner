"""
data_fetcher_batch.py – Re-export stub.
Batch functions were merged back into data_fetcher.py to avoid circular imports.
This file exists only for backwards compatibility.
"""
from core.data_fetcher import (  # noqa: F401
    fetch_universe_data,
    fetch_sentiment_batch,
    fetch_prices_only,
    update_scored_with_prices,
    fetch_benchmark_performance,
    search_stocks,
)
