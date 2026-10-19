"""Controllable traffic generator: burst / sustained / malformed modes.

Sends protocol packets to a target UDP endpoint (directly to the echo
server for a baseline, or via fault_proxy for a fault run), collects the
echoes, and writes per-packet CSV + a summary JSON with real measured
numbers: sent, echoed, lost, loss rate, achieved throughput, and the RTT
distribution (min / mean / p50 / p95 / p99 / max).

Modes:
  burst     -- micro-bursts: B bursts of N packets back-to-back, gap G ms
               between bursts (models incast / microburst pressure).
  sustained -- paced stream at a target rate for D seconds
               (models a large flow saturating a link).
  malformed -- interleaves valid packets with application-layer malformed
               datagrams (bad magic / truncated / corrupted / garbage) and
               verifies the server never echoes a malformed one.
"""
import argparse
import csv
import json
import math
import socket
import sys
import time

from protocol import build_malformed, build_packet


def percentile(sorted_vals, pct):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return sorted_vals[int(k)]
    return sorted_vals[lo] * (hi - k) + sorted_vals[hi] * (k - lo)


def summarise(rows, wall_s):
    rtts = sorted(r["rtt_ms"] for r in rows if r["rtt_ms"] is not None)
    sent = len(rows)
    echoed = len(rtts)
    lost = sent - echoed
    return {
        "sent": sent,
        "echoed": echoed,
        "lost": lost,
        "loss_rate": round(lost / sent, 6) if sent else 0.0,
        "wall_seconds": round(wall_s, 4),
        "throughput_pps": round(sent / wall_s, 1) if wall_s > 0 else 0.0,
        "echo_throughput_pps": round(echoed / wall_s, 1) if wall_s > 0 else 0.0,
        "rtt_ms": {
            "min": round(rtts[0], 3) if rtts else None,
            "mean": round(sum(rtts) / len(rtts), 3) if rtts else None,
            "p50": round(percentile(rtts, 50), 3) if rtts else None,
            "p95": round(percentile(rtts, 95), 3) if rtts else None,
            "p99": round(percentile(rtts, 99), 3) if rtts else None,
            "max": round(rtts[-1], 3) if rtts else None,
        },
    }


