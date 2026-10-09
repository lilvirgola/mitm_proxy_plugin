import threading

from mitm_proxy_plugin.core.counter import atomic_increment


def test_atomic_increment_sequential(tmp_path):
    counter = tmp_path / "counter"
    lock = tmp_path / "counter.lock"

    assert atomic_increment(counter, lock) == 1
    assert atomic_increment(counter, lock) == 2
    assert atomic_increment(counter, lock) == 3


def test_atomic_increment_concurrent(tmp_path):
    counter = tmp_path / "counter"
    lock = tmp_path / "counter.lock"
    results = []

    def worker():
        value = atomic_increment(counter, lock)
        results.append(value)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == list(range(1, 21))
    assert int(counter.read_text()) == 20