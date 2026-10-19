"""Prometheus exporter for net-assurance-lab (clean-room, stdlib only).

Serves the metrics of the most recent lab run in Prometheus exposition
format on ``GET /metrics`` (plus ``/healthz`` and a small index page).

Design
------
* Mode of operation is "latest run": the exporter re-reads
  ``results/latest/`` (or ``--results-dir``) on *every* scrape, so a
  fresh ``./run_lab.sh`` run is picked up with no exporter restart --
  and if a run is in progress and ``results/latest`` is swapped in at
  the end, the very next scrape reflects it. That is the live-update
  path this bench supports: the lab writes results atomically at the
  end of a run (copytree into ``results/latest``), it does not stream
  partial results, so per-scrape reload is both sufficient and honest.
* No third-party dependency: exposition text is rendered by hand and
  served with ``http.server.ThreadingHTTPServer`` (127.0.0.1 only by
  default, matching the lab's loopback-only rule).
* Every number comes from the run artifacts themselves:
    - ``<scenario>.json``        sent/echoed/lost, loss rate,
                                  throughput, RTT min/mean/p50/p95/p99/max
    - ``<scenario>.csv``         per-packet RTTs -> RTT histogram buckets
    - ``server_stats_<s>.json``  server received/valid/malformed/echoed
    - ``fault_proxy_log.jsonl``  final ``{"summary": ...}`` line ->
                                  proxy in/forwarded/dropped counters
    - ``run_meta.json``          run_id / python / platform (info metric)
  Fault-injection *configured* parameters are not stored in the run
  artifacts; they are the constants used by ``run_experiment.py`` and
  are passed here with matching defaults (``--fault-loss`` etc.). They
  are exported as a separate ``nal_fault_injection_config_*`` family,
  clearly distinct from the *measured* proxy counters, and can be
  overridden on the command line if the experiment changes.
* Missing files never fabricate values: the affected family is simply
  omitted and ``nal_exporter_results_present`` reports 0/1 per file
  group so Prometheus can alert on a stale / empty exporter.

Usage:
    python3 src/prom_exporter.py                 # 127.0.0.1:9108
    python3 src/prom_exporter.py --port 9108 --results-dir results/latest
"""

import argparse
import csv
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

SCENARIOS = ("baseline_burst", "baseline_sustained", "fault_sustained", "malformed")
RTT_STATS = ("min", "mean", "p50", "p95", "p99", "max")
# Histogram bucket boundaries in milliseconds (plus implicit +Inf).
RTT_BUCKETS_MS = (1, 5, 10, 25, 50, 100, 150, 200, 300, 500)


