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
