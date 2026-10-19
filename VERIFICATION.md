# VERIFICATION — build-host run evidence

Final verified run: `20261019-154535` (2026-10-19, America/Los_Angeles).
All figures below are copied from that run's artifacts in
`results/20261019-154535/` (= `results/latest/`).

## Environment probes (actual commands and results)

- `python3 --version` → Python 3.12.3. `go version` → not installed, so
  the lab is Python (spec allowed Go or Python).
- `which tcpdump tshark` → neither installed; `tc` and `ip` exist.
  Install was attempted: `pip install scapy` succeeded (scapy 2.8.0),
  but `apt-get install -y tcpdump tshark` failed with
  "E: Unable to locate package tcpdump / tshark" (the VM's apt sources
  do not carry them). So the tcpdump capture path in
  `src/capture.py` is implemented but **untested on this host** — the
  pcap in this repo was produced by the raw-socket path (see below).
  Scapy *is* installed and was used as an independent pcap parser.
- Raw/packet socket creation: OK (process runs as root,
  CAP_NET_RAW in the bounding set).

## Blocker found and worked around: UDP sendto EPERM

First run of `./run_lab.sh` failed: `traffic_gen.py` raised
`PermissionError: [Errno 1] Operation not permitted` on the first burst
`sendto`. Isolation tests (all loopback-only):

- Single unconnected UDP `sendto` to 127.0.0.1 → EPERM on every port
  tried (53, 123, 5005, 9999).
- Raw IP socket send with IP_HDRINCL → EPERM. Inside a fresh network
  namespace (`unshare -n`, lo up) → EPERM. IPv6 ::1 → EPERM.
- `iptables -L` → all chains empty, policy ACCEPT. TCP loopback →
  works. **Connected UDP socket (`connect()` + `send()`) → works.**

Conclusion: the VM's network policy blocks unconnected UDP sends. Fix
applied: generator, server and proxy all use connected UDP (documented
in code comments and README). Packets on the wire are identical UDP
datagrams; only the local socket call pattern differs.

## Commands run for the final artifacts

```
python3 -m unittest discover -s tests -v   → 5 tests, OK
./run_lab.sh                               → exit 0,
  "run complete: .../results/20261019-154535"
```

## Key outputs of the final run

Scenario summaries (`results/latest/*.json`, `all_packets`):

| scenario | sent | echoed | lost | loss rate | echo pps | RTT p50 | RTT p95 | RTT p99 |
|---|---|---|---|---|---|---|---|---|
| baseline_burst | 2000 | 2000 | 0 | 0.0000 | 1958.5 | 2.117 | 4.656 | 5.517 |
| baseline_sustained | 9000 | 9000 | 0 | 0.0000 | 3000.3 | 0.003 | 3.047 | 6.952 |
| fault_sustained | 10000 | 4725 | 5275 | 0.5275 | 945.0 | 116.861 | 162.401 | 245.775 |
| malformed (valid subset) | 200 | 200 | 0 | 0.0000 | — | — | — | — |

(RTT in ms. Malformed scenario totals: 400 sent incl. 200 malformed,
200 echoed, `malformed_echoed: 0`.)

Fault-proxy summary line (`fault_proxy_log.jsonl`, 16,104 lines total):

```
{"summary": {"in_client": 10000, "in_server": 6103, "dropped_loss": 2680,
             "dropped_flap": 2595, "forwarded": 10828, "delayed": 10828}}
```

Server stats per scenario: baseline_burst 2000/2000 echoed;
baseline_sustained 9000/9000; fault_sustained 6103 received = 6103 echoed;
malformed 400 received, 200 valid + 200 malformed, 200 echoed.

Cross-checks that tie out: proxy `in_server` (6103) equals the fault
server's received_total (6103); client loss in the fault run (0.5275) is
consistent with 20% loss + 0.6/2.5 s flap applied in *both* directions
(survival ≈ 0.8 × 0.76 per leg, compounded over the round trip);
fault-run RTT floor (~81 ms minimum in an earlier run) matches the
configured 40 ms × 2 legs.

