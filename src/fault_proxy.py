"""Application-layer UDP fault-injection proxy.

Sits between the traffic generator and the echo server on loopback and
injects, in the forwarding path:
  - packet loss      (--loss 0.0-1.0, deterministic RNG seed)
  - added delay      (--delay-ms base + uniform jitter up to --jitter-ms),
                     implemented with a delayed-send queue (heap)
  - link flap        (--flap-period-s / --flap-down-s: during each period,
                     the first down-window drops 100% of traffic both ways)

Why application layer instead of tc/netem: this VM is a container-like
guest where netem may not be permitted for every user, and an app-layer
proxy is portable and its drop/delay decisions are logged packet-by-packet,
which makes the experiment auditable. The trade-off (documented in README):
it models loss/delay/flap *semantics*, not kernel/NIC behaviour, queueing
in a real switch ASIC, or sub-millisecond timing fidelity.

Connected-UDP note: on the build VM, unconnected UDP sendto() is blocked
with EPERM by the host network policy (measured; see VERIFICATION.md),
while connected UDP sockets send fine. The back socket is connect()ed to
the server up front; the front socket connect()s to the first client it
hears from (the lab is one client at a time). Wire format is unchanged.

Every forwarded/dropped/delayed datagram is appended to a JSONL decision
log so a report can point at exactly which sequences were sacrificed.
"""
import argparse
import heapq
import json
import random
import select
import socket
import sys
import time


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen-host", default="127.0.0.1")
    ap.add_argument("--listen-port", type=int, default=6000)
    ap.add_argument("--target-host", default="127.0.0.1")
    ap.add_argument("--target-port", type=int, default=5005)
    ap.add_argument("--loss", type=float, default=0.0)
    ap.add_argument("--delay-ms", type=float, default=0.0)
    ap.add_argument("--jitter-ms", type=float, default=0.0)
    ap.add_argument("--flap-period-s", type=float, default=0.0)
    ap.add_argument("--flap-down-s", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--log-out", required=True)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    front = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    front.bind((args.listen_host, args.listen_port))
    front.setblocking(False)
    back = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    back.connect((args.target_host, args.target_port))
    back.setblocking(False)

    logf = open(args.log_out, "w", encoding="utf-8")
    counters = {"in_client": 0, "in_server": 0, "dropped_loss": 0,
                "dropped_flap": 0, "forwarded": 0, "delayed": 0}
    client_locked = {"flag": False}
    start = time.monotonic()
    pending = []  # heap of (due_monotonic, dest_sock, payload)

    def flap_is_down(now: float) -> bool:
        if args.flap_period_s <= 0 or args.flap_down_s <= 0:
            return False
        return (now % args.flap_period_s) < args.flap_down_s

    def decide(payload, direction, now):
        """Return delay_seconds to apply, or None to drop."""
        if flap_is_down(now):
            counters["dropped_flap"] += 1
            logf.write(json.dumps({"t": round(now, 6), "dir": direction,
                                   "action": "drop_flap", "len": len(payload)}) + "\n")
            return None
        if rng.random() < args.loss:
            counters["dropped_loss"] += 1
            logf.write(json.dumps({"t": round(now, 6), "dir": direction,
                                   "action": "drop_loss", "len": len(payload)}) + "\n")
            return None
        delay = args.delay_ms / 1000.0
        if args.jitter_ms > 0:
            delay += rng.uniform(0, args.jitter_ms) / 1000.0
        if delay > 0:
            counters["delayed"] += 1
        counters["forwarded"] += 1
        logf.write(json.dumps({"t": round(now, 6), "dir": direction,
                               "action": "forward", "delay_ms": round(delay * 1000, 3),
                               "len": len(payload)}) + "\n")
        return delay

    print(f"fault_proxy {args.listen_host}:{args.listen_port} -> "
          f"{args.target_host}:{args.target_port} loss={args.loss} "
          f"delay_ms={args.delay_ms} jitter_ms={args.jitter_ms} "
          f"flap={args.flap_down_s}s/{args.flap_period_s}s", flush=True)
    try:
        while True:
            timeout = 0.05
            if pending:
                timeout = max(0.0, min(timeout, pending[0][0] - time.monotonic()))
            r, _, _ = select.select([front, back], [], [], timeout)
            for s in r:
                now = time.monotonic() - start
                if s is front and not client_locked["flag"]:
                    data, addr = front.recvfrom(65535)
                    front.connect(addr)
                    client_locked["flag"] = True
                    print(f"fault_proxy client locked: {addr}", flush=True)
                else:
                    data = s.recv(65535)
                if s is front:
                    counters["in_client"] += 1
                    d = decide(data, "c2s", now)
                    if d is not None:
                        heapq.heappush(pending, (time.monotonic() + d, back, data))
                else:
                    counters["in_server"] += 1
                    d = decide(data, "s2c", now)
                    if d is not None and client_locked["flag"]:
                        heapq.heappush(pending, (time.monotonic() + d, front, data))
            while pending and pending[0][0] <= time.monotonic():
                _, sock_out, payload = heapq.heappop(pending)
                try:
                    sock_out.send(payload)
                except OSError:
                    pass
            logf.flush()
    except KeyboardInterrupt:
        pass
    finally:
        logf.write(json.dumps({"summary": counters}) + "\n")
        logf.close()
        print(f"fault_proxy counters: {counters}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
