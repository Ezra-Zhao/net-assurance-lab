"""Wire protocol for net-assurance-lab (clean-room, hand-written).

Frame layout (UDP payload):
    bytes 0-3   magic b"NAL1"
    bytes 4-7   sequence number, unsigned big-endian uint32
    bytes 8-15  sender timestamp, big-endian float64 (seconds, time.time())
    bytes 16+   filler payload (byte value = seq % 251), total length = size

A datagram is *malformed* at the application layer when any of these hold:
wrong magic, shorter than the 16-byte header, or a declared length that
does not match the actual datagram length. The echo server counts malformed
datagrams separately and never echoes them.
"""
import struct

MAGIC = b"NAL1"
HEADER = struct.Struct("!4sId")
HEADER_LEN = HEADER.size  # 16


def build_packet(seq: int, size: int = 256, ts: float = 0.0) -> bytes:
    if size < HEADER_LEN:
        size = HEADER_LEN
    filler_len = size - HEADER_LEN
    filler = bytes([seq % 251]) * filler_len
    return HEADER.pack(MAGIC, seq, ts) + filler


def parse_packet(data: bytes):
    """Return (seq, ts) for a valid packet, or None if malformed."""
    if len(data) < HEADER_LEN:
        return None
    magic, seq, ts = HEADER.unpack(data[:HEADER_LEN])
    if magic != MAGIC:
        return None
    # filler integrity: every filler byte must equal seq % 251
    expect = seq % 251
    for b in data[HEADER_LEN:]:
        if b != expect:
            return None
    return seq, ts


def build_malformed(kind: int, seq: int, size: int = 256) -> bytes:
    """Deterministic malformed variants, cycled by `kind % 4`."""
    k = kind % 4
    if k == 0:  # bad magic
        return b"XXXX" + build_packet(seq, size)[4:]
    if k == 1:  # truncated header
        return build_packet(seq, size)[:8]
    if k == 2:  # corrupted filler (breaks integrity check)
        pkt = bytearray(build_packet(seq, size))
        if len(pkt) > HEADER_LEN + 4:
            pkt[HEADER_LEN + 4] ^= 0xFF
        return bytes(pkt)
    # random garbage of plausible length
    import random
    rng = random.Random(seq * 2654435761 & 0xFFFFFFFF)
    return bytes(rng.getrandbits(8) for _ in range(size))
