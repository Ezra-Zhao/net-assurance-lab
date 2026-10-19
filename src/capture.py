"""Real packet capture on loopback, written as a classic libpcap file.

Primary path: tcpdump (if installed). Fallback path (used when tcpdump is
absent): a Python AF_INET/SOCK_RAW socket capturing every IP packet on the
host for the capture window, filtered in user space to the experiment's
UDP ports, and serialised by hand into pcap format with LINKTYPE_RAW
(DLT_RAW = 101). Both paths record bytes that actually crossed the
loopback interface during the run -- nothing here synthesises a capture.

Usage: capture.py --out file.pcap --duration 5 --ports 5005,6000
The process prints which path it took as the first stdout line:
  CAPTURE_METHOD=tcpdump  or  CAPTURE_METHOD=raw-socket
"""
import argparse
import shutil
import socket
import struct
import subprocess
import sys
import time

PCAP_MAGIC = 0xA1B2C3D4
LINKTYPE_RAW = 101


def capture_tcpdump(out: str, duration: float, ports) -> int:
    port_expr = " or ".join(f"port {p}" for p in ports)
    cmd = ["tcpdump", "-i", "lo", "-w", out, "-U", port_expr]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(duration)
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    print(f"tcpdump wrote {out}")
    return 0


def capture_raw_socket(out: str, duration: float, ports) -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_UDP)
    sock.settimeout(0.25)
    start = time.time()
    end = start + duration
    records = []
    while time.time() < end:
        try:
            pkt, _ = sock.recvfrom(65535)
        except socket.timeout:
            continue
        if len(pkt) < 20:
            continue
        ihl = (pkt[0] & 0x0F) * 4
        if len(pkt) < ihl + 8 or pkt[9] != 17:  # UDP only
            continue
        sport, dport = struct.unpack("!HH", pkt[ihl:ihl + 4])
        if sport in ports or dport in ports:
            ts = time.time()
            records.append((ts, pkt))
    with open(out, "wb") as f:
        f.write(struct.pack("<IHHiIII", PCAP_MAGIC, 2, 4, 0, 0, 65535, LINKTYPE_RAW))
        for ts, pkt in records:
            sec = int(ts)
            usec = int((ts - sec) * 1_000_000)
            f.write(struct.pack("<IIII", sec, usec, len(pkt), len(pkt)))
            f.write(pkt)
    print(f"raw-socket captured {len(records)} packets -> {out}")
    return len(records)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--duration", type=float, default=5.0)
    ap.add_argument("--ports", default="5005,6000")
    args = ap.parse_args()
    ports = [int(p) for p in args.ports.split(",") if p.strip()]

    if shutil.which("tcpdump"):
        print("CAPTURE_METHOD=tcpdump")
        return capture_tcpdump(args.out, args.duration, ports)
    print("CAPTURE_METHOD=raw-socket")
    n = capture_raw_socket(args.out, args.duration, ports)
    if n == 0:
        print("WARNING: capture contained 0 packets", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
