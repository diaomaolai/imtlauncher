# -*- coding: utf-8 -*-
"""
time_sync 单元测试（纯函数，不联网）：
NTP 应答解析、HTTP Date 头解析、偏移取值边界。

运行：
    D:\\python\\python.exe test_time_sync.py
"""

import unittest

import time_sync


class TimeSyncTest(unittest.TestCase):

    def test_parse_ntp_response(self):
        """NTP 48 字节应答 → Unix 时间戳"""
        import struct
        tx = time_sync.NTP_EPOCH + 1792544433  # 2026-10-20 17:00:33 UTC
        data = bytearray(48)
        data[40:44] = struct.pack(u"!I", tx)
        data[44:48] = struct.pack(u"!I", 0)
        self.assertAlmostEqual(
            time_sync.parse_ntp_response(bytes(data)), 1792544433.0
        )

    def test_parse_ntp_too_short(self):
        with self.assertRaises(ValueError):
            time_sync.parse_ntp_response(b"\x00" * 10)

    def test_parse_http_date(self):
        """RFC1123 Date 头 → Unix 时间戳"""
        stamp = time_sync.parse_http_date(
            u"Tue, 20 Oct 2026 12:00:52 GMT"
        )
        self.assertAlmostEqual(stamp, 1792497652.0, delta=1.0)

    def test_parse_http_date_empty(self):
        with self.assertRaises(ValueError):
            time_sync.parse_http_date(u"")

    def test_fetch_offset_fails_gracefully(self):
        """NTP 与 HTTP Date 都失败时返回 (None, None) 而不是抛异常"""
        import time_sync as ts
        old_ntp, old_http = ts.ntp_offset, ts.http_date_offset
        try:
            def boom(*_a, **_k):
                raise OSError(u"网络不可用")
            ts.ntp_offset = boom
            ts.http_date_offset = boom
            offset, source = ts.fetch_offset()
            self.assertIsNone(offset)
            self.assertIsNone(source)
        finally:
            ts.ntp_offset, ts.http_date_offset = old_ntp, old_http


if __name__ == "__main__":
    unittest.main()
