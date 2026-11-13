# -*- coding: utf-8 -*-
"""
按钮翻转探针的仿真测试（电脑端可直接运行，不需要安卓）。

用一台「假手机」模拟：首页 → i购 → 经典 → 列表 → 详情，并在指定时刻
把按钮从灰变橙，验证探针能：
   1. 自己导航到详情页；
   2. 采样并识别出翻转；
   3. 把结论写进结果文件。

运行：
    python test_flip_probe.py
"""

import os
import time
import unittest
from datetime import datetime, timedelta

from config import PRODUCT_FULL_TEXTS, BUY_NOW_TEXTS, YEAR_RED_MIN
from flip_probe import FlipProbe, _redness

GRAY = (200, 200, 200)
ORANGE = (230, 120, 50)


class FakePhone(object):
    """可控的「手机」：页面靠点击推进，按钮颜色按时间翻转。"""

    def __init__(self, flip_at):
        self.page = u"home"
        self.flip_at = flip_at
        self.is_connected_flag = True

    def is_connected(self):
        return self.is_connected_flag

    def _texts(self):
        if self.page == u"home":
            return {u"i购"}
        if self.page == u"igou":
            return {u"i购", u"经典"}
        if self.page == u"list":
            return {u"i购", u"经典"} | set(PRODUCT_FULL_TEXTS)
        return {u"数量", u"i购", u"立即购买"}

    def text_exists(self, text):
        return any(text in t for t in self._texts())

    def any_text_exists(self, texts):
        return any(self.text_exists(t) for t in texts)

    def text_exists_in_px_region(self, text, region):
        return self.text_exists(text)

    def node_center(self, keywords):
        if self.page == u"list":
            for name in PRODUCT_FULL_TEXTS:
                if all(k in name for k in keywords):
                    return (313, 1807)
        return None

    def click_text(self, text):
        return self._click(text)

    def click_text_in_px_region(self, text, region):
        return self._click(text)

    def _click(self, text):
        if text == u"i购" and self.page == u"home":
            self.page = u"igou"
            return True
        if text == u"经典" and self.page == u"igou":
            self.page = u"list"
            return True
        if text in PRODUCT_FULL_TEXTS and self.page == u"list":
            self.page = u"detail"
            return True
        return False

    def find_exact_regex_texts(self, regex):
        return []

    def find_regex_in_px_region(self, regex, region):
        return []

    def average_color_in_px_region(self, region):
        return self.current_color()

    def max_red_in_regions(self, regions):
        return [self.current_color() for _ in regions]

    def current_color(self):
        return ORANGE if datetime.now() >= self.flip_at else GRAY

    def tap_px(self, x, y, jitter=6):
        return True

    def back(self):
        if self.page == u"detail":
            self.page = u"list"
        return True

    def dump_nodes(self):
        return []


class RednessTest(unittest.TestCase):

    def test_colors(self):
        self.assertEqual(_redness(None), -1)
        self.assertEqual(_redness(GRAY), 0)
        self.assertGreaterEqual(_redness(ORANGE), YEAR_RED_MIN)


class FlipProbeTest(unittest.TestCase):

    def test_navigate_detect_and_write(self):
        flip_at = datetime.now() + timedelta(seconds=1.2)
        phone = FakePhone(flip_at)
        probe = FlipProbe(
            phone, None, flip_at,
            lead=0.5, tail=1.5, sample_gap=0.05, nav_pause=0.02,
        )
        probe.run()          # 直接跑，不另起线程，便于断言

        self.assertEqual(phone.page, u"detail", u"应该已导航到详情页")
        self.assertTrue(probe.result_path, u"应该写出结果文件")
        self.assertTrue(os.path.exists(probe.result_path))

        with open(probe.result_path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn(u"【会】", text, u"应判定为会翻转：\n%s" % text)

        csv_path = probe.result_path[:-4] + u".csv"
        self.assertTrue(os.path.exists(csv_path))
        with open(csv_path, encoding="utf-8") as handle:
            lines = handle.read().strip().split("\n")
        self.assertGreater(len(lines), 5, u"采样点太少：%d" % len(lines))

    def test_no_flip_reports_negative(self):
        # 翻转时刻设到窗口之后：整场都应该是灰的
        far = datetime.now() + timedelta(seconds=30)
        phone = FakePhone(far)
        probe = FlipProbe(
            phone, None, datetime.now() + timedelta(seconds=0.6),
            lead=0.2, tail=1.0, sample_gap=0.05, nav_pause=0.02,
        )
        probe.run()

        self.assertTrue(probe.result_path)
        with open(probe.result_path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn(u"没有自己翻转", text, text)

    def test_abort_when_a11y_off(self):
        flip_at = datetime.now() + timedelta(seconds=1)
        phone = FakePhone(flip_at)
        phone.is_connected_flag = False
        probe = FlipProbe(phone, None, flip_at, lead=0.2, tail=0.5)
        probe.run()
        self.assertEqual(probe.result_path, u"", u"无障碍关闭时不应写结果")


if __name__ == "__main__":
    unittest.main()
