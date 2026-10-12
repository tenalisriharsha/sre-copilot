import pytest

from sre_copilot.state import BoundedTTLMap


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_get_returns_value_before_ttl():
    clock = FakeClock()
    store: BoundedTTLMap[str, int] = BoundedTTLMap(max_entries=10, ttl_seconds=60, clock=clock)
    store.set("a", 1)
    clock.now += 59
    assert store.get("a") == 1
    assert "a" in store


def test_entries_expire_after_ttl():
    clock = FakeClock()
    store: BoundedTTLMap[str, int] = BoundedTTLMap(max_entries=10, ttl_seconds=60, clock=clock)
    store.set("old", 1)
    clock.now += 30
    store.set("new", 2)
    clock.now += 30  # "old" is now exactly 60s old
    assert store.get("old") is None
    assert "old" not in store
    assert store.get("new") == 2
    assert len(store) == 1
    clock.now += 30
    assert len(store) == 0


def test_rewrite_refreshes_ttl():
    clock = FakeClock()
    store: BoundedTTLMap[str, int] = BoundedTTLMap(max_entries=10, ttl_seconds=60, clock=clock)
    store.set("a", 1)
    clock.now += 50
    store.set("a", 2)
    clock.now += 50
    assert store.get("a") == 2


def test_max_entries_evicts_oldest_first():
    store: BoundedTTLMap[int, int] = BoundedTTLMap(max_entries=3, ttl_seconds=3600)
    for i in range(5):
        store.set(i, i)
    assert len(store) == 3
    assert 0 not in store and 1 not in store
    assert [store.get(i) for i in (2, 3, 4)] == [2, 3, 4]


def test_size_stays_bounded_under_a_stream_of_unique_keys():
    store: BoundedTTLMap[str, int] = BoundedTTLMap(max_entries=100, ttl_seconds=3600)
    for i in range(10_000):
        store.set(f"fp-{i}", i)
    assert len(store) == 100
    assert store.get("fp-9999") == 9999
    assert store.get("fp-0") is None


def test_rewrite_moves_key_to_newest_position():
    store: BoundedTTLMap[str, int] = BoundedTTLMap(max_entries=2, ttl_seconds=3600)
    store.set("a", 1)
    store.set("b", 2)
    store.set("a", 3)
    store.set("c", 4)  # evicts "b", the least recently written
    assert "b" not in store
    assert store.get("a") == 3
    assert store.get("c") == 4


@pytest.mark.parametrize("kwargs", [{"max_entries": 0}, {"ttl_seconds": 0}])
def test_rejects_non_positive_bounds(kwargs):
    params = {"max_entries": 1, "ttl_seconds": 1.0} | kwargs
    with pytest.raises(ValueError):
        BoundedTTLMap(**params)
