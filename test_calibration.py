# -*- coding: utf-8 -*-
"""
自动校准与设备档案单元测试（电脑端可直接运行，无需安卓环境）。

运行：
    D:\\python\\python.exe test_calibration.py
"""

import json
import os
import shutil
import tempfile
import unittest

from datetime import datetime

from config import (
    YEAR_CHOICES,
    IGOU_TAB_REGION_PX,
    JINGDIAN_TAB_REGION_PX,
    YEAR_CELL_REGION_PX,
    QTY_VALUE_REGION_PX,
    BUTTON_REGION_PX,
    RUNTIME_STALL_RECAL_SECONDS,
    STALL_RECAL_AFTER,
)
from device_profile import DeviceProfile, ProfileStore
from calibration import DeviceCalibrator, NodeTree
from flow_core import FlowCore, NAVIGATE_IGOU


# ------------------------------------------------------------------
# 构造模拟节点 dump（结构参照 OPPO 真机 uiautomator dump）
# ------------------------------------------------------------------

def _node(index, parent, bounds, text=u"", desc=u"",
          class_name=u"android.view.View", clickable=False):
    return {
        u"window": 0,
        u"i": index,
        u"p": parent,
        u"c": class_name,
        u"id": u"",
        u"t": text,
        u"d": desc,
        u"ck": clickable,
        u"sc": False,
        u"b": list(bounds),
    }


YEAR_BOUNDS = {
    u"2026": (150, 1490, 435, 1590),
    u"2024": (430, 1490, 715, 1590),
    u"2023": (710, 1490, 990, 1590),
    u"2022": (150, 1610, 435, 1715),
    u"2021": (430, 1610, 715, 1715),
    u"2020": (710, 1610, 990, 1715),
    u"2019": (150, 1730, 435, 1835),
}


def build_detail_dump():
    nodes = [_node(0, -1, (0, 0, 1080, 2400))]
    # 数量行
    nodes.append(_node(16, 0, (0, 1900, 1080, 2020)))
    nodes.append(_node(13, 16, (42, 1932, 120, 1992), text=u"数量"))
    nodes.append(_node(
        14, 16, (783, 1923, 870, 2001),
        class_name=u"android.widget.Button", clickable=True
    ))
    nodes.append(_node(
        15, 16, (867, 1923, 954, 2001),
        class_name=u"android.widget.EditText", text=u"2"
    ))
    nodes.append(_node(
        17, 16, (951, 1923, 1038, 2001),
        class_name=u"android.widget.Button", clickable=True
    ))
    # 年份格
    index = 20
    for year in YEAR_CHOICES:
        nodes.append(_node(index, 0, YEAR_BOUNDS[year], text=year,
                           clickable=True))
        index += 1
    # 购买按钮
    nodes.append(_node(30, 0, (600, 2124, 1080, 2200),
                       text=u"09:00投放",
                       class_name=u"android.widget.Button"))
    return nodes


def build_home_dump():
    return [
        _node(0, -1, (0, 0, 1080, 2400)),
        _node(3, 0, (216, 2043, 432, 2161), clickable=True),
        _node(1, 3, (0, 0, 0, 0), text=u"i购"),
    ]


def build_igou_dump():
    return [
        _node(0, -1, (0, 0, 1080, 2400)),
        _node(5, 0, (40, 1080, 170, 1160), text=u"全部"),
        _node(4, 0, (202, 966, 337, 1056), text=u"经典",
              clickable=True),
        _node(6, 0, (390, 1080, 520, 1160), text=u"精品"),
    ]


def build_list_dump():
    return [
        _node(0, -1, (0, 0, 1080, 2400)),
        _node(6, 0, (40, 1080, 170, 1160), text=u"全部"),
        _node(4, 0, (202, 966, 337, 1056), text=u"经典"),
        _node(5, 0, (120, 1100, 960, 1400),
              text=u"飞天53%vol 500ml 带杯", clickable=True),
    ]


# ------------------------------------------------------------------
# Mock 桥接
# ------------------------------------------------------------------

class MockBridge(object):
    """按页面返回模拟节点，点击即切页"""

    def __init__(self):
        self.dumps = {
            u"home": build_home_dump(),
            u"igou": build_igou_dump(),
            u"list": build_list_dump(),
            u"detail": build_detail_dump(),
        }
        self.page = u"home"
        self.actions = []

    def is_connected(self):
        return True

    def _texts(self):
        return {
            (n.get(u"t") or u"") for n in self.dumps[self.page]
        }

    def text_exists(self, text):
        return any(text in value for value in self._texts())

    def node_center(self, keywords):
        for node in self.dumps[self.page]:
            text = node.get(u"t") or u""
            if all(part in text for part in keywords) \
                    and NodeTree.has_real_bounds(node):
                bounds = node[u"b"]
                return (
                    (bounds[0] + bounds[2]) // 2,
                    (bounds[1] + bounds[3]) // 2,
                )
        return None

    def click_text(self, text):
        self.actions.append((u"text", text))
        if text == u"i购":
            self.page = u"igou"
        return True

    def click_node_by_parts(self, keywords):
        self.actions.append((u"parts", tuple(keywords)))
        self.page = u"detail"
        return True

    def dump_nodes(self):
        return [dict(node) for node in self.dumps[self.page]]

    def save_screenshot(self, path):
        with open(path, u"wb") as handle:
            handle.write(b"fake-png")
        return True

    def back(self):
        if self.page == u"detail":
            self.page = u"list"
        return True


