"""Current retrieval entry point for the offline assistant.

The active query path is the frozen R2 base SQLite retrieval contract plus the
R2.5 query-time fact-family gate. The SQLite file carries the R2.2 index
metadata; R2.5 does not rebuild or mutate that index and only evaluates its
additional admission gate at query time. Historical milestone modules remain
importable as frozen implementations, not application-facing dependencies.
"""

from __future__ import annotations

from .engine import query_index as _query_r2_5


def query_index(database, query, top_k, provider, retrieval):
    """Run the configured active retrieval pipeline without changing its contract."""
    return _query_r2_5(database, query, top_k, provider, retrieval)
