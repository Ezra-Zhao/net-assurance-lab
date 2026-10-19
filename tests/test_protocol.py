import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from protocol import build_malformed, build_packet, parse_packet  # noqa: E402


class TestProtocol(unittest.TestCase):
    def test_roundtrip(self):
        pkt = build_packet(42, 256, ts=123.5)
        self.assertEqual(parse_packet(pkt), (42, 123.5))

    def test_min_size(self):
        pkt = build_packet(7, 8, ts=0.0)
        self.assertEqual(len(pkt), 16)
        self.assertIsNotNone(parse_packet(pkt))

    def test_all_malformed_kinds_rejected(self):
        for kind in range(4):
            bad = build_malformed(kind, 99, 256)
            self.assertIsNone(parse_packet(bad), f"kind {kind} was accepted")

    def test_truncated_rejected(self):
        self.assertIsNone(parse_packet(build_packet(1, 256)[:10]))

    def test_bad_magic_rejected(self):
        pkt = b"NOPE" + build_packet(3, 256)[4:]
        self.assertIsNone(parse_packet(pkt))


if __name__ == "__main__":
    unittest.main()