# 经典点击需要切到 list；在测试里补一个定制 mock
class MockBridgeFull(MockBridge):

    def click_text(self, text):
        self.actions.append((u"text", text))
        if text == u"i购":
            self.page = u"igou"
        elif text == u"经典":
            self.page = u"list"
        elif u"飞天" in text:
            self.page = u"detail"
        return True


# ------------------------------------------------------------------
# 测试用例
# ------------------------------------------------------------------

class TestNodeTree(unittest.TestCase):

    def test_parent_chain_and_real_bounds(self):
        tree = NodeTree(build_home_dump())
        node = tree.find_exact(u"i购")
        self.assertFalse(tree.has_real_bounds(node))
        target = tree.first_real_ancestor(node)
        self.assertEqual(tree.bounds(target), [216, 2043, 432, 2161])

    def test_extract_detail_controls(self):
        tree = NodeTree(build_detail_dump())
        cal = DeviceCalibrator.__new__(DeviceCalibrator)
        years = DeviceCalibrator._year_records(cal, tree)
        self.assertEqual(set(years), set(YEAR_CHOICES))
        value, minus, plus = DeviceCalibrator._qty_records(cal, tree)
        self.assertEqual(value[u"bounds"], [867, 1923, 954, 2001])
        self.assertEqual(minus[u"bounds"], [783, 1923, 870, 2001])
        self.assertEqual(plus[u"bounds"], [951, 1923, 1038, 2001])
        button = DeviceCalibrator._button_record(cal, tree)
        self.assertEqual(button[u"bounds"], [600, 2124, 1080, 2200])

    def test_product_record(self):
        tree = NodeTree(build_list_dump())
        cal = DeviceCalibrator.__new__(DeviceCalibrator)
        record = DeviceCalibrator._product_record(cal, tree)
        self.assertEqual(record[u"bounds"], [120, 1100, 960, 1400])


