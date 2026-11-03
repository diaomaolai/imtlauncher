# -*- coding: utf-8 -*-
"""
桌面/其他 APP 的恢复：误触 Home 或切到微信时，把 i茅台 拉回前台。

实拍场景：用户设定时间后在桌面静止等待；或抢购中误触 Home。
此时无障碍树里全是桌面图标（时钟/备忘录/微信…），不能在桌面里
误找 i购/经典；应按前台包名判断"不在 i茅台"，限频拉起。

运行：
    D:\\python\\python.exe test_launcher_recovery.py
"""

import unittest
from datetime import datetime, timedelta

from flow_core import FlowCore, READ_DETAIL


class LauncherBridge(object):
    def __init__(self, package):
        self.package = package
        self.launches = 0

    def is_connected(self):
        return True

    def current_package(self):
        return self.package

    def text_exists(self, text):
        return False

    def any_text_exists(self, texts):
        return False

    def node_center(self, keywords):
        return None

    def find_exact_regex_texts(self, regex):
        return []

    def find_regex_in_px_region(self, regex, region):
        return []

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
        return True


def make_flow(bridge):
    flow = FlowCore(bridge)
    flow.reset(datetime(2026, 11, 3, 9, 0, 0))
    flow.on_launch_app = lambda: setattr(
        bridge, "launches", bridge.launches + 1
    )
    flow.state = READ_DETAIL
    return flow


class LauncherRecoveryTest(unittest.TestCase):

    def test_launcher_triggers_launch(self):
        """前台是华为桌面：拉起 i茅台，不做任何点击"""
        bridge = LauncherBridge(u"com.huawei.android.launcher")
        flow = make_flow(bridge)
        now = datetime(2026, 11, 3, 9, 0, 0)
        flow.update(0.05, now)
        self.assertEqual(bridge.launches, 1)
        self.assertEqual(flow.state, READ_DETAIL)

    def test_launch_is_throttled(self):
        """1.5 秒内不重复拉起"""
        bridge = LauncherBridge(u"com.huawei.android.launcher")
        flow = make_flow(bridge)
        now = datetime(2026, 11, 3, 9, 0, 0)
        flow.update(0.05, now)
        flow.update(0.05, now + timedelta(seconds=0.2))
        self.assertEqual(bridge.launches, 1)
        flow.update(0.05, now + timedelta(seconds=1.6))
        self.assertEqual(bridge.launches, 2)

    def test_in_moutai_does_not_launch(self):
        """前台已是 i茅台：不拉起，正常走状态机"""
        bridge = LauncherBridge(u"com.moutai.mall")
        flow = make_flow(bridge)
        flow.update(0.05, datetime(2026, 11, 3, 9, 0, 0))
        self.assertEqual(bridge.launches, 0)

    def test_old_apk_without_package_is_ignored(self):
        """旧 APK 没有 current_package：不误判、不影响原逻辑"""
        bridge = LauncherBridge(None)
        bridge.current_package = None
        flow = make_flow(bridge)
        flow.update(0.05, datetime(2026, 11, 3, 9, 0, 0))
        self.assertEqual(bridge.launches, 0)


if __name__ == "__main__":
    unittest.main()