## Pcap authenticity

- Produced by `src/capture.py`, `CAPTURE_METHOD=raw-socket`
  (`results/latest/capture_log.txt`): a raw IP socket captured the
  packets as they crossed loopback during the fault scenario; the file
  was serialised as pcap v2.4, LINKTYPE_RAW.
- `captures/fault_scenario.pcap`: 8,079,324 bytes, 26,931 packets,
  capture span 5.251 s.
- Independent validation with Scapy (not the lab's own parser):
  `rdpcap` parsed all 26,931 packets; **all 26,931** carry UDP payloads
  starting with the lab magic `NAL1`; top flows match the topology —
  generator→proxy :6000, proxy→server :5005, server→proxy, proxy→
  generator. An earlier run's capture validated identically
  (25,715 packets, 25,715 NAL1).

## Generated file list (final state)

```
README.md  VERIFICATION.md  Makefile  run_lab.sh
src/protocol.py  src/echo_server.py  src/fault_proxy.py
src/traffic_gen.py  src/capture.py  src/run_experiment.py
src/gen_report.py            (1,007 lines of Python incl. tests)
tests/test_protocol.py       (5 tests, OK)
captures/fault_scenario.pcap (real capture, see above)
sample-report/FAULT_REPORT.md (generated from the final run)
results/20261019-154535/ + results/latest/ (identical copies):
  baseline_burst.{csv,json}  baseline_sustained.{csv,json}
  fault_sustained.{csv,json}  malformed.{csv,json}
  server_stats_<scenario>.json ×4  fault_proxy_log.jsonl
  capture_log.txt  run_meta.json
```

## Not completed / known limits

- tcpdump/tshark capture path untested on this host (packages not
  installed in time); the shipped pcap is from the raw-socket path and
  is labelled as such in the report. On any normal Linux host,
  `capture.py` prefers tcpdump automatically.
- tc/netem path not used (see README: application-layer injection is
  the design, with its limits stated).
- No external network target was contacted at any point; every socket
  in the build, tests and runs is bound to / connected to 127.0.0.1.

---

# Supplement: Prometheus + Grafana monitoring module (2026-10-19)

Added after the original verification above; nothing above was changed.
Verification level for this supplement: **fully run end-to-end on this
host** (real Prometheus and Grafana binaries, real exporter, real lab
run) — details and the two download/host quirks encountered are below.

## What was added

```
src/prom_exporter.py               exporter, stdlib only, /metrics + /healthz
tests/test_prom_exporter.py        6 new tests (collect/HTTP/missing-dir)
monitoring/prometheus.yml          scrape config (job net-assurance-lab)
monitoring/rules/alerts.yml        10 alert rules
monitoring/start_local.sh          local stack starter (binaries via env)
monitoring/grafana/provisioning/datasources/prometheus.yml
monitoring/grafana/provisioning/dashboards/dashboards.yml
monitoring/grafana/dashboards/service-overview.json    (12 panels)
monitoring/grafana/dashboards/fault-comparison.json   (12 panels)
README.md                          new "Monitoring" section
```

Design note: the exporter re-reads `results/latest/` on every scrape.
The lab publishes results at the end of a run, so this *is* the
live-update path — a re-run refreshes Prometheus/Grafana with no
exporter restart. Existing lab files and behaviour were not modified
(the exporter only reads artifacts; the only pre-existing files edited
are `README.md`, this file (append-only), and no `src/` originals).

## Fresh lab run consumed by the monitoring stack

```
./run_lab.sh  ->  exit 0, "run complete: .../results/20261019-171627"
python3 -m unittest discover -s tests -v  ->  11 tests, OK
  (5 original protocol tests + 6 new exporter tests; exporter tests use
   fixed synthetic inputs for exact-value assertions and assert only
   shape against the real results/latest)
```

Key figures of run `20261019-171627` (from `results/latest/*.json` and
the proxy summary line; these are the values every monitoring check
below must — and did — reproduce):

| scenario | sent | echoed | loss rate | echo pps | RTT p50 | RTT p95 | RTT p99 |
|---|---|---|---|---|---|---|---|
| baseline_burst | 2000 | 2000 | 0.0 | 1940.8 | 3.786 | 9.348 | 12.486 |
| baseline_sustained | 9000 | 9000 | 0.0 | 2998.4 | 2.703 | 41.96 | 120.452 |
| fault_sustained | 10000 | 4103 | 0.5897 | 812.6 | 149.537 | 364.273 | 443.359 |
| malformed (all) | 400 | 200 | 0.5 | 1002.4 | 0.002 | 2.366 | 4.452 |

Proxy summary: `in_client 9316, in_server 5449, dropped_loss 2352,
dropped_flap 2861, forwarded 9552, delayed 9552`.
Note: this run's `baseline_sustained` p99 (120.452 ms) is far above the
previous verified run's 6.952 ms — host scheduling jitter on the build
VM, visible in the raw JSON, and it is what legitimately fires the
baseline-p99 alert below. The alert working on real data is the point;
the threshold (50 ms) was *not* tuned after the fact to hide it.

## Binaries: download record (official sources only)

- Prometheus v3.15.0 (latest release per GitHub API at build time) from
  `github.com/prometheus/prometheus/releases/download/v3.15.0/
  prometheus-3.15.0.linux-amd64.tar.gz` (107 MB).
  `prometheus --version` -> `version 3.15.0 ... go1.27.1 linux/amd64`.
  Extraction needed `tar --no-same-owner` (ownership remap not
  permitted in this VM) — cosmetic, contents unaffected.
- Grafana OSS 13.2.4 (latest per GitHub API) from
  `dl.grafana.com/oss/release/grafana-13.2.4.linux-amd64.tar.gz`
  (461,295,109 bytes). First download attempt hit the command's 900 s
  cap 908,805 bytes short (`gzip -t`: unexpected end of file); resumed
  with `curl -C -`, final size exactly 461,295,109 bytes, `gzip -t` OK.
  `grafana --version` -> `grafana version 13.2.4`.
- Host quirk: `/tmp` is a 512 MB tmpfs and was at 100% during the
  Grafana download, so archives were downloaded to `/tmp` first (per
  plan) but the Grafana archive was moved to a workspace-disk scratch
  dir (`~/workspace/.monitoring-scratch/`, outside the repo) for the
  resume + extraction. Binaries were run from that scratch dir and
  deleted after verification; nothing binary is vendored in the repo.

## Static validation (promtool + parsers)

```
promtool check config monitoring/prometheus.yml
  -> SUCCESS: 1 rule files found; valid prometheus config file syntax
promtool check rules monitoring/rules/alerts.yml
  -> SUCCESS: 10 rules found
python json.load on both dashboards -> OK (uids nal-service-overview /
  nal-fault-comparison, schemaVersion 39, 12 panels each, every target
  carries an expr); yaml.safe_load on prometheus.yml, alerts.yml and
  both provisioning files -> OK
```

## Live run evidence

Stack started locally, all loopback: exporter on 9108
(`python3 src/prom_exporter.py`), Prometheus 3.15.0 on 9090 with
`monitoring/prometheus.yml`, Grafana 13.2.4
on 3000 with `GF_PATHS_PROVISIONING` pointing at the repo's
`monitoring/grafana/provisioning` and `NETLAB_DASHBOARDS_PATH` set to
the repo's dashboards folder (the env-var expansion in
`dashboards.yml` is the mechanism under test).

