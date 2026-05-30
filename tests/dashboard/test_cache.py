from dashboard.cache import Cache


def test_computes_once():
    calls = []
    cache = Cache()

    def fn():
        calls.append(1)
        return 42

    assert cache.get_or_compute("k", fn) == 42
    assert cache.get_or_compute("k", fn) == 42
    assert len(calls) == 1  # fn appelé une seule fois


def test_distinct_keys():
    cache = Cache()
    assert cache.get_or_compute("a", lambda: 1) == 1
    assert cache.get_or_compute("b", lambda: 2) == 2
