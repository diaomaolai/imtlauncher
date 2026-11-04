# -*- coding: utf-8 -*-
"""
scheduler 单元测试：时间解析 / 剩余格式化 / 下一场次 / 下一个两分钟整点。

运行：
    D:\\python\\python.exe test_scheduler.py
"""

import unittest
from datetime import datetime

from scheduler import (
    parse_target_time,
    format_remaining,
    next_slot,
    next_two_minute_mark,
)


class SchedulerTest(unittest.TestCase):

    def test_two_minute_mark_examples(self):
        """按实拍口径：14:04:05 → 14:06:00"""
        cases = [
            (datetime(2026, 11, 4, 14, 4, 5),
             datetime(2026, 11, 4, 14, 6, 0)),
            (datetime(2026, 11, 4, 14, 4, 0),
             datetime(2026, 11, 4, 14, 6, 0)),
            (datetime(2026, 11, 4, 14, 3, 30),
             datetime(2026, 11, 4, 14, 4, 0)),
            (datetime(2026, 11, 4, 14, 5, 59),
             datetime(2026, 11, 4, 14, 6, 0)),
            (datetime(2026, 11, 4, 14, 6, 0),
             datetime(2026, 11, 4, 14, 8, 0)),
        ]
        for now, expect in cases:
            self.assertEqual(next_two_minute_mark(now), expect, now)

    def test_two_minute_mark_midnight(self):
        """跨天：23:59:30 → 次日 00:00:00"""
        now = datetime(2026, 11, 4, 23, 59, 30)
        self.assertEqual(
            next_two_minute_mark(now),
            datetime(2026, 11, 5, 0, 0, 0),
        )

    def test_parse_target_time(self):
        now = datetime(2026, 11, 4, 14, 0, 0)
        self.assertEqual(
            parse_target_time(u"14:06:00", now),
            datetime(2026, 11, 4, 14, 6, 0),
        )
        # 今天已过 → 明天
        self.assertEqual(
            parse_target_time(u"13:59:00", now),
            datetime(2026, 11, 5, 13, 59, 0),
        )

    def test_format_remaining(self):
        self.assertEqual(format_remaining(3661), u"01:01:01")

    def test_next_slot(self):
        now = datetime(2026, 11, 4, 9, 7, 0)
        self.assertEqual(
            next_slot(now), datetime(2026, 11, 4, 9, 10, 0)
        )


if __name__ == "__main__":
    unittest.main()
