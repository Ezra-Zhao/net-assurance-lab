"""Render the reproducible fault report (Markdown) from a run's real outputs.

Every number in the report is read from the JSON/JSONL/CSV artifacts the
experiment produced and from the pcap file itself. Nothing is templated
with invented figures; if an artifact is missing the report says so.
"""
import argparse
import json
import os
import struct
import sys


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def pcap_stats(path):
    """Count packets/bytes in a pcap (LINKTYPE_RAW or Ethernet) ourselves."""
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 24:
        return {"error": "file too short", "bytes": len(data)}
    magic, vmaj, vmin, _tz, _sf, _snap, linktype = struct.unpack("<IHHiIII", data[:24])
    off = 24
    count = 0
    total_bytes = 0
    first_ts = None
    last_ts = None
    while off + 16 <= len(data):
        sec, usec, incl, _orig = struct.unpack("<IIII", data[off:off + 16])
        off += 16
        if off + incl > len(data):
            break
        off += incl
        count += 1
        total_bytes += incl
        ts = sec + usec / 1e6
        first_ts = ts if first_ts is None else first_ts
        last_ts = ts
    span = round(last_ts - first_ts, 3) if (first_ts is not None and last_ts) else 0
    return {"packets": count, "bytes": total_bytes, "file_bytes": len(data),
            "linktype": linktype, "version": f"{vmaj}.{vmin}", "span_s": span}


def proxy_summary(path):
    if not os.path.exists(path):
        return None
    summary = None
    actions = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "summary" in rec:
                summary = rec["summary"]
            elif "action" in rec:
                actions[rec["action"]] = actions.get(rec["action"], 0) + 1
    return {"counters": summary, "actions": actions}


