"""Disk-backed parquet cache with per-key TTL."""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

CACHE_DIR = Path("data/cache")


def _cache_path(key: str) -> Path:
    safe = key.replace("/", "_").replace(" ", "_")
    return CACHE_DIR / f"{safe}.parquet"


def cached(key: str, fetch_fn, ttl_hours: float = 6.0) -> pd.DataFrame:
    """Return cached DataFrame if fresh, otherwise fetch, cache, and return."""
    path = _cache_path(key)
    if path.exists():
        age = (time.time() - path.stat().st_mtime) / 3600
        if age < ttl_hours:
            return pd.read_parquet(path)
    df = fetch_fn()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return df
