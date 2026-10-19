"""Tests for src/prom_exporter.py.

Uses a small synthetic results directory written into a temp dir --
values are fixed test inputs (not lab measurements) chosen so the
expected exposition lines can be asserted exactly. Also smoke-tests
the real results/latest directory when it exists, asserting only
shape (metric names / label presence), never specific run numbers.
"""
import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = importlib.util.spec_from_file_location(
    "prom_exporter", os.path.join(ROOT, "src", "prom_exporter.py"))
EXP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXP)

FAULT_CFG = {"loss_ratio": 0.2, "delay_ms": 40.0, "jitter_ms": 30.0,
             "flap_period_s": 2.5, "flap_down_s": 0.6}


def _write(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f)


def _scenario(sent, echoed, loss_rate, p99):
    stats = {"sent": sent, "echoed": echoed, "lost": sent - echoed,
             "loss_rate": loss_rate, "throughput_pps": 100.0,
             "echo_throughput_pps": 90.0, "wall_seconds": 1.0,
             "rtt_ms": {"min": 0.1, "mean": 1.0, "p50": 0.5,
                        "p95": 2.0, "p99": p99, "max": 3.0}}
    return {"mode": "sustained", "packet_size_bytes": 256,
            "malformed_sent": 0, "malformed_echoed": 0,
            "all_packets": stats, "valid_packets": stats}


class CollectTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="nal-results-")
        for name in EXP.SCENARIOS:
            _write(os.path.join(self.dir, f"{name}.json"),
                   _scenario(100, 90, 0.1, 7.5))
            _write(os.path.join(self.dir, f"server_stats_{name}.json"),
                   {"received_total": 90, "valid": 90, "malformed": 0,
                    "echoed": 90})
            with open(os.path.join(self.dir, f"{name}.csv"), "w",
                      encoding="utf-8") as f:
                f.write("seq,malformed_sent,echoed,rtt_ms\n")
                f.write("0,0,1,0.5\n1,0,1,12.0\n2,0,0,\n")
        _write(os.path.join(self.dir, "run_meta.json"),
               {"run_id": "20260101-120000", "python": "3.12.3",
                "platform": "linux"})
        with open(os.path.join(self.dir, "fault_proxy_log.jsonl"), "w",
                  encoding="utf-8") as f:
            f.write('{"t": 0.1, "dir": "c2s", "action": "forward"}\n')
            f.write(json.dumps({"summary": {
                "in_client": 100, "in_server": 90, "dropped_loss": 5,
                "dropped_flap": 4, "forwarded": 181, "delayed": 181}}) + "\n")
        self.text = EXP.collect(self.dir, FAULT_CFG)

    def test_core_metrics_present_with_exact_test_values(self):
        self.assertIn('nal_loss_ratio{scenario="fault_sustained",mode="sustained"} 0.1',
                      self.text)
        self.assertIn('nal_rtt_ms{scenario="baseline_burst",mode="sustained",stat="p99"} 7.5',
                      self.text)
        self.assertIn('nal_packets_sent_total{scenario="baseline_sustained",mode="sustained"} 100',
                      self.text)
        self.assertIn('nal_run_info{run_id="20260101-120000",python="3.12.3",platform="linux"} 1',
                      self.text)

    def test_proxy_and_flap_metrics(self):
        self.assertIn('nal_fault_proxy_packets_total{kind="dropped_flap"} 4', self.text)
        self.assertIn("nal_link_flap_detected 1", self.text)
        self.assertIn('nal_fault_injection_config{param="loss_ratio"} 0.2', self.text)
        self.assertIn("nal_fault_injection_flap_duty_ratio 0.24", self.text)

    def test_histogram_is_cumulative(self):
        # CSV RTTs are 0.5 and 12.0 ms: le=1 -> 1, le=25 -> 2, +Inf -> 2.
        self.assertIn('le="1"} 1', self.text)
        self.assertIn('le="25"} 2', self.text)
        self.assertIn('nal_rtt_histogram_ms_count{scenario="baseline_burst",mode="sustained"} 2',
                      self.text)

    def test_missing_dir_yields_no_fabricated_series(self):
        text = EXP.collect(os.path.join(self.dir, "does-not-exist"), FAULT_CFG)
        self.assertNotIn("nal_loss_ratio{", text)
        self.assertIn('nal_exporter_results_present{group="scenario_summaries"} 0', text)

    def test_exposition_has_help_and_type(self):
        self.assertIn("# TYPE nal_loss_ratio gauge", self.text)
        self.assertIn("# HELP nal_loss_ratio", self.text)


class HttpTest(unittest.TestCase):
    def test_metrics_endpoint_over_http(self):
        handler = EXP.make_handler(os.path.join(ROOT, "results", "latest"), FAULT_CFG)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics",
                                        timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                body = resp.read().decode("utf-8")
            self.assertIn("nal_loss_ratio", body)
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz",
                                        timeout=5) as resp:
                self.assertEqual(resp.status, 200)
        finally:
            httpd.shutdown()


if __name__ == "__main__":
    unittest.main()
