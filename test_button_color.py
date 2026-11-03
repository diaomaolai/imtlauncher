# -*- coding: utf-8 -*-
"""
按钮状态识别（颜色 + 文字），不看上下位置。

规则（实拍确认）：
  · 灰色按钮：已售罄 / xx:xx投放 / xx:xx备货中 —— 不可点；
  · 黄/橙色按钮：立即抢购 —— 可点；
  · 取不到颜色（旧 APK/低版本）→ 退回纯文字判断。

运行：
    D:\\python\\python.exe test_button_color.py
"""

import unittest
from datetime import datetime

from config import SOLD_OUT_TEXTS
from flow_core import (
    FlowCore,
    READ_DETAIL,
    RAPID_BUY,
    WAIT_TIME,
)

BUY = u"立即抢购"
GRAY = (150, 150, 150)
YELLOW = (245, 170, 60)


class ColorBridge(object):
    """详情页：按钮文字 + 颜色可控"""

    def __init__(self, rgb=GRAY, button=BUY, time_text=None,
                 with_color=True):
        self.rgb = rgb
        self.button = button
        self.time_text = time_text
        self.clicks = 0
        self.backs = 0
        self.on_detail = True
        if not with_color:
            self.average_color_in_px_region = None

    def is_connected(self):
        return True

    def text_exists(self, text):
        if text in (u"立即抢购", u"立即购买"):
            return self.button in (u"立即抢购", u"立即购买")
        if text in SOLD_OUT_TEXTS:
            return self.button in SOLD_OUT_TEXTS
        return text == u"数量" and self.on_detail

    def any_text_exists(self, texts):
        return any(self.text_exists(t) for t in texts)

    def node_center(self, keywords):
        return None

    def average_color_in_px_region(self, region):
        return self.rgb

    def find_exact_regex_texts(self, regex):
        return [self.time_text] if self.time_text else []

    def find_regex_in_px_region(self, regex, region):
        return []

    def text_exists_in_px_region(self, text, region):
        return False

    def click_text_in_px_region(self, text, region):
        if text in (u"立即抢购", u"立即购买") and self.button == BUY:
            self.clicks += 1
            return True
        return False

    def click_text(self, text):
        return False

    def click_node_by_parts(self, keywords):
        return False

    def tap_px(self, x, y, jitter=6):
        return True

    def back(self):
        self.backs += 1
        self.on_detail = False
        return True


def make_flow(bridge, now):
    flow = FlowCore(bridge)
    flow.reset(datetime(2026, 11, 2, 9, 0, 0))
    flow.state = READ_DETAIL
    return flow


class ButtonColorTest(unittest.TestCase):

    def test_gray_button_wait_not_click(self):
        """灰色 + 立即抢购（禁用态）：不能点"""
        bridge = ColorBridge(rgb=GRAY, button=BUY)
        flow = make_flow(bridge, datetime(2026, 11, 2, 9, 0, 0))
        flow.update(0.05, datetime(2026, 11, 2, 9, 0, 0))
        self.assertEqual(bridge.clicks, 0)
        self.assertEqual(flow.state, READ_DETAIL)
        self.assertGreater(flow._gray_elapsed, 0.0)

    def test_yellow_button_clicks(self):
        """黄/橙 + 立即抢购：点一次进入连点"""
        bridge = ColorBridge(rgb=YELLOW, button=BUY)
        flow = make_flow(bridge, datetime(2026, 11, 2, 9, 0, 0))
        flow.update(0.05, datetime(2026, 11, 2, 9, 0, 0))
        self.assertEqual(bridge.clicks, 1)
        self.assertEqual(flow.state, RAPID_BUY)

    def test_gray_time_button_waits_for_target(self):
        """灰色 + 09:00投放：读时间、回列表等待，不点"""
        bridge = ColorBridge(rgb=GRAY, button=u"09:00投放",
                             time_text=u"09:00")
        flow = make_flow(bridge, datetime(2026, 11, 2, 8, 59, 0))
        now = datetime(2026, 11, 2, 8, 59, 0)
        # 时间要连续 2 次读数一致才采信
        flow.update(0.05, now)
        flow.update(0.05, now)
        self.assertEqual(bridge.clicks, 0)
        self.assertEqual(flow.state, WAIT_TIME)
        self.assertEqual(
            flow.session_target, datetime(2026, 11, 2, 9, 0, 0)
        )
        self.assertEqual(bridge.backs, 1)

    def test_restock_text_is_time_state(self):
        """灰色 + 09:05备货中：同样按时间处理"""
        bridge = ColorBridge(rgb=GRAY, button=u"09:05备货中",
                             time_text=u"09:05")
        flow = make_flow(bridge, datetime(2026, 11, 2, 9, 0, 0))
        now = datetime(2026, 11, 2, 9, 0, 0)
        flow.update(0.05, now)
        flow.update(0.05, now)
        self.assertEqual(bridge.clicks, 0)
        self.assertEqual(flow.state, WAIT_TIME)
        self.assertEqual(
            flow.session_target, datetime(2026, 11, 2, 9, 5, 0)
        )

    def test_no_color_capability_falls_back_to_text(self):
        """旧 APK 取不到颜色：按文字点（原逻辑）"""
        bridge = ColorBridge(rgb=None, button=BUY, with_color=False)
        flow = make_flow(bridge, datetime(2026, 11, 2, 9, 0, 0))
        flow.update(0.05, datetime(2026, 11, 2, 9, 0, 0))
        self.assertEqual(bridge.clicks, 1)
        self.assertEqual(flow.state, RAPID_BUY)

    def test_color_classification(self):
        """取色分类：灰 / 黄橙 / 未知"""
        gray = FlowCore(ColorBridge(rgb=(150, 152, 149)))
        self.assertEqual(gray._button_color_state(), u"gray")
        yellow = FlowCore(ColorBridge(rgb=(245, 170, 60)))
        self.assertEqual(yellow._button_color_state(), u"buy")
        white = FlowCore(ColorBridge(rgb=(250, 248, 246)))
        self.assertIsNone(white._button_color_state())


if __name__ == "__main__":
    unittest.main()
