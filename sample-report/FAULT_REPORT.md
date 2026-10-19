# Fault Report — loopback link degradation under sustained load

Run ID: `20261019-171627` · Python 3.12.3 · platform linux · target 127.0.0.1 only

## Phenomenon

Under a sustained 2,000 pps UDP stream, the path through the fault-injection proxy showed a packet loss rate of 0.5897 (baseline direct path: 0.0000) and a p95 round-trip time of 364.273 ms (baseline p95: 41.96 ms). Loss arrived in clusters aligned with the proxy's periodic link-flap windows, on top of a uniform random-loss background — the signature of a link that is both lossy and intermittently down, not a congested-but-healthy link (which would inflate latency without this loss pattern).

## Reproduction steps

1. From the repository root: `./run_lab.sh`
2. The runner starts the echo server on 127.0.0.1:5005, runs baseline burst + sustained scenarios directly, then starts fault_proxy on 127.0.0.1:6000 with loss=0.20, delay=40 ms, jitter=30 ms, flap 0.6 s down per 2.5 s period, captures a pcap of the fault scenario, and finally runs the malformed packet scenario.
3. Compare `results/latest/baseline_sustained.json` with `results/latest/fault_sustained.json`; every number below comes from those files.

## Measured evidence

| scenario | sent | echoed | lost | loss rate | echo pps | RTT p50 / p95 / p99 (ms) |
|---|---|---|---|---|---|---|
| baseline_burst | 2000 | 2000 | 0 | 0.0000 | 1940.8 | 3.786 / 9.348 / 12.486 |
| baseline_sustained | 9000 | 9000 | 0 | 0.0000 | 2998.4 | 2.703 / 41.96 / 120.452 |
| fault_sustained (via proxy) | 10000 | 4103 | 5897 | 0.5897 | 812.6 | 149.537 / 364.273 / 443.359 |
| malformed mix | 400 | 200 | 200 | 0.5000 | 1002.4 | 0.002 / 2.366 / 4.452 |

Fault-proxy decision log (`fault_proxy_log.jsonl`): client datagrams in=9316, server datagrams in=5449, forwarded=9552, dropped by random loss=2352, dropped by flap window=2861, delayed=9552.

Echo-server totals for the whole run: received 16849, valid 16649, malformed 200, echoed 16649.

Malformed scenario: 200 malformed datagrams were sent and 0 were echoed back. A correct server echoes none of them; valid packets interleaved in the same stream: loss rate 0.0000.

## Packet-capture evidence

- File: `captures/fault_scenario.pcap` (7474824 bytes on disk, pcap v2.4, linktype 101)
- Capture method: raw-socket (see src/capture.py; fallback is a raw IP socket, primary is tcpdump when installed)
- Packets in capture: 24916, captured payload bytes: 7076144, capture span: 5.255 s
- Capture log: `raw-socket captured 24916 packets -> /home/hatch/workspace/oxide-proofs/net-assurance-lab/captures/fault_scenario.pcap`

## Localisation / conclusion

- The baseline path (same generator, same server, no proxy) establishes the loopback noise floor; any delta in the fault run is attributable to the injected faults, because the proxy decision log accounts for drops packet-by-packet and the client-side lost sequence numbers can be cross-checked against it in the per-packet CSVs.
- Latency inflation in the fault run matches the configured 40 ms base delay + up to 30 ms jitter applied in both directions, i.e. the delay is a path property, not server processing time (the baseline p95 isolates server + loopback cost).
- Flap drops cluster at the start of each 2.5 s period (proxy log timestamps), distinguishing an intermittent-down link from uniform random loss — in a real rack this pattern points at a flapping optic/cable or a renegotiating port rather than congestion.
- Malformed datagrams were rejected by header/integrity validation and never echoed, so the server's parser is not the source of the observed loss.
- Accounting gap, stated plainly: the client sent 10000 datagrams and the proxy received 9316; the 684 datagrams in between were dropped by the kernel receive buffer at the proxy's front socket before user space saw them (single-threaded proxy, per-packet log flush). They are part of the measured client-side loss but are not in the proxy decision log, because the proxy never saw them.

## Honest limits of this experiment

- Everything ran on one host's loopback interface. There is no switch ASIC, no optic, no NIC queue, no cross-traffic, and no real cable to flap; the proxy models the *semantics* of loss/delay/flap at the application layer. Numbers here characterise the harness and the method, not any real network hardware.
- Python user-space forwarding adds its own jitter; the delay figures should be read as 'configured delay plus a small host-dependent overhead visible in the baseline'.
- The malformed cases are application-protocol malformations; they do not exercise IP/UDP header corruption, fragmentation, or checksum offload behaviour.
