# net-assurance-lab

A small, reproducible network-reliability experiment bench on loopback,
built as a proof artifact for product-assurance / network test work:
a controllable traffic generator, an application-layer fault-injection
proxy, automatic metrics collection, a real packet capture, and a
generated fault report whose numbers all come from the run itself.

Everything runs against **127.0.0.1 only**. No packet is ever sent to an
external target. All code is hand-written for this lab (clean-room),
Python 3 standard library only — no third-party dependency is required
to run it.

## What failure mode each experiment is designed to expose

| Scenario | Traffic | Fault injected | Failure mode it exposes |
|---|---|---|---|
| `baseline_burst` | 10 micro-bursts × 200 packets, 100 ms gaps | none | Receiver/queue behaviour under incast-style microbursts: does a burst overflow a receive buffer or inflate tail latency even on a healthy path? |
| `baseline_sustained` | 3,000 pps paced stream, 3 s | none | The noise floor: sustained-throughput capability and RTT distribution of the healthy path, used as the control for every fault run. |
| `fault_sustained` | 2,000 pps paced stream, 5 s, via proxy | 20% random loss each way, +40 ms delay with up to 30 ms jitter each way, link flap 0.6 s down in every 2.5 s period | A degrading link: separates *uniform random loss* from *flap-clustered loss* and from *pure latency inflation*, and tests whether the localisation method (baseline delta + per-packet proxy decision log + pcap) can attribute each observed symptom to the right cause. |
| `malformed` | 200 malformed + 200 valid datagrams interleaved at 2,000 pps | bad magic, truncated header, corrupted payload, random garbage | Parser robustness: a correct receiver rejects adversarial/malformed input without echoing it and without disturbing the valid traffic sharing the stream. |

## Structure

```
run_lab.sh                  one-command entry point
Makefile                    make run / make test / make clean
src/
  protocol.py               wire format (magic + seq + timestamp + filler)
                            and the malformed-packet variants
  echo_server.py            validating UDP echo server, per-scenario stats
  fault_proxy.py            loss / delay+jitter / flap injection with a
                            per-packet JSONL decision log
  traffic_gen.py            burst / sustained / malformed generator;
                            per-packet CSV + summary JSON (loss, throughput,
                            RTT min/mean/p50/p95/p99/max)
  capture.py                pcap capture: tcpdump when installed, else a
                            raw IP socket writing LINKTYPE_RAW pcap by hand
  run_experiment.py         orchestrates all four scenarios + capture
  gen_report.py             renders sample-report/FAULT_REPORT.md purely
                            from the run artifacts and the pcap itself
tests/test_protocol.py      protocol round-trip and malformed-rejection tests
results/<run_id>/           raw artifacts of one run (CSVs, JSONs, logs)
results/latest/             copy of the most recent run
captures/fault_scenario.pcap  pcap of the fault scenario (real capture)
sample-report/FAULT_REPORT.md generated fault report (phenomenon,
                            reproduction, capture evidence, localisation)
VERIFICATION.md             build-host run evidence: commands, outputs,
                            environment quirks and how they were handled
```

## How to run

```bash
./run_lab.sh        # or: make run
python3 -m unittest discover -s tests -v   # or: make test
```

Requirements: Python 3.10+, loopback UDP. `tcpdump` is used for capture
when present; otherwise the built-in raw-socket capture path is used and
the report records which path produced the pcap. No root is needed for
the traffic itself; the raw-socket capture path needs permission to open
a raw IP socket (root or `CAP_NET_RAW`), and `capture.py` fails loudly
rather than fabricating a capture if it gets zero packets.

## Metrics collected (all measured, never templated)

Per scenario: packets sent / echoed / lost, loss rate, send-phase and
echo throughput (pps), RTT min/mean/p50/p95/p99/max, plus server-side
received/valid/malformed/echoed counters and the proxy's per-packet
decision log (forward / drop_loss / drop_flap, with delay applied).
Structured outputs: per-packet CSVs and summary JSONs under
`results/<run_id>/`.

## Honest boundaries — what this lab is and is not

- **Loopback is not a rack.** There is no switch ASIC, no optic or DAC, no
  NIC queue, no cross-traffic, and no physical cable to flap. The proxy
  models the *semantics* of loss, delay and flap at the application
  layer. The numbers characterise the harness and the method; they are
  not measurements of any real network hardware, and the achievable
  rates (a few thousand pps from a Python generator) are orders of
  magnitude below line-rate hardware testing.
- **Fault injection is application-layer, not tc/netem.** That is a
  deliberate trade: decisions are logged packet-by-packet and the bench
  is portable, but kernel queueing, netem-style distributions and
  sub-millisecond timing fidelity are out of scope.
- **Malformed means application-protocol malformed** (bad magic,
  truncation, corruption, garbage). It does not exercise IP/UDP header
  corruption, fragmentation, or checksum-offload behaviour.
- **Host quirk found while building (documented, not hidden):** on the
  build VM, unconnected UDP `sendto()` is blocked with EPERM by the host
  network policy, while connected UDP sockets send normally. The lab
  therefore uses connected UDP throughout; the packets on the wire are
  unchanged. Full detail in VERIFICATION.md.
- The fault report is generated from a single run's artifacts; re-running
  produces fresh numbers each time (loss is seeded in the proxy, but OS
  scheduling jitter is not), and `results/` keeps each run separate so
  figures can always be traced back to their run.