def _esc(value):
    """Escape a label value per the Prometheus exposition format."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _fmt(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    f = float(value)
    if f != f or f in (float("inf"), float("-inf")):
        return "+Inf" if f > 0 else "-Inf"
    return repr(f)


class MetricWriter:
    def __init__(self):
        self.lines = []
        self._declared = set()

    def declare(self, name, mtype, help_text):
        if name in self._declared:
            return
        self._declared.add(name)
        self.lines.append(f"# HELP {name} {help_text}")
        self.lines.append(f"# TYPE {name} {mtype}")

    def add(self, name, labels, value):
        v = _fmt(value)
        if v is None:
            return
        if labels:
            lab = ",".join(f'{k}="{_esc(val)}"' for k, val in labels)
            self.lines.append(f"{name}{{{lab}}} {v}")
        else:
            self.lines.append(f"{name} {v}")

    def render(self):
        return "\n".join(self.lines) + "\n"


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _proxy_summary(path):
    """Return the final {"summary": {...}} record of the proxy JSONL log."""
    summary = None
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if '"summary"' in line:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(rec.get("summary"), dict):
                        summary = rec["summary"]
    except OSError:
        return None
    return summary


def _rtt_histogram(path):
    """Count echoed per-packet RTTs (ms) from a scenario CSV into buckets."""
    counts = [0] * (len(RTT_BUCKETS_MS) + 1)  # last slot = +Inf total
    total = 0
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                raw = (row.get("rtt_ms") or "").strip()
                if not raw:
                    continue
                try:
                    rtt = float(raw)
                except ValueError:
                    continue
                total += 1
                for i, bound in enumerate(RTT_BUCKETS_MS):
                    if rtt <= bound:
                        counts[i] += 1
                        break
                else:
                    counts[-1] += 1
    except OSError:
        return None
    # Convert per-bucket counts to cumulative counts (Prometheus style).
    cumulative = []
    running = 0
    for c in counts[:-1]:
        running += c
        cumulative.append(running)
    cumulative.append(total)
    return cumulative, total


def collect(results_dir, fault_cfg):
    """Read one results directory and render the full exposition text."""
    w = MetricWriter()
    now = time.time()
    w.declare("nal_exporter_build_info", "gauge",
              "Exporter build info (value is always 1).")
    w.add("nal_exporter_build_info", [("implementation", "python-stdlib"),
                                      ("mode", "latest-run")], 1)
    w.declare("nal_exporter_last_scrape_timestamp_seconds", "gauge",
              "Unix time of this scrape's reload of the results directory.")
    w.add("nal_exporter_last_scrape_timestamp_seconds", [], now)

    meta = _load_json(os.path.join(results_dir, "run_meta.json"))
    summaries_present = 0
    run_start = None
    if meta:
        run_id = str(meta.get("run_id", "unknown"))
        w.declare("nal_run_info", "gauge",
                  "Identity of the lab run currently being exported (value is always 1).")
        w.add("nal_run_info", [("run_id", run_id),
                               ("python", meta.get("python", "unknown")),
                               ("platform", meta.get("platform", "unknown"))], 1)
        try:  # run_id format: YYYYMMDD-HHMMSS (local time of the run host)
            run_start = time.mktime(time.strptime(run_id, "%Y%m%d-%H%M%S"))
        except (ValueError, OverflowError):
            run_start = None
    if run_start is None:
        try:
            run_start = os.path.getmtime(results_dir)
        except OSError:
            run_start = None
    if run_start is not None:
        w.declare("nal_run_timestamp_seconds", "gauge",
                  "Unix time the exported run started (parsed from run_id, else results dir mtime).")
        w.add("nal_run_timestamp_seconds", [], run_start)
        w.declare("nal_results_age_seconds", "gauge",
                  "Seconds between the exported run's start and this scrape.")
        w.add("nal_results_age_seconds", [], max(0.0, now - run_start))

    for scenario in SCENARIOS:
        data = _load_json(os.path.join(results_dir, f"{scenario}.json"))
        if not data:
            continue
        summaries_present += 1
        mode = data.get("mode", "unknown")
        allp = data.get("all_packets") or {}
        valid = data.get("valid_packets") or {}
        lab = [("scenario", scenario), ("mode", mode)]

        w.declare("nal_packets_sent_total", "counter",
                  "Packets sent by the traffic generator in the exported run.")
        w.add("nal_packets_sent_total", lab, allp.get("sent"))
        w.declare("nal_packets_echoed_total", "counter",
                  "Packets echoed back and received by the generator (valid subset for malformed).")
        w.add("nal_packets_echoed_total", lab, valid.get("echoed", allp.get("echoed")))
        w.declare("nal_packets_lost_total", "counter",
                  "Packets sent but never echoed (valid subset for malformed).")
        w.add("nal_packets_lost_total", lab, valid.get("lost", allp.get("lost")))
        w.declare("nal_loss_ratio", "gauge",
                  "Lost / sent ratio of the valid packet stream, 0..1.")
        w.add("nal_loss_ratio", lab, valid.get("loss_rate", allp.get("loss_rate")))
        w.declare("nal_all_packets_loss_ratio", "gauge",
                  "Lost / sent ratio counting every datagram sent, malformed included.")
        w.add("nal_all_packets_loss_ratio", lab, allp.get("loss_rate"))

        w.declare("nal_throughput_pps", "gauge",
                  "Throughput in packets per second, by kind (send = generator send phase, echo = echoed stream).")
        w.add("nal_throughput_pps", lab + [("kind", "send")], allp.get("throughput_pps"))
        w.add("nal_throughput_pps", lab + [("kind", "echo")], allp.get("echo_throughput_pps"))
        w.declare("nal_scenario_wall_seconds", "gauge",
                  "Wall-clock seconds of the scenario's traffic phase.")
        w.add("nal_scenario_wall_seconds", lab, allp.get("wall_seconds"))
        w.declare("nal_packet_size_bytes", "gauge",
                  "Datagram payload size used by the scenario.")
        w.add("nal_packet_size_bytes", lab, data.get("packet_size_bytes"))

        rtt = valid.get("rtt_ms") or allp.get("rtt_ms") or {}
        w.declare("nal_rtt_ms", "gauge",
                  "Round-trip time in milliseconds by statistic (valid packet stream).")
        for stat in RTT_STATS:
            w.add("nal_rtt_ms", lab + [("stat", stat)], rtt.get(stat))

        w.declare("nal_malformed_sent_total", "counter",
                  "Malformed datagrams sent by the generator (malformed scenario).")
        w.add("nal_malformed_sent_total", lab, data.get("malformed_sent"))
        w.declare("nal_malformed_echoed_total", "counter",
                  "Malformed datagrams wrongly echoed by the server; must stay 0.")
        w.add("nal_malformed_echoed_total", lab, data.get("malformed_echoed"))

        hist = _rtt_histogram(os.path.join(results_dir, f"{scenario}.csv"))
        if hist:
            cumulative, total = hist
            w.declare("nal_rtt_histogram_ms", "histogram",
                      "Cumulative count of echoed packets with RTT <= le milliseconds, recomputed from the per-packet CSV.")
            bounds = [str(b) for b in RTT_BUCKETS_MS] + ["+Inf"]
            for bound, count in zip(bounds, cumulative):
                w.add("nal_rtt_histogram_ms_bucket", lab + [("le", bound)], count)
            w.add("nal_rtt_histogram_ms_count", lab, total)

        srv = _load_json(os.path.join(results_dir, f"server_stats_{scenario}.json"))
        if srv:
            w.declare("nal_server_packets_total", "counter",
                      "Server-side packet counters by kind for the scenario.")
            for kind in ("received_total", "valid", "malformed", "echoed"):
                if kind in srv:
                    w.add("nal_server_packets_total",
                          [("scenario", scenario), ("kind", kind)], srv[kind])

    proxy = _proxy_summary(os.path.join(results_dir, "fault_proxy_log.jsonl"))
    if proxy:
        w.declare("nal_fault_proxy_packets_total", "counter",
                  "Fault-proxy per-run packet counters by kind (final summary line of fault_proxy_log.jsonl).")
        for kind in ("in_client", "in_server", "dropped_loss", "dropped_flap",
                     "forwarded", "delayed"):
            if kind in proxy:
                w.add("nal_fault_proxy_packets_total", [("kind", kind)], proxy[kind])
        dropped_flap = proxy.get("dropped_flap", 0) or 0
        w.declare("nal_link_flap_detected", "gauge",
                  "1 when the proxy log shows at least one flap-window drop in the exported run, else 0.")
        w.add("nal_link_flap_detected", [], 1 if dropped_flap > 0 else 0)
        total_in = (proxy.get("in_client", 0) or 0) + (proxy.get("in_server", 0) or 0)
        if total_in:
            w.declare("nal_fault_proxy_drop_ratio", "gauge",
                      "Share of proxy-input packets dropped, by cause (loss = configured random loss, flap = link-flap windows).")
            w.add("nal_fault_proxy_drop_ratio", [("cause", "loss")],
                  (proxy.get("dropped_loss", 0) or 0) / total_in)
            w.add("nal_fault_proxy_drop_ratio", [("cause", "flap")], dropped_flap / total_in)

    if fault_cfg is not None:
        w.declare("nal_fault_injection_config", "gauge",
                  "Configured fault-injection value for the fault_sustained scenario (as run by run_experiment.py; configured, not measured).")
        for param, value in fault_cfg.items():
            w.add("nal_fault_injection_config", [("param", param)], value)
        period = fault_cfg.get("flap_period_s") or 0
        down = fault_cfg.get("flap_down_s") or 0
        w.declare("nal_fault_injection_flap_duty_ratio", "gauge",
                  "Configured flap duty cycle: flap_down_s / flap_period_s (0 when flap is disabled).")
        w.add("nal_fault_injection_flap_duty_ratio", [], (down / period) if period else 0)

    w.declare("nal_exporter_results_present", "gauge",
              "1 when the named group of run artifacts was found and parsed at scrape time.")
    w.add("nal_exporter_results_present", [("group", "scenario_summaries")],
          1 if summaries_present == len(SCENARIOS) else 0)
    w.add("nal_exporter_results_present", [("group", "run_meta")], 1 if meta else 0)
    w.add("nal_exporter_results_present", [("group", "fault_proxy_log")], 1 if proxy else 0)
    w.declare("nal_exporter_scenarios_exported", "gauge",
              "Number of scenario summaries exported at scrape time.")
    w.add("nal_exporter_scenarios_exported", [], summaries_present)
    return w.render()


def make_handler(results_dir, fault_cfg):
    class Handler(BaseHTTPRequestHandler):
        server_version = "nal-prom-exporter/1.0"

        def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler API)
            if self.path.rstrip("/") in ("/metrics",):
                body = collect(results_dir, fault_cfg).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type",
                                 "text/plain; version=0.0.4; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path.rstrip("/") == "/healthz":
                ok = os.path.isdir(results_dir)
                body = b"ok\n" if ok else b"results dir missing\n"
                self.send_response(200 if ok else 503)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path in ("/", "/index.html"):
                body = (b"<!doctype html><title>net-assurance-lab exporter</title>"
                        b"<h1>net-assurance-lab Prometheus exporter</h1>"
                        b"<p><a href=\"/metrics\">/metrics</a> &middot; "
                        b"<a href=\"/healthz\">/healthz</a></p>")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404)

        def log_message(self, fmt, *args):  # keep stdout clean by default
            if os.environ.get("NAL_EXPORTER_VERBOSE"):
                super().log_message(fmt, *args)

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind host (default 127.0.0.1, loopback only)")
    ap.add_argument("--port", type=int, default=9108)
    ap.add_argument("--results-dir",
                    default=os.path.join(ROOT, "results", "latest"),
                    help="run results directory to export (default results/latest)")
    # Configured fault parameters: defaults mirror run_experiment.py.
    ap.add_argument("--fault-loss", type=float, default=0.20)
    ap.add_argument("--fault-delay-ms", type=float, default=40.0)
    ap.add_argument("--fault-jitter-ms", type=float, default=30.0)
    ap.add_argument("--fault-flap-period-s", type=float, default=2.5)
    ap.add_argument("--fault-flap-down-s", type=float, default=0.6)
    ap.add_argument("--no-fault-config", action="store_true",
                    help="omit the nal_fault_injection_config_* family")
    args = ap.parse_args()

    fault_cfg = None
    if not args.no_fault_config:
        fault_cfg = {"loss_ratio": args.fault_loss,
                     "delay_ms": args.fault_delay_ms,
                     "jitter_ms": args.fault_jitter_ms,
                     "flap_period_s": args.fault_flap_period_s,
                     "flap_down_s": args.fault_flap_down_s}
    httpd = ThreadingHTTPServer((args.host, args.port),
                                make_handler(args.results_dir, fault_cfg))
    print(f"nal exporter on http://{args.host}:{args.port}/metrics "
          f"(results: {args.results_dir})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
