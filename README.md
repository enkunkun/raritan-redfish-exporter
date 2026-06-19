# raritan-redfish-exporter

Prometheus exporter for Raritan PDUs (PX2/PX3/PX4 family) via their built-in
Redfish API. Walks `PowerEquipment/RackPDUs/{n}` and re-exposes Mains,
Branches, and Outlets metrics on a single `/metrics` endpoint.

Tested on PX3TS-1194JR (firmware 4.3.13.5). Should work on any Raritan PDU
that speaks Redfish `PowerEquipment` (PX2 with recent firmware, PX3, PX4).

## Why not `jenningsloy318/redfish_exporter`?

That exporter (the common Redfish exporter on GitHub) targets server BMCs and
walks `Chassis.Power` / `Chassis.Thermal`. Raritan PDUs publish their
readings under `PowerEquipment.RackPDUs`, which that exporter does not
collect — so it returns no data.

## Metrics

All metrics share the labels `host`, `circuit_type` (`Mains` | `Branches` |
`Outlets`), `circuit_id`, and `user_label`.

| Metric | Description |
|---|---|
| `raritan_voltage_volts` | Circuit voltage |
| `raritan_current_amps` | Circuit current |
| `raritan_power_watts` | Active power |
| `raritan_apparent_va` | Apparent power |
| `raritan_power_factor` | Power factor |
| `raritan_frequency_hz` | Line frequency |
| `raritan_energy_kwh` | Cumulative energy |
| `raritan_rated_current_amps` | Nameplate rated current |
| `raritan_circuit_health` | 1 if `Status.Health == OK` |
| `raritan_outlet_powered` | 1 if `PowerState == On` (outlets only) |
| `raritan_scrape_success` | 1 if the last poll cycle succeeded |
| `raritan_scrape_duration_seconds` | Duration of the last poll cycle |
| `raritan_scrape_attempts_total` | Counter of `ok` / `error` attempts |

## Configuration

The exporter is configured via environment variables. There is no config
file, so the same image works for every deployment.

| Variable | Required | Default | Notes |
|---|---|---|---|
| `RARITAN_HOST` | yes | — | PDU hostname or IP |
| `RARITAN_USER` | yes | — | A read-only user (see below) |
| `RARITAN_PASS` | yes | — | Password |
| `RARITAN_SCHEME` | no | `https` | Override if you must use HTTP |
| `EXPORTER_PORT` | no | `9610` | Listen port |
| `SCRAPE_INTERVAL` | no | `60` | Seconds between polls |
| `HTTP_TIMEOUT` | no | `10` | Per-request timeout |

### Read-only Raritan user

Create a role with **only** the *Unrestricted View Privilege* permission
(`制限のない表示権限` in Japanese UI), then create a user assigned to that
role. No SNMP, no write privileges, no outlet control.

## Run with Docker

```sh
docker run -d --restart=unless-stopped \
  -p 9610:9610 \
  -e RARITAN_HOST=pdu.example.local \
  -e RARITAN_USER=monitor \
  -e RARITAN_PASS=... \
  ghcr.io/enkunkun/raritan-redfish-exporter:latest
```

Then point Prometheus at `host:9610`:

```yaml
scrape_configs:
  - job_name: raritan-pdu
    scrape_interval: 60s
    static_configs:
      - targets: ["raritan-redfish-exporter:9610"]
```

## TLS

Raritan PDUs ship with a self-signed certificate, so the exporter sets
`verify=False` on the HTTPS session. If you have provisioned a trusted
certificate, that is fine — the exporter still works, it just does not
verify.

## Quirks worked around

Raritan firmware 4.x returns a malformed schema-like body when an HTTP/2
client requests Redfish endpoints without `Accept-Encoding: gzip`. The
exporter always sends that header, which makes the firmware return valid
JSON.

## License

MIT
