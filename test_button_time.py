# -*- coding: utf-8 -*-
"""
按钮时间识别：排除「每日09:00、20:00投放」说明文字的干扰。

实拍详情页：
  · 按钮上方是一整段说明文字「每日09:00、20:00投放」，
    其中 20:00 紧跟"投放"，会被前瞻正则命中；
  · 按钮本身是灰色圆角框，文字整段就是「09:00投放」。

代码因此改成"整段精确匹配 + 取最下方节点"：
  · 说明文字不是整段 xx:xx投放 → 不命中；
  · 按钮是整段 → 命中，捕获分组取到 09:00。

运行：
    D:\\python\\python.exe test_button_time.py
"""

import re
import unittest
from datetime import datetime

from config import BUTTON_TIME_EXACT_REGEX
from flow_core import FlowCore
from calibration import DeviceCalibrator, NodeTree


class FakeBridge(object):
    """详情页：同时存在说明段落和按钮"""

    def __init__(self):
        self.explanation = u"每日09:00、20:00投放"
        self.button = u"09:00投放"
        self.backs = 0
        self.on_detail = True

    def is_connected(self):
        return True

    def text_exists(self, text):
        if text == u"数量":
            return self.on_detail
        return text in (self.explanation, self.button)

    def any_text_exists(self, texts):
        return any(self.text_exists(t) for t in texts)

    def node_center(self, keywords):
        return None

    def find_exact_regex_texts(self, regex):
        """模拟新 APK：整段匹配，只有按钮命中"""
        pattern = re.compile(regex)
        out = []
        for text in (self.explanation, self.button):
            matcher = pattern.fullmatch(text)
            if matcher is not None:
                out.append(matcher.group(1))
        return out

    def find_regex_in_px_region(self, regex, region):
        """模拟旧 API：区域里同时读到说明文字和按钮（20:00 会干扰）"""
        return [u"20:00", u"09:00"]

    def text_exists_in_px_region(self, text, region):
        return False

    def click_text_in_px_region(self, text, region):
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


class ButtonTimeTest(unittest.TestCase):

    def test_exact_match_excludes_explanation(self):
        """整段匹配只认按钮的 09:00，不认说明文字里的 20:00"""
        flow = FlowCore(FakeBridge())
        self.assertEqual(flow._button_time_hits(), [u"09:00"])

    def test_old_apk_falls_back_to_region(self):
        """旧 APK 没有整段匹配能力时，退回区域扫描（已知限制）"""
        bridge = FakeBridge()
        bridge.find_exact_regex_texts = None
        flow = FlowCore(bridge)
        self.assertEqual(flow._button_time_hits(), [u"20:00", u"09:00"])

    def test_handle_sale_time_targets_09(self):
        """读到 09:00 后目标应设为 09:00，而不是说明文字里的 20:00"""
        bridge = FakeBridge()
        flow = FlowCore(bridge)
        flow.reset(datetime(2026, 11, 2, 9, 0, 0))
        now = datetime(2026, 11, 2, 8, 59, 0)
        self.assertTrue(flow._handle_sale_time(u"09:00", now))
        self.assertEqual(
            flow.session_target, datetime(2026, 11, 2, 9, 0, 0)
        )
        self.assertEqual(bridge.backs, 1)

    def test_restock_prefix_is_matched(self):
        """实拍格式「补货中 ~ 09:25投放」：整段匹配要能取到 09:25"""
        bridge = FakeBridge()
        bridge.button = u"补货中 ~ 09:25投放"
        flow = FlowCore(bridge)
        self.assertEqual(flow._button_time_hits(), [u"09:25"])

    def test_restock_waits_for_target(self):
        """读到补货时间 09:25 后按未来时间等待"""
        bridge = FakeBridge()
        bridge.button = u"补货中 ~ 09:25投放"
        flow = FlowCore(bridge)
        flow.reset(datetime(2026, 11, 3, 9, 25, 0))
        now = datetime(2026, 11, 3, 9, 20, 0)
        self.assertTrue(flow._handle_sale_time(u"09:25", now))
        self.assertEqual(
            flow.session_target, datetime(2026, 11, 3, 9, 25, 0)
        )

    def test_explanation_still_rejected(self):
        """补上前缀后，说明文字「每日09:00、20:00投放」仍不被整段命中"""
        pattern = re.compile(BUTTON_TIME_EXACT_REGEX)
        self.assertIsNone(pattern.fullmatch(u"每日09:00、20:00投放"))
        self.assertEqual(pattern.fullmatch(u"09:00投放").group(1), u"09:00")
        self.assertEqual(
            pattern.fullmatch(u"补货中 ~ 09:25投放").group(1), u"09:25"
        )

    def test_calibration_records_button_not_explanation(self):
        """校准采集按钮 bounds 时不能把说明段落当成按钮"""
        nodes = [
            {"window": 0, "i": 0, "p": -1, "c": u"", "id": u"", "t": u"",
             "d": u"", "ck": False, "sc": False, "b": [0, 0, 1080, 2400]},
            {"window": 0, "i": 1, "p": 0, "c": u"", "id": u"",
             "t": u"每日09:00、20:00投放", "d": u"", "ck": False,
             "sc": False, "b": [100, 2050, 980, 2100]},
            {"window": 0, "i": 2, "p": 0, "c": u"", "id": u"",
             "t": u"09:00投放", "d": u"", "ck": True,
             "sc": False, "b": [620, 2230, 860, 2300]},
        ]
        tree = NodeTree(nodes)
        cal = DeviceCalibrator.__new__(DeviceCalibrator)
        record = DeviceCalibrator._button_record(cal, tree)
        self.assertEqual(record[u"bounds"], [620, 2230, 860, 2300])
        self.assertEqual(
            DeviceCalibrator._button_state_text(cal, tree), u"投放时间 09:00"
        )


if __name__ == "__main__":
    unittest.main()