class TestCalibrationRun(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.mkdtemp()
        self.store = ProfileStore(base_dir=self.temp)
        self.bridge = MockBridgeFull()
        self.cal = DeviceCalibrator(self.bridge, self.store, logger=None)
        fake_fp = {
            u"brand": u"OPPO", u"model": u"PDSM00",
            u"android_sdk": 33, u"screen_w": 1080,
            u"screen_h": 2400, u"density": 3.0,
            u"moutai_package": u"com.moutai.mall",
            u"moutai_version": u"1.9.15",
            u"moutai_version_code": 10915,
            u"installed": True,
        }
        self.cal._build_fingerprint = lambda: (fake_fp, {}, {})

    def tearDown(self):
        shutil.rmtree(self.temp, ignore_errors=True)

    def test_full_run_saves_profile(self):
        ok, profile = self.cal.run()
        self.assertTrue(ok)
        self.assertEqual(
            profile.controls[u"igou_tab"][u"bounds"],
            [216, 2043, 432, 2161]
        )
        self.assertEqual(
            profile.controls[u"jingdian_tab"][u"bounds"],
            [202, 966, 337, 1056]
        )
        self.assertEqual(
            profile.controls[u"product_card"][u"bounds"],
            [120, 1100, 960, 1400]
        )
        self.assertEqual(len(profile.controls[u"year_cells"]), 7)
        # 4 个阶段都有截图
        self.assertEqual(len(profile.screenshots), 4)
        # 档案可被 ProfileStore 重新匹配
        loaded = self.store.find_matching(profile.fingerprint)
        self.assertIsNotNone(loaded)
        # JSON 与 TXT 均落盘
        files = os.listdir(self.store.dir)
        self.assertTrue(any(name.endswith(u".json") for name in files))
        self.assertTrue(any(name.endswith(u".txt") for name in files))

    def test_no_buy_action_in_calibration(self):
        self.cal.run()
        for kind, value in self.bridge.actions:
            self.assertNotIn(u"立即抢购", value)
            self.assertNotIn(u"立即购买", value)


class TestProfileSerialization(unittest.TestCase):

    def test_roundtrip_and_match(self):
        fingerprint = {
            u"brand": u"HUAWEI", u"model": u"GOA-AL80",
            u"android_sdk": 31, u"screen_w": 1200,
            u"screen_h": 2652, u"density": 3.25,
            u"moutai_package": u"com.moutai.mall",
            u"moutai_version": u"1.9.15",
            u"moutai_version_code": 10915,
        }
        profile = DeviceProfile(
            fingerprint=fingerprint,
            controls={u"igou_tab": {u"bounds": [1, 2, 3, 4]}},
        )
        data = json.loads(json.dumps(profile.to_dict()))
        restored = DeviceProfile.from_dict(data)
        self.assertTrue(restored.matches(fingerprint))
        changed = dict(fingerprint)
        changed[u"moutai_version"] = u"1.9.16"
        self.assertFalse(restored.matches(changed))


# ------------------------------------------------------------------
# FlowCore 档案驱动与停滞重校测试
# ------------------------------------------------------------------

class FlowMockBridge(object):
    """全部查找返回空，记录区域参数"""

    def __init__(self):
        self.region_calls = []
        self.taps = []

    def is_connected(self):
        return True

    def text_exists_in_px_region(self, text, region):
        self.region_calls.append((text, tuple(region)))
        return False

    def click_text_in_px_region(self, text, region):
        return False

    def text_exists(self, text):
        return False

    def click_text(self, text):
        return False

    def find_regex_in_px_region(self, regex, region):
        return []

    def tap_px(self, x, y, jitter_px=6):
        self.taps.append((x, y))
        return False

    def node_center(self, keywords):
        return None

    def click_node_by_parts(self, keywords):
        return False

    def back(self):
        return False

    def dump_nodes(self):
        return []

    def save_screenshot(self, path):
        return False


def build_runtime_profile():
    return DeviceProfile(
        fingerprint={},
        controls={
            u"igou_tab": {
                u"bounds": [110, 2250, 490, 2420],
                u"center": [300, 2335],
            },
            u"jingdian_tab": {
                u"bounds": [160, 1020, 420, 1160],
                u"center": [290, 1090],
            },
            u"year_cells": {
                u"2026": {
                    u"bounds": [170, 1640, 480, 1760],
                    u"center": [325, 1700],
                },
            },
            u"qty_value": {
                u"bounds": [950, 2120, 1060, 2230],
                u"center": [1005, 2175],
            },
            u"qty_plus": {
                u"bounds": [1055, 2120, 1165, 2230],
                u"center": [1110, 2175],
            },
            u"action_button": {
                u"bounds": [660, 2350, 1200, 2440],
                u"center": [930, 2395],
            },
        },
    )


class TestProfileDrivenFlow(unittest.TestCase):

    def test_region_prefers_profile_bounds(self):
        flow = FlowCore(FlowMockBridge())
        flow.profile = build_runtime_profile()
        self.assertEqual(
            flow._region(u"igou_tab", IGOU_TAB_REGION_PX),
            (110, 2250, 490, 2420)
        )
        self.assertEqual(
            flow._region(u"jingdian_tab", JINGDIAN_TAB_REGION_PX),
            (160, 1020, 420, 1160)
        )
        self.assertEqual(
            flow._region(
                u"year_cells",
                YEAR_CELL_REGION_PX[u"2026"],
                sub_key=u"2026",
            ),
            (170, 1640, 480, 1760)
        )
        self.assertEqual(
            flow._region(u"qty_value", QTY_VALUE_REGION_PX),
            (950, 2120, 1060, 2230)
        )
        self.assertEqual(
            flow._button_region(),
            (660, 2350, 1200, 2440)
        )
        self.assertEqual(flow._profile_center(u"qty_plus"), (1110, 2175))

    def test_region_falls_back_to_legacy_px(self):
        flow = FlowCore(FlowMockBridge())
        self.assertEqual(
            flow._region(u"igou_tab", IGOU_TAB_REGION_PX),
            IGOU_TAB_REGION_PX
        )
        self.assertEqual(flow._button_region(), BUTTON_REGION_PX)
        self.assertIsNone(flow._profile_center(u"qty_plus"))


class TestStallRecalibration(unittest.TestCase):

    def test_nav_stall_sets_recal_flag(self):
        bridge = FlowMockBridge()
        flow = FlowCore(bridge)
        flow.reset(datetime.now())
        flow._goto(NAVIGATE_IGOU, u"导航中…")
        # 每 1 秒计一次，连续 STALL_RECAL_AFTER 次才重校
        need_seconds = RUNTIME_STALL_RECAL_SECONDS * STALL_RECAL_AFTER
        ticks = int(need_seconds / 0.3) + 4
        for _ in range(ticks):
            flow.update(0.3, datetime.now())
        self.assertTrue(flow.needs_recalibration)

    def test_stall_counter_resets_on_goto(self):
        flow = FlowCore(FlowMockBridge())
        flow._goto(NAVIGATE_IGOU, u"导航中…")
        # 1.2 秒 → 计 1 次
        flow._tick_stall(0.6)
        flow._tick_stall(0.6)
        self.assertEqual(flow._stall_count, 1)
        flow._goto(NAVIGATE_IGOU, u"重新导航…")
        self.assertEqual(flow._stall_count, 0)
        self.assertFalse(flow.needs_recalibration)

    def test_freeze_jump_counts_as_three(self):
        """冻结跳时（dt=60）按 3 次封顶计：立即重校，但不记 60 次"""
        flow = FlowCore(FlowMockBridge())
        flow._goto(NAVIGATE_IGOU, u"导航中…")
        flow._tick_stall(60.0)
        self.assertTrue(flow.needs_recalibration)
        self.assertEqual(flow._stall_count, 3)


if __name__ == u"__main__":
    unittest.main(verbosity=2)