Prometheus:

```
GET /-/healthy              -> "Prometheus Server is Healthy."
GET /api/v1/targets         -> net-assurance-lab http://127.0.0.1:9108/metrics  up
                               prometheus       http://127.0.0.1:9090/metrics  up
GET /api/v1/rules           -> group net-assurance-lab.rules, 10 rules loaded
GET /api/v1/query nal_loss_ratio
  -> baseline_burst 0, baseline_sustained 0, fault_sustained 0.5897, malformed 0
GET /api/v1/query nal_rtt_ms{stat="p99"}
  -> 12.486 / 120.452 / 443.359 / 4.452 (matches the table above)
GET /api/v1/query nal_throughput_pps{scenario="fault_sustained"}
  -> send 1980.5, echo 812.6
GET /api/v1/query nal_fault_proxy_packets_total
  -> in_client 9316, in_server 5449, dropped_loss 2352,
     dropped_flap 2861, forwarded 9552, delayed 9552
GET /api/v1/query nal_fault_injection_config
  -> loss_ratio 0.2, delay_ms 40, jitter_ms 30, flap_period_s 2.5, flap_down_s 0.6
GET /api/v1/query nal_link_flap_detected -> 1
GET /api/v1/query_range nal_loss_ratio{scenario="fault_sustained"}
  -> series returned, values 0.5897 (range queries work, not just instant)
GET /api/v1/alerts (after the for: durations elapsed)
  -> NalLinkFlapDetected        firing  severity=info     value 1
     NalBaselineP99LatencyHigh  firing  severity=warning  value 120.452
     (all other rules inactive on this run's data — correct: baseline
      loss is 0, malformed_echoed is 0, results are fresh)
```

