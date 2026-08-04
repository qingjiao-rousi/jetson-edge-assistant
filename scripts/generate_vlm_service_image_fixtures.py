#!/usr/bin/env python3
"""Deterministically writes synthetic, non-customer PNG panels for M7.5C."""
import hashlib, pathlib, struct, zlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "tests/fixtures/vlm-service"
def png(name, color):
    width, height = 320, 192
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            accent = 255 if (x // 20 + y // 20) % 2 == 0 else 110
            row.extend((color[0] if y < 150 else accent, color[1] if y < 150 else accent, color[2] if y < 150 else accent))
        rows.append(bytes(row))
    def chunk(kind, data): return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b"")
def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, color in (("synthetic-alarm-panel.png", (180, 30, 30)), ("synthetic-device-panel.png", (25, 100, 180))):
        path = OUT / name; path.write_bytes(png(name, color))
        print(f"{path.relative_to(ROOT)} {path.stat().st_size} {hashlib.sha256(path.read_bytes()).hexdigest()}")
if __name__ == "__main__": main()
