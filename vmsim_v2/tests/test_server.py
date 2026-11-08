import json
import threading
import urllib.error
import urllib.request

import pytest

from vmsim import Config, experiments, simulate, workloads
from vmsim.server import make_server

REFS = [[p, i % 3 == 0] for i, p in enumerate(workloads.TEXTBOOK)]


@pytest.fixture
def base():
    srv = make_server("127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def call(base, path, body=None, method=None):
    req = urllib.request.Request(base + path, method=method or ("POST" if body is not None else "GET"),
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return r.status, dict(r.headers), (json.loads(r.read() or b"{}"))


def test_health_and_cors(base):
    status, headers, body = call(base, "/api/health")
    assert status == 200 and body["ok"] is True and "LRU" in body["policies"]
    assert headers["Access-Control-Allow-Origin"] == "*"


def test_preflight_allows_private_network(base):
    status, headers, _ = call(base, "/api/simulate", method="OPTIONS")
    assert status == 204 and headers["Access-Control-Allow-Private-Network"] == "true"


def test_simulate_matches_in_process_engine(base):
    _, _, body = call(base, "/api/simulate", {"refs": REFS, "frames": 3, "tlb": 2, "prefetch": 0})
    for name, res in body["results"].items():
        local = simulate([(p, bool(w)) for p, w in REFS], name, Config(frames=3, tlb_size=2))
        assert res["stats"]["faults"] == local.stats["faults"]
        assert [e["victim"] for e in res["events"]] == [e.victim for e in local.events]
        assert [e["dirty"] for e in res["events"]] == [list(e.dirty) for e in local.events]


def test_simulate_with_prefetch_reports_it(base):
    refs = [[i, False] for i in range(20)]
    _, _, body = call(base, "/api/simulate", {"refs": refs, "frames": 4, "prefetch": 1})
    s = body["results"]["FIFO"]["stats"]
    assert s["faults"] == 10 and s["prefetch_useful"] == 10


def test_sweep_matches_experiments(base):
    refs = [[p, False] for p in workloads.BELADY]
    _, _, body = call(base, "/api/sweep", {"refs": refs, "frames": [3, 4], "policies": ["FIFO", "LRU"]})
    assert body["faults"] == experiments.frames_sweep(workloads.BELADY, ["FIFO", "LRU"], [3, 4])
    assert body["faults"]["FIFO"] == [9, 10]


@pytest.mark.parametrize("path,body", [
    ("/api/simulate", {"refs": [], "frames": 3}),
    ("/api/simulate", {"refs": [[1, False]], "frames": 0}),
    ("/api/simulate", {"refs": [[-1, False]], "frames": 3}),
    ("/api/simulate", {"refs": "nope"}),
    ("/api/simulate", {"refs": [[1, False]], "frames": 3, "prefetch": 99}),
    ("/api/sweep", {"refs": [[1, False]], "frames": []}),
    ("/api/sweep", {"refs": [[1, False]], "frames": [3], "policies": ["??"]}),
])
def test_bad_input_is_400(base, path, body):
    with pytest.raises(urllib.error.HTTPError) as e:
        call(base, path, body)
    assert e.value.code == 400


def test_unknown_route_404(base):
    with pytest.raises(urllib.error.HTTPError) as e:
        call(base, "/api/nope")
    assert e.value.code == 404


def test_oversized_requests_are_refused_not_run(base):
    from vmsim.server import MAX_REFS, MAX_WORK
    refs = [[i % 50, False] for i in range(MAX_REFS)]
    with pytest.raises(urllib.error.HTTPError) as e:
        call(base, "/api/sweep", {"refs": refs, "frames": list(range(1, 10))})
    assert e.value.code == 400
    with pytest.raises(urllib.error.HTTPError) as e:
        call(base, "/api/simulate", {"refs": refs + [[1, False]], "frames": 4})
    assert e.value.code == 400
    assert MAX_WORK <= 100_000


def test_server_drops_stalled_connections():
    from vmsim.server import Handler
    assert Handler.timeout and Handler.timeout <= 10


def test_server_rejects_invalid_config_values_with_400(base):
    for body in ({"refs": [[1, False]], "frames": 3, "tlb": -1}, {"refs": [[1, False]], "frames": 3, "prefetch": -2}):
        with pytest.raises(urllib.error.HTTPError) as e:
            call(base, "/api/simulate", body)
        assert e.value.code == 400