Every panel query of both dashboards was also executed against the
Prometheus API directly: 26 targets, 26 returned non-empty series,
0 empty, 0 errors.

Grafana (admin credentials were a throwaway local pair, not stored
in the repo):

```
GET /api/health -> {"database": "ok", "version": "13.2.4", "commit": "0e79aef9..."}
provisioning log -> "starting to provision dashboards" ...
                    "finished to provision dashboards"
GET /api/datasources -> Prometheus | prometheus | uid prometheus |
                        http://127.0.0.1:9090 | default: True
GET /api/datasources/uid/prometheus/health
  -> {"status": "OK", "message": "Successfully queried the Prometheus API."}
GET /api/search?type=dash-db
  -> nal-service-overview    "net-assurance-lab - Service Overview"           (folder net-assurance-lab)
     nal-fault-comparison    "net-assurance-lab - Fault Injection Comparison" (folder net-assurance-lab)
GET /api/dashboards/uid/<uid> -> both return 12 panels; neither dashboard
  was created via the API — provisioning is the only way they got in.
POST /api/ds/query (panel queries through Grafana itself, now-1h..now)
  -> nal_loss_ratio: 4 series x 19 points, fault_sustained last = 0.5897
     nal_rtt_ms{stat="p99"}: last values 12.486 / 120.452 / 443.359 / 4.452
     proxy drops: dropped_flap last = 2861, dropped_loss last = 2352
     fault throughput: send last = 1980.5, echo last = 812.6
  i.e. the dashboards do not merely load — their panels render the
  exported run's real data through the provisioned datasource.
```

Cosmetic note: Grafana logged two `level=error` lines about missing
*plugin* and *alerting* provisioning sub-directories (this repo only
provisions datasources + dashboards). Harmless: provisioning of both
shipped kinds finished, and the API checks above passed.

## Cleanup and limits of this supplement

- Launch quirk, recorded honestly: the Prometheus start command passed
  `--storage.tsdb.path=~/workspace/...` as a program argument, where
  the shell does not expand `~`; the TSDB therefore landed in a literal
  directory named `~` inside the repo (900 KB) instead of the scratch
  dir. It affected nothing else (Prometheus served normally) and was
  deleted in cleanup; `start_local.sh` uses an absolute `$DATA` path
  and does not have this bug.
- After evidence capture, the exporter / Prometheus / Grafana
  processes were stopped and the downloaded binaries, TSDB and
  Grafana data were deleted (repo carries only the hand-written
  module). Reproduction = `monitoring/start_local.sh`
  with `PROM_BIN` / `GRAFANA_BIN` pointing at fresh downloads.
- Not covered: Alertmanager routing (none configured by design),
  Grafana alerting, authentication hardening, and any non-loopback
  deployment. The dashboards' time series show the exported run's
  values as scraped over time; intra-run time dynamics do not exist in
  the lab's artifacts and are not invented here.
