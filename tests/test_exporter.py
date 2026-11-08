import logging
from types import SimpleNamespace

import pytest
import requests
from prometheus_client import REGISTRY

import exporter

HOST = exporter.HOST
BASE = "/PowerEquipment/RackPDUs/1"


def http_error(status: int) -> requests.HTTPError:
    return requests.HTTPError(str(status), response=SimpleNamespace(status_code=status))


def circuit(cid: str, **extra) -> dict:
    body = {"Id": cid, "UserLabel": f"lbl-{cid}", "Status": {"Health": "OK"}}
    body.update(extra)
    return body


PDU_LIST = {"Members": [{"@odata.id": f"/redfish/v1{BASE}"}]}
MAINS = circuit("Mains", Voltage={"Reading": 100.5})
BRANCH = circuit("Branch0", CurrentAmps={"Reading": 1.25})
OUTLET = circuit("Outlet0", PowerState="On", PowerWatts={"Reading": 42.0})


def coll(*member_paths: str) -> dict:
    return {"Members": [{"@odata.id": f"/redfish/v1{p}"} for p in member_paths]}


def cycle_responses() -> dict:
    return {
        "/PowerEquipment/RackPDUs": coll(BASE),
        f"{BASE}/Mains": coll(f"{BASE}/Mains/0"),
        f"{BASE}/Mains/0": MAINS,
        f"{BASE}/Branches": coll(f"{BASE}/Branches/0"),
        f"{BASE}/Branches/0": BRANCH,
        f"{BASE}/Outlets": coll(f"{BASE}/Outlets/0"),
        f"{BASE}/Outlets/0": OUTLET,
    }


@pytest.fixture
def stub_fetch(monkeypatch):
    """Replace exporter.fetch with a dict-backed stub.

    Returns a helper taking {path: body_or_exception}; the helper returns
    the list of fetched paths so tests can assert call order.
    """

    def _install(responses):
        seen = []

        def fake(path):
            seen.append(path)
            out = responses[path]
            if isinstance(out, Exception):
                raise out
            return out

        monkeypatch.setattr(exporter, "fetch", fake)
        return seen

    return _install


def counter(name: str, labels: dict) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


class TestScrapeOncePartialFailure:
    def test_continues_cycle_after_non_404(self, stub_fetch, caplog):
        responses = cycle_responses()
        responses[f"{BASE}/Branches"] = http_error(500)
        err_before = counter("raritan_scrape_attempts_total", {"host": HOST, "result": "error"})
        seen = stub_fetch(responses)

        with caplog.at_level(logging.INFO):
            exporter.scrape_once()

        assert f"{BASE}/Outlets" in seen
        assert (
            REGISTRY.get_sample_value(
                "raritan_power_watts",
                {"host": HOST, "circuit_type": "Outlets", "circuit_id": "Outlet0", "user_label": "lbl-Outlet0"},
            )
            == 42.0
        )
        assert REGISTRY.get_sample_value("raritan_scrape_success", {"host": HOST}) == 0.0
        assert counter("raritan_scrape_attempts_total", {"host": HOST, "result": "error"}) == err_before + 1

        summaries = [r for r in caplog.records if r.getMessage().startswith("scrape cycle done")]
        assert len(summaries) == 1
        msg = summaries[0].getMessage()
        assert "ok=2" in msg and "failed=1" in msg

    def test_404_is_skipped_not_failed(self, stub_fetch):
        responses = cycle_responses()
        responses[f"{BASE}/Branches"] = http_error(404)
        ok_before = counter("raritan_scrape_attempts_total", {"host": HOST, "result": "ok"})
        stub_fetch(responses)

        exporter.scrape_once()

        assert REGISTRY.get_sample_value("raritan_scrape_success", {"host": HOST}) == 1.0
        assert counter("raritan_scrape_attempts_total", {"host": HOST, "result": "ok"}) == ok_before + 1

    def test_listing_failure_marks_error(self, stub_fetch):
        stub_fetch({"/PowerEquipment/RackPDUs": requests.ConnectionError("boom")})

        exporter.scrape_once()

        assert REGISTRY.get_sample_value("raritan_scrape_success", {"host": HOST}) == 0.0
        assert REGISTRY.get_sample_value("raritan_scrape_duration_seconds", {"host": HOST}) >= 0.0


class TestScrapeCircuitTypes:
    def test_all_present(self, stub_fetch):
        stub_fetch(cycle_responses())
        assert exporter.scrape_circuit_types(BASE) == (3, 0, 0)

    def test_counts_404_as_skipped(self, stub_fetch):
        responses = cycle_responses()
        responses[f"{BASE}/Branches"] = http_error(404)
        stub_fetch(responses)
        assert exporter.scrape_circuit_types(BASE) == (2, 1, 0)

    def test_isolates_unexpected_errors(self, stub_fetch):
        responses = cycle_responses()
        responses[f"{BASE}/Branches"] = KeyError("@odata.id")
        stub_fetch(responses)
        assert exporter.scrape_circuit_types(BASE) == (2, 0, 1)


def test_members_strips_prefix():
    c = coll("/Foo", "/Bar")
    assert list(exporter.members(c)) == ["/Foo", "/Bar"]
