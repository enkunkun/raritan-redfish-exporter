#!/usr/bin/env python3
"""Raritan PDU Redfish exporter.

Polls /redfish/v1/PowerEquipment/RackPDUs/{id} and re-exposes the circuit and
outlet readings as Prometheus metrics on :9610/metrics.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from typing import Any, Iterable

import requests
import urllib3
from prometheus_client import Counter, Gauge, start_http_server

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HOST = os.environ["RARITAN_HOST"]
USER = os.environ["RARITAN_USER"]
PASS = os.environ["RARITAN_PASS"]
SCHEME = os.environ.get("RARITAN_SCHEME", "https")
PORT = int(os.environ.get("EXPORTER_PORT", "9610"))
SCRAPE_INTERVAL = int(os.environ.get("SCRAPE_INTERVAL", "60"))
HTTP_TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "10"))

BASE = f"{SCHEME}://{HOST}/redfish/v1"
LABELS = ["host", "circuit_type", "circuit_id", "user_label"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
log = logging.getLogger("raritan-exporter")

voltage = Gauge("raritan_voltage_volts", "Circuit voltage", LABELS)
current = Gauge("raritan_current_amps", "Circuit current", LABELS)
power_w = Gauge("raritan_power_watts", "Active power", LABELS)
apparent = Gauge("raritan_apparent_va", "Apparent power (VA)", LABELS)
pf = Gauge("raritan_power_factor", "Power factor", LABELS)
freq = Gauge("raritan_frequency_hz", "Frequency", LABELS)
energy = Gauge("raritan_energy_kwh", "Cumulative energy (kWh)", LABELS)
rated = Gauge("raritan_rated_current_amps", "Rated current", LABELS)
health = Gauge("raritan_circuit_health", "Health: 1=OK, 0=otherwise", LABELS)
outlet_on = Gauge("raritan_outlet_powered", "Outlet PowerState: 1=On", LABELS)
scrape_ok = Gauge("raritan_scrape_success", "1 if last scrape cycle succeeded", ["host"])
scrape_seconds = Gauge("raritan_scrape_duration_seconds", "Last scrape duration", ["host"])
scrape_total = Counter("raritan_scrape_attempts_total", "Total scrape attempts", ["host", "result"])

session = requests.Session()
session.auth = (USER, PASS)
session.verify = False
session.headers["Accept-Encoding"] = "gzip"


def fetch(path: str) -> dict[str, Any]:
    r = session.get(BASE + path, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return r.json()


def members(collection: dict[str, Any]) -> Iterable[str]:
    for m in collection.get("Members", []):
        yield m["@odata.id"].removeprefix("/redfish/v1")


def set_circuit(c: dict[str, Any], kind: str) -> None:
    lbl = (HOST, kind, c.get("Id", "?"), c.get("UserLabel", "") or "")

    def reading(node: dict | None, key: str = "Reading") -> float | None:
        if not isinstance(node, dict):
            return None
        v = node.get(key)
        return float(v) if isinstance(v, (int, float)) else None

    pairs = [
        (voltage, reading(c.get("Voltage"))),
        (current, reading(c.get("CurrentAmps"))),
        (power_w, reading(c.get("PowerWatts"))),
        (apparent, reading(c.get("PowerWatts"), "ApparentVA")),
        (pf, reading(c.get("PowerWatts"), "PowerFactor")),
        (freq, reading(c.get("FrequencyHz"))),
        (energy, reading(c.get("EnergykWh"))),
    ]
    rated_amps = c.get("RatedCurrentAmps")
    if isinstance(rated_amps, (int, float)):
        pairs.append((rated, float(rated_amps)))

    for metric, val in pairs:
        if val is not None:
            metric.labels(*lbl).set(val)

    status = c.get("Status") or {}
    health.labels(*lbl).set(1.0 if status.get("Health") == "OK" else 0.0)

    if "PowerState" in c:
        outlet_on.labels(*lbl).set(1.0 if c["PowerState"] == "On" else 0.0)


def scrape_collection(path: str, kind: str) -> int:
    coll = fetch(path)
    count = 0
    for sub in members(coll):
        set_circuit(fetch(sub), kind)
        count += 1
    return count


def scrape_once() -> None:
    started = time.monotonic()
    try:
        pdus = fetch("/PowerEquipment/RackPDUs")
        for pdu_path in members(pdus):
            for kind, suffix in (("Mains", "Mains"), ("Branches", "Branches"), ("Outlets", "Outlets")):
                try:
                    n = scrape_collection(f"{pdu_path}/{suffix}", kind)
                    log.debug("scraped %s: %d members", kind, n)
                except requests.HTTPError as e:
                    if e.response is not None and e.response.status_code == 404:
                        log.debug("%s not present on this PDU", suffix)
                    else:
                        raise
    except Exception as e:
        scrape_total.labels(HOST, "error").inc()
        scrape_ok.labels(HOST).set(0)
        log.error("scrape failed: %s", e)
    else:
        scrape_total.labels(HOST, "ok").inc()
        scrape_ok.labels(HOST).set(1)
    finally:
        scrape_seconds.labels(HOST).set(time.monotonic() - started)


def loop() -> None:
    while True:
        scrape_once()
        time.sleep(SCRAPE_INTERVAL)


if __name__ == "__main__":
    log.info("starting exporter for %s on :%d (interval=%ds)", HOST, PORT, SCRAPE_INTERVAL)
    start_http_server(PORT)
    threading.Thread(target=loop, daemon=True).start()
    while True:
        time.sleep(3600)
