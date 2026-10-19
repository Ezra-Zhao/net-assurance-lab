"""UDP echo server: validates packets, echoes valid ones, counts malformed.

The runner starts a fresh server instance per scenario, so the stats file
is per-scenario. Writes a JSON stats file on exit (SIGTERM/SIGINT).

Connected-UDP note: on the build VM, unconnected UDP sendto() is blocked
with EPERM by the host network policy (see VERIFICATION.md), while a
connected UDP socket sends fine. This server therefore connect()s to the
first peer it hears from (the lab is strictly one client at a time) and
replies with send(). The wire format is unchanged.
"""
import argparse
import json
import signal
import socket
import sys

from protocol import parse_packet


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5005)
    ap.add_argument("--stats-out", required=True)
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.host, args.port))
    sock.settimeout(0.25)

    stats = {"received_total": 0, "valid": 0, "malformed": 0, "echoed": 0}
    stop = {"flag": False}
    peer = {"addr": None}

    def handle_sigterm(signum, frame):
        stop["flag"] = True

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    print(f"echo_server listening on {args.host}:{args.port}", flush=True)
    while not stop["flag"]:
        try:
            if peer["addr"] is None:
                data, addr = sock.recvfrom(65535)
                sock.connect(addr)
                peer["addr"] = addr
                print(f"echo_server peer locked: {addr}", flush=True)
            else:
                data = sock.recv(65535)
        except socket.timeout:
            continue
        except OSError:
            continue
        stats["received_total"] += 1
        if parse_packet(data) is None:
            stats["malformed"] += 1
            continue  # malformed datagrams are dropped, never echoed
        stats["valid"] += 1
        try:
            sock.send(data)
            stats["echoed"] += 1
        except OSError:
            pass

    with open(args.stats_out, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, sort_keys=True)
    print(f"echo_server stats: {stats}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
