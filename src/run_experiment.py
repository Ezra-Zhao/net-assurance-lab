"""One-command experiment runner.

Scenarios (all on 127.0.0.1 only; a fresh echo server per scenario so
server-side stats are per-scenario too):
  1. baseline_burst      burst traffic straight to the echo server
  2. baseline_sustained  paced sustained traffic straight to the server
  3. fault_sustained     sustained traffic through fault_proxy with
                         loss=0.20, delay=40ms + jitter 30ms, and a link
                         flap of 0.6s down in every 2.5s period;
                         a pcap is captured for the whole scenario
  4. malformed           malformed + valid mix straight to the server

Outputs land in results/<run_id>/ and results/latest/ is a copy of the
most recent run. The fault report is rendered by gen_report.py.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SERVER_PORT = 5005
PROXY_PORT = 6000


def run(cmd, **kw):
    print("+ " + " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run(cmd, check=True, **kw)


class Server:
    def __init__(self, py, outdir, name):
        self.proc = subprocess.Popen(
            [py, os.path.join(HERE, "echo_server.py"), "--port", str(SERVER_PORT),
             "--stats-out", os.path.join(outdir, f"server_stats_{name}.json")])
        time.sleep(0.4)

    def stop(self):
        self.proc.send_signal(signal.SIGTERM)
        self.proc.wait(timeout=10)
        time.sleep(0.2)  # let the port drain before the next bind


def main() -> int:
    run_id = time.strftime("%Y%m%d-%H%M%S")
    outdir = os.path.join(ROOT, "results", run_id)
    os.makedirs(outdir, exist_ok=True)
    capdir = os.path.join(ROOT, "captures")
    os.makedirs(capdir, exist_ok=True)
    py = sys.executable

    meta = {"run_id": run_id, "server_port": SERVER_PORT, "proxy_port": PROXY_PORT,
            "python": sys.version.split()[0], "platform": sys.platform}

    # 1+2: baselines, direct
    for name, extra in [
        ("baseline_burst", ["--mode", "burst", "--bursts", "10",
                            "--burst-size", "200", "--burst-gap-ms", "100"]),
        ("baseline_sustained", ["--mode", "sustained", "--rate-pps", "3000",
                                "--duration-s", "3"]),
    ]:
        srv = Server(py, outdir, name)
        try:
            run([py, os.path.join(HERE, "traffic_gen.py"), *extra,
                 "--port", str(SERVER_PORT),
                 "--csv-out", os.path.join(outdir, f"{name}.csv"),
                 "--summary-out", os.path.join(outdir, f"{name}.json")])
        finally:
            srv.stop()

    # 3: fault scenario through the proxy, captured
    srv = Server(py, outdir, "fault_sustained")
    proxy_log = os.path.join(outdir, "fault_proxy_log.jsonl")
    proxy = subprocess.Popen(
        [py, os.path.join(HERE, "fault_proxy.py"),
         "--listen-port", str(PROXY_PORT), "--target-port", str(SERVER_PORT),
         "--loss", "0.20", "--delay-ms", "40", "--jitter-ms", "30",
         "--flap-period-s", "2.5", "--flap-down-s", "0.6",
         "--log-out", proxy_log])
    time.sleep(0.5)
    pcap_path = os.path.join(capdir, "fault_scenario.pcap")
    capture_log = os.path.join(outdir, "capture_log.txt")
    try:
        with open(capture_log, "w", encoding="utf-8") as clog:
            capture = subprocess.Popen(
                [py, os.path.join(HERE, "capture.py"), "--out", pcap_path,
                 "--duration", "10", "--ports", f"{SERVER_PORT},{PROXY_PORT}"],
                stdout=clog, stderr=subprocess.STDOUT)
            time.sleep(0.3)
            try:
                run([py, os.path.join(HERE, "traffic_gen.py"),
                     "--mode", "sustained", "--rate-pps", "2000", "--duration-s", "5",
                     "--port", str(PROXY_PORT),
                     "--csv-out", os.path.join(outdir, "fault_sustained.csv"),
                     "--summary-out", os.path.join(outdir, "fault_sustained.json")])
            finally:
                capture.wait(timeout=30)
    finally:
        proxy.send_signal(signal.SIGINT)
        proxy.wait(timeout=10)
        srv.stop()

    # 4: malformed mix, direct
    srv = Server(py, outdir, "malformed")
    try:
        run([py, os.path.join(HERE, "traffic_gen.py"),
             "--mode", "malformed", "--count", "200", "--rate-pps", "2000",
             "--port", str(SERVER_PORT),
             "--csv-out", os.path.join(outdir, "malformed.csv"),
             "--summary-out", os.path.join(outdir, "malformed.json")])
    finally:
        srv.stop()

    with open(os.path.join(outdir, "run_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, sort_keys=True)

    latest = os.path.join(ROOT, "results", "latest")
    if os.path.isdir(latest):
        shutil.rmtree(latest)
    shutil.copytree(outdir, latest)

    run([py, os.path.join(HERE, "gen_report.py"), "--results", outdir,
         "--pcap", pcap_path,
         "--out", os.path.join(ROOT, "sample-report", "FAULT_REPORT.md")])
    print(f"run complete: {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
