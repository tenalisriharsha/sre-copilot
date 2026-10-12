"""Bounded in-memory state for per-alert pipeline data.

The pipeline keeps a little state per alert fingerprint (runbook hits, stage
results, which deliveries were already handled). A long-running pod sees an
unbounded stream of fingerprints, so every such map must forget old entries.
``BoundedTTLMap`` evicts entries older than a TTL and, past a maximum size,
the least recently written ones.
"""

import time
from collections import OrderedDict
from collections.abc import Callable


class BoundedTTLMap[K, V]:
    """A dict-like map with a per-entry TTL and a hard size cap.

    Entries expire ``ttl_seconds`` after they were last written. Writing a
    key refreshes its TTL and moves it to the newest position; when the map
    holds more than ``max_entries`` the oldest entries are dropped. Because
    every entry has the same TTL, insertion order is also expiry order, so
    pruning only ever looks at the oldest end.
    """

    def __init__(
        self,
        max_entries: int,
        ttl_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._clock = clock
        self._data: OrderedDict[K, tuple[float, V]] = OrderedDict()

    def set(self, key: K, value: V) -> None:
        """Insert or replace ``key``, refreshing its TTL."""
        self._data.pop(key, None)
        self._data[key] = (self._clock() + self._ttl, value)
        self._prune()

    def get(self, key: K, default: V | None = None) -> V | None:
        """Return the live value for ``key``, or ``default`` if absent/expired."""
        self._prune()
        entry = self._data.get(key)
        return default if entry is None else entry[1]

    def __contains__(self, key: object) -> bool:
        self._prune()
        return key in self._data

    def __len__(self) -> int:
        self._prune()
        return len(self._data)

    def _prune(self) -> None:
        now = self._clock()
        while self._data:
            oldest_key, (expires_at, _) = next(iter(self._data.items()))
            if expires_at > now:
                break
            del self._data[oldest_key]
        while len(self._data) > self._max_entries:
            self._data.popitem(last=False)
