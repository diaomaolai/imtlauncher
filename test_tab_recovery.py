# -*- coding: utf-8 -*-
"""
误触到其它 tab（首页/π社区/小茅运/我的）后的快速回位：

抢购窗口内（09:00-10:00 / 20:00-21:00）用户误触底部其它 tab 时，
流程不能停在别的页面空等，必须尽快回到：
    点 i购 → 点 经典 → 点 飞天53%vol 500ml贵州茅台酒（带杯）。

本测试覆盖：READ 态发现不在详情 → 回 NAV → 点 i购 → 点 经典。

运行：
    D:\\python\\python.exe test_tab_recovery.py
"""

import unittest
from datetime import datetime, timedelta

from flow_core import FlowCore, NAVIGATE_IGOU, READ_DETAIL

PRODUCT = u"飞天53%vol 500ml贵州茅台酒（带杯）"


class TabBridge(object):
    """五个底部 tab + i购分类页/列表页的最小模拟"""

    def __init__(self):
        self.page = u"home"
        self.clicks = []
        self.package = u"com.moutai.mall"

    def is_connected(self):
        return True

    def current_package(self):
        return self.package

    def text_exists(self, text):
        if text == u"数量":
            return self.page == u"detail"
        if text == u"经典":
            return self.page in (u"igou", u"list")
        if text == u"i购":
            return True
        return False

    def any_text_exists(self, texts):
        return any(self.text_exists(t) for t in texts)

    def node_center(self, keywords):
        if self.page == u"list" and all(
                part in PRODUCT for part in keywords):
            return (540, 1300)
        return None

    def find_exact_regex_texts(self, regex):
        return []

    def find_regex_in_px_region(self, regex, region):
        return []

    def text_exists_in_px_region(self, text, region):
        return False

    def click_text_in_px_region(self, text, region):
        self.clicks.append(text)
        if text == u"i购":
            self.page = u"igou"
            return True
        if text == u"经典":
            self.page = u"list"
            return True
        return False

    def click_text(self, text):
        return False

    def click_node_by_parts(self, keywords):
        return False

    def tap_px(self, x, y, jitter=6):
        return True

    def back(self):
        return True


class StaleProfileTest(unittest.TestCase):
    """档案区域过期/为空的兜底：不能因此把页面判成 unknown"""

    def _flow(self, bridge, controls=None):
        from device_profile import DeviceProfile
        flow = FlowCore(bridge)
        flow.reset(datetime(2026, 11, 3, 9, 0, 0))
        if controls is not None:
            flow.profile = DeviceProfile(controls=controls)
        flow.state = NAVIGATE_IGOU
        return flow

    def test_bad_igou_region_falls_back_to_full_page(self):
        """qty/igou 区域里没有 i购 → 仍能全页认出首页并点击 i购"""
        bridge = TabBridge()
        flow = self._flow(bridge, {u"igou_tab": {u"bounds": [0, 0, 10, 10]}})
        flow.update(0.2, datetime(2026, 11, 3, 9, 0, 5))
        self.assertEqual(bridge.page, u"igou")
        self.assertIn(u"i购", bridge.clicks)

    def test_wrong_foreground_package_does_not_block(self):
        """前台包名取错（桌面/自己进程）也不能卡住流程"""
        bridge = TabBridge()
        bridge.package = u"com.huawei.android.launcher"
        flow = self._flow(bridge)
        flow.on_launch_app = lambda: None
        flow.update(0.2, datetime(2026, 11, 3, 9, 0, 5))
        self.assertEqual(bridge.page, u"igou")
        self.assertIn(u"i购", bridge.clicks)


class TabRecoveryTest(unittest.TestCase):

    def test_read_on_home_returns_to_nav(self):
        """READ 态发现停在首页 → 20 拍内回 NAV"""
        bridge = TabBridge()
        flow = FlowCore(bridge)
        flow.reset(datetime(2026, 11, 3, 9, 0, 0))
        flow.state = READ_DETAIL
        now = datetime(2026, 11, 3, 9, 0, 5)
        for _ in range(20):
            flow.update(0.05, now)
        self.assertEqual(flow.state, NAVIGATE_IGOU)

    def test_nav_clicks_igou_then_jingdian(self):
        """NAV：首页点 i购，i购页点 经典（点击有 0.3 秒冷却）"""
        bridge = TabBridge()
        flow = FlowCore(bridge)
        flow.reset(datetime(2026, 11, 3, 9, 0, 0))
        flow.state = NAVIGATE_IGOU
        now = datetime(2026, 11, 3, 9, 0, 5)
        flow.update(0.3, now)
        self.assertEqual(bridge.page, u"igou")
        self.assertIn(u"i购", bridge.clicks)
        flow.update(0.3, now + timedelta(seconds=0.4))
        self.assertEqual(bridge.page, u"list")
        self.assertIn(u"经典", bridge.clicks)

    def test_other_tab_named_home_still_clicks_igou(self):
        """π社区/小茅运/我的 也含底部 i购 tab → 一律按首页处理并点击"""
        bridge = TabBridge()
        flow = FlowCore(bridge)
        flow.reset(datetime(2026, 11, 3, 9, 0, 0))
        flow.state = NAVIGATE_IGOU
        flow.update(0.3, datetime(2026, 11, 3, 9, 0, 5))
        self.assertEqual(bridge.page, u"igou")


if __name__ == "__main__":
    unittest.main()
