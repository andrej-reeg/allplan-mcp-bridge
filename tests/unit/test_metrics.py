"""Tests for per-tool call metrics."""



from allplan_mcp_server.metrics import Metrics


def test_record_increments_counts() -> None:
    m = Metrics()
    m.record_call("create_wall", 100.0, error=False)
    m.record_call("create_wall", 200.0, error=True)
    m.record_call("create_wall", 150.0, error=False)
    s = m.summary()
    assert s["create_wall"]["calls"] == 3
    assert s["create_wall"]["errors"] == 1


def test_separate_tools_independent() -> None:
    m = Metrics()
    m.record_call("create_wall", 10.0, error=False)
    m.record_call("ping", 1.0, error=False)
    s = m.summary()
    assert s["create_wall"]["calls"] == 1
    assert s["ping"]["calls"] == 1


def test_percentiles_single_sample() -> None:
    m = Metrics()
    m.record_call("ping", 42.0, error=False)
    p = m.summary()["ping"]
    assert p["p50_ms"] == 42.0
    assert p["p95_ms"] == 42.0
    assert p["p99_ms"] == 42.0


def test_percentiles_empty() -> None:
    m = Metrics()
    # Access stats before any calls: summary returns empty dict
    assert m.summary() == {}


def test_percentiles_monotone_ordering() -> None:
    m = Metrics()
    for i in range(100):
        m.record_call("t", float(i), error=False)
    p = m.summary()["t"]
    assert p["p50_ms"] <= p["p95_ms"] <= p["p99_ms"]


def test_rolling_window_capped_at_1000() -> None:
    m = Metrics()
    # First 1000 samples: all 1.0
    for _ in range(1000):
        m.record_call("t", 1.0, error=False)
    # Next 500 samples: all 9999.0 — should evict the earliest 500
    for _ in range(500):
        m.record_call("t", 9999.0, error=False)
    # call_count reflects all 1500 calls
    assert m.summary()["t"]["calls"] == 1500
    # p99 should reflect the new high values (9999.0), not the old ones
    assert m.summary()["t"]["p99_ms"] == 9999.0


def test_p50_is_median() -> None:
    m = Metrics()
    # 10 values: 1..10 — median should be around 5
    for v in range(1, 11):
        m.record_call("t", float(v), error=False)
    p50 = m.summary()["t"]["p50_ms"]
    # nearest-rank p50 of [1..10] is index ceil(0.5*10)-1 = 4 → value 5
    assert p50 == 5.0


def test_thread_safety_concurrent_writes() -> None:
    import threading

    m = Metrics()
    errors: list[Exception] = []

    def _worker() -> None:
        try:
            for _ in range(200):
                m.record_call("t", 1.0, error=False)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert m.summary()["t"]["calls"] == 2000