def run(args) -> dict:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    # NOTE (measured on the build host, see VERIFICATION.md): unconnected
    # sendto() on UDP is blocked with EPERM by this VM's network policy,
    # while a connected UDP socket + send() passes. The lab therefore uses
    # connected UDP throughout; the packets on the wire are identical.
    sock.connect((args.host, args.port))
    sock.setblocking(False)
    target = (args.host, args.port)

    plan = []  # (seq, is_malformed, payload_builder_thunk)
    seq = 0
    if args.mode == "burst":
        schedule = []  # send times relative to start
        t = 0.0
        for _ in range(args.bursts):
            for _ in range(args.burst_size):
                schedule.append((seq, False))
                seq += 1
            t += args.burst_gap_ms / 1000.0
        pacing = ("bursts", schedule, args.bursts, args.burst_size, args.burst_gap_ms)
    elif args.mode == "sustained":
        n = int(args.rate_pps * args.duration_s)
        schedule = [(i, False) for i in range(n)]
        seq = n
        pacing = ("paced", schedule, args.rate_pps)
    else:  # malformed: 1 malformed per valid packet, deterministic mix
        schedule = []
        for i in range(args.count):
            schedule.append((seq, True))
            seq += 1
            schedule.append((seq, False))
            seq += 1
        pacing = ("paced", schedule, args.rate_pps)

    rows = {}
    sent_ts = {}
    t0 = time.perf_counter()
    next_send_idx = 0
    total = len(schedule)

    if pacing[0] == "bursts":
        burst_no = 0
        idx = 0
        while idx < total:
            for _ in range(args.burst_size):
                if idx >= total:
                    break
                s, bad = schedule[idx]
                payload = build_malformed(idx, s, args.packet_size) if bad else \
                    build_packet(s, args.packet_size, time.time())
                sock.send(payload)
                sent_ts[s] = time.perf_counter()
                rows[s] = {"seq": s, "malformed_sent": int(bad), "rtt_ms": None}
                idx += 1
            burst_no += 1
            deadline = time.perf_counter() + args.burst_gap_ms / 1000.0
            while time.perf_counter() < deadline:
                _drain(sock, rows, sent_ts)
    else:
        rate = pacing[2]
        interval = 1.0 / rate if rate > 0 else 0.0
        next_t = t0
        for s, bad in schedule:
            now = time.perf_counter()
            if now < next_t:
                # drain while waiting so the receive buffer never lags
                while time.perf_counter() < next_t:
                    _drain(sock, rows, sent_ts)
            payload = build_malformed(s, s, args.packet_size) if bad else \
                build_packet(s, args.packet_size, time.time())
            sock.send(payload)
            sent_ts[s] = time.perf_counter()
            rows[s] = {"seq": s, "malformed_sent": int(bad), "rtt_ms": None}
            next_t += interval
            _drain(sock, rows, sent_ts)

    send_wall_s = time.perf_counter() - t0
    # grace window for late echoes
    grace_end = time.perf_counter() + args.grace_s
    while time.perf_counter() < grace_end:
        _drain(sock, rows, sent_ts)
    wall_s = send_wall_s  # throughput is a property of the send phase
    ordered = [rows[k] for k in sorted(rows)]
    # malformed-sent rows can legitimately "echo" only if the malformed
    # bytes accidentally parse as valid; count those explicitly.
    malformed_echoed = sum(1 for r in ordered if r["malformed_sent"] and r["rtt_ms"] is not None)
    valid_rows = [r for r in ordered if not r["malformed_sent"]]

    with open(args.csv_out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["seq", "malformed_sent", "echoed", "rtt_ms"])
        for r in ordered:
            w.writerow([r["seq"], r["malformed_sent"],
                        int(r["rtt_ms"] is not None),
                        "" if r["rtt_ms"] is None else round(r["rtt_ms"], 3)])

    summary = {
        "mode": args.mode,
        "target": f"{args.host}:{args.port}",
        "packet_size_bytes": args.packet_size,
        "all_packets": summarise(ordered, wall_s),
        "valid_packets": summarise(valid_rows, wall_s),
        "malformed_sent": sum(1 for r in ordered if r["malformed_sent"]),
        "malformed_echoed": malformed_echoed,
    }
    with open(args.summary_out, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)
    return summary


def _drain(sock, rows, sent_ts):
    while True:
        try:
            data, _ = sock.recvfrom(65535)
        except BlockingIOError:
            return
        except OSError:
            return
        now = time.perf_counter()
        # echo carries the original header; recover seq from bytes 4-8
        if len(data) >= 8:
            import struct
            seq = struct.unpack("!I", data[4:8])[0]
            if seq in rows and rows[seq]["rtt_ms"] is None and seq in sent_ts:
                rows[seq]["rtt_ms"] = (now - sent_ts[seq]) * 1000.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["burst", "sustained", "malformed"], required=True)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5005)
    ap.add_argument("--packet-size", type=int, default=256)
    ap.add_argument("--bursts", type=int, default=10)
    ap.add_argument("--burst-size", type=int, default=200)
    ap.add_argument("--burst-gap-ms", type=float, default=100.0)
    ap.add_argument("--rate-pps", type=float, default=3000.0)
    ap.add_argument("--duration-s", type=float, default=3.0)
    ap.add_argument("--count", type=int, default=200, help="malformed mode: pairs count")
    ap.add_argument("--grace-s", type=float, default=1.5)
    ap.add_argument("--csv-out", required=True)
    ap.add_argument("--summary-out", required=True)
    args = ap.parse_args()
    run(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