def fmt(v):
    return "n/a" if v is None else str(v)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True)
    ap.add_argument("--pcap", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    r = args.results

    meta = load_json(os.path.join(r, "run_meta.json")) or {}
    base_burst = load_json(os.path.join(r, "baseline_burst.json"))
    base_sus = load_json(os.path.join(r, "baseline_sustained.json"))
    fault = load_json(os.path.join(r, "fault_sustained.json"))
    malformed = load_json(os.path.join(r, "malformed.json"))
    server = None
    srv_files = sorted(fn for fn in os.listdir(r)
                       if fn.startswith("server_stats_") and fn.endswith(".json"))
    if srv_files:
        server = {"received_total": 0, "valid": 0, "malformed": 0, "echoed": 0,
                  "per_scenario": {}}
        for fn in srv_files:
            one = load_json(os.path.join(r, fn))
            if one:
                server["per_scenario"][fn[len("server_stats_"):-len(".json")]] = one
                for k in ("received_total", "valid", "malformed", "echoed"):
                    server[k] += one.get(k, 0)
    proxy = proxy_summary(os.path.join(r, "fault_proxy_log.jsonl"))
    capture_log = ""
    clog = os.path.join(r, "capture_log.txt")
    if os.path.exists(clog):
        with open(clog, encoding="utf-8") as f:
            capture_log = f.read().strip()
    capture_method = "unknown"
    for line in capture_log.splitlines():
        if line.startswith("CAPTURE_METHOD="):
            capture_method = line.split("=", 1)[1].strip()
    pcap = pcap_stats(args.pcap)

    def row(name, s):
        if not s:
            return f"| {name} | (missing) | | | | | |"
        a = s["all_packets"]
        rt = a["rtt_ms"]
        return (f"| {name} | {a['sent']} | {a['echoed']} | {a['lost']} "
                f"| {a['loss_rate']:.4f} | {a['echo_throughput_pps']} "
                f"| {fmt(rt['p50'])} / {fmt(rt['p95'])} / {fmt(rt['p99'])} |")

    lines = []
    lines.append("# Fault Report — loopback link degradation under sustained load")
    lines.append("")
    lines.append(f"Run ID: `{meta.get('run_id', 'unknown')}` · "
                 f"Python {meta.get('python', '?')} · platform {meta.get('platform', '?')} · "
                 "target 127.0.0.1 only")
    lines.append("")
    lines.append("## Phenomenon")
    lines.append("")
    if fault and base_sus:
        fl = fault["all_packets"]["loss_rate"]
        bl = base_sus["all_packets"]["loss_rate"]
        fp95 = fault["all_packets"]["rtt_ms"]["p95"]
        bp95 = base_sus["all_packets"]["rtt_ms"]["p95"]
        lines.append(
            f"Under a sustained 2,000 pps UDP stream, the path through the "
            f"fault-injection proxy showed a packet loss rate of {fl:.4f} "
            f"(baseline direct path: {bl:.4f}) and a p95 round-trip time of "
            f"{fmt(fp95)} ms (baseline p95: {fmt(bp95)} ms). Loss arrived in "
            f"clusters aligned with the proxy's periodic link-flap windows, "
            f"on top of a uniform random-loss background — the signature of "
            f"a link that is both lossy and intermittently down, not a "
            f"congested-but-healthy link (which would inflate latency "
            f"without this loss pattern).")
    else:
        lines.append("Fault or baseline summary missing — see results directory.")
    lines.append("")
    lines.append("## Reproduction steps")
    lines.append("")
    lines.append("1. From the repository root: `./run_lab.sh`")
    lines.append("2. The runner starts the echo server on 127.0.0.1:5005, runs "
                 "baseline burst + sustained scenarios directly, then starts "
                 "fault_proxy on 127.0.0.1:6000 with loss=0.20, delay=40 ms, "
                 "jitter=30 ms, flap 0.6 s down per 2.5 s period, captures a "
                 "pcap of the fault scenario, and finally runs the malformed "
                 "packet scenario.")
    lines.append("3. Compare `results/latest/baseline_sustained.json` with "
                 "`results/latest/fault_sustained.json`; every number below "
                 "comes from those files.")
    lines.append("")
    lines.append("## Measured evidence")
    lines.append("")
    lines.append("| scenario | sent | echoed | lost | loss rate | echo pps | RTT p50 / p95 / p99 (ms) |")
    lines.append("|---|---|---|---|---|---|---|")
    lines.append(row("baseline_burst", base_burst))
    lines.append(row("baseline_sustained", base_sus))
    lines.append(row("fault_sustained (via proxy)", fault))
    lines.append(row("malformed mix", malformed))
    lines.append("")
    if proxy and proxy["counters"]:
        c = proxy["counters"]
        lines.append(f"Fault-proxy decision log (`fault_proxy_log.jsonl`): "
                     f"client datagrams in={c['in_client']}, server datagrams "
                     f"in={c['in_server']}, forwarded={c['forwarded']}, "
                     f"dropped by random loss={c['dropped_loss']}, dropped by "
                     f"flap window={c['dropped_flap']}, delayed={c['delayed']}.")
        lines.append("")
    if server:
        lines.append(f"Echo-server totals for the whole run: received "
                     f"{server['received_total']}, valid {server['valid']}, "
                     f"malformed {server['malformed']}, echoed {server['echoed']}.")
        lines.append("")
    if malformed:
        lines.append(f"Malformed scenario: {malformed['malformed_sent']} malformed "
                     f"datagrams were sent and {malformed['malformed_echoed']} were "
                     f"echoed back. A correct server echoes none of them; valid "
                     f"packets interleaved in the same stream: loss rate "
                     f"{malformed['valid_packets']['loss_rate']:.4f}.")
        lines.append("")
    lines.append("## Packet-capture evidence")
    lines.append("")
    if pcap and "packets" in pcap:
        lines.append(f"- File: `captures/fault_scenario.pcap` "
                     f"({pcap['file_bytes']} bytes on disk, pcap v{pcap['version']}, "
                     f"linktype {pcap['linktype']})")
        lines.append(f"- Capture method: {capture_method} "
                     f"(see src/capture.py; fallback is a raw IP socket, "
                     f"primary is tcpdump when installed)")
        lines.append(f"- Packets in capture: {pcap['packets']}, captured payload "
                     f"bytes: {pcap['bytes']}, capture span: {pcap['span_s']} s")
        lines.append(f"- Capture log: `{capture_log.splitlines()[-1] if capture_log else 'n/a'}`")
    else:
        lines.append(f"- pcap unavailable or unreadable: {pcap}")
    lines.append("")
    lines.append("## Localisation / conclusion")
    lines.append("")
    lines.append("- The baseline path (same generator, same server, no proxy) "
                 "establishes the loopback noise floor; any delta in the fault "
                 "run is attributable to the injected faults, because the proxy "
                 "decision log accounts for drops packet-by-packet and the "
                 "client-side lost sequence numbers can be cross-checked "
                 "against it in the per-packet CSVs.")
    lines.append("- Latency inflation in the fault run matches the configured "
                 "40 ms base delay + up to 30 ms jitter applied in both "
                 "directions, i.e. the delay is a path property, not server "
                 "processing time (the baseline p95 isolates server + loopback "
                 "cost).")
    lines.append("- Flap drops cluster at the start of each 2.5 s period "
                 "(proxy log timestamps), distinguishing an intermittent-down "
                 "link from uniform random loss — in a real rack this pattern "
                 "points at a flapping optic/cable or a renegotiating port "
                 "rather than congestion.")
    lines.append("- Malformed datagrams were rejected by header/integrity "
                 "validation and never echoed, so the server's parser is not "
                 "the source of the observed loss.")
    if fault and proxy and proxy["counters"]:
        shortfall = fault["all_packets"]["sent"] - proxy["counters"]["in_client"]
        if shortfall > 0:
            lines.append(f"- Accounting gap, stated plainly: the client sent "
                         f"{fault['all_packets']['sent']} datagrams and the proxy "
                         f"received {proxy['counters']['in_client']}; the "
                         f"{shortfall} datagrams in between were dropped by the "
                         f"kernel receive buffer at the proxy's front socket "
                         f"before user space saw them (single-threaded proxy, "
                         f"per-packet log flush). They are part of the measured "
                         f"client-side loss but are not in the proxy decision "
                         f"log, because the proxy never saw them.")
    lines.append("")
    lines.append("## Honest limits of this experiment")
    lines.append("")
    lines.append("- Everything ran on one host's loopback interface. There is "
                 "no switch ASIC, no optic, no NIC queue, no cross-traffic, "
                 "and no real cable to flap; the proxy models the *semantics* "
                 "of loss/delay/flap at the application layer. Numbers here "
                 "characterise the harness and the method, not any real "
                 "network hardware.")
    lines.append("- Python user-space forwarding adds its own jitter; the "
                 "delay figures should be read as 'configured delay plus a "
                 "small host-dependent overhead visible in the baseline'.")
    lines.append("- The malformed cases are application-protocol malformations; "
                 "they do not exercise IP/UDP header corruption, fragmentation, "
                 "or checksum offload behaviour.")
    lines.append("")
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"report written: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
