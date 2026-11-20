# -*- coding: utf-8 -*-
"""
风控自愈的单元测试（电脑端可直接运行，不需要安卓）。

覆盖：
1. 两场窗口判定（09:00–10:00、20:00–21:00）的边界；
2. 「被杀」判定：风控弹窗文字 / 前台包名 / 白名单不误判；
3. 冷却重拉流程：冷却 → 拉起 → 通知状态机强制回 NAV；
4. 状态机被强制回 NAV 时，临时状态确实被清干净。

运行：
    python test_risk_guard.py
"""

import unittest
from datetime import datetime

import risk_guard
from config import RISK_KILL_TEXTS
from flow_core import FlowCore, NAVIGATE_IGOU
from risk_guard import RiskGuardian, in_sale_window

MOUTAI = u"com.moutai.mall"
MORNING = datetime(2026, 11, 14, 9, 30, 0)
EVENING = datetime(2026, 11, 14, 20, 30, 0)


class FakeStop(object):
    """把 Event.wait 变成瞬间返回，测试里不真的睡 25 秒。"""

    def __init__(self):
        self.called = False

    def set(self):
        self.called = True

    def is_set(self):
        return False

    def wait(self, _timeout):
        return False


class FakeBridge(object):
    """可控的「手机」：文字与前台包名都由用例设定。"""

    def __init__(self, texts=None, package=MOUTAI):
        self.texts = set(texts or [])
        self.package = package

    def any_text_exists(self, texts):
        return any(t in self.texts for t in texts)

    def text_exists(self, text):
        return text in self.texts

    def current_package(self):
        return self.package

    def is_connected(self):
        return True


class FakeFlow(object):
    """只记录 force_restart_to_nav 是否被调用。"""

    def __init__(self):
        self.is_done = False
        self.force_calls = []

    def server_now(self):
        return MORNING

    def force_restart_to_nav(self, reason):
        self.force_calls.append(reason)


class SaleWindowTest(unittest.TestCase):

    def test_morning_window(self):
        self.assertFalse(in_sale_window(datetime(2026, 11, 14, 8, 59, 59)))
        self.assertTrue(in_sale_window(datetime(2026, 11, 14, 9, 0, 0)))
        self.assertTrue(in_sale_window(datetime(2026, 11, 14, 9, 59, 59)))
        self.assertTrue(in_sale_window(datetime(2026, 11, 14, 10, 0, 0)))
        self.assertFalse(in_sale_window(datetime(2026, 11, 14, 10, 0, 1)))

    def test_evening_window(self):
        self.assertFalse(in_sale_window(datetime(2026, 11, 14, 19, 59, 59)))
        self.assertTrue(in_sale_window(datetime(2026, 11, 14, 20, 0, 0)))
        self.assertTrue(in_sale_window(datetime(2026, 11, 14, 21, 0, 0)))
        self.assertFalse(in_sale_window(datetime(2026, 11, 14, 21, 0, 1)))

    def test_midday_not_in_window(self):
        self.assertFalse(in_sale_window(datetime(2026, 11, 14, 15, 0, 0)))


class DetectTest(unittest.TestCase):

    def _guardian(self, texts=None, package=MOUTAI):
        bridge = FakeBridge(texts, package)
        return RiskGuardian(bridge, FakeFlow(), None, lambda: True)

    def test_risk_dialog_detected(self):
        text = list(RISK_KILL_TEXTS)[0]
        self.assertIsNotNone(self._guardian([text]).detect())

    def test_normal_app_not_detected(self):
        self.assertIsNone(self._guardian([], MOUTAI).detect())

    def test_launcher_means_killed(self):
        reason = self._guardian([], u"com.huawei.android.launcher").detect()
        self.assertIsNotNone(reason)
        self.assertIn(u"已退出", reason)

    def test_own_app_is_ignored(self):
        self.assertIsNone(
            self._guardian([], u"org.personal.imtlauncher").detect()
        )

    def test_systemui_is_ignored(self):
        self.assertIsNone(self._guardian([], u"com.android.systemui").detect())

    def test_unknown_package_does_not_judge(self):
        """旧 APK 取不到包名时不能误判"""
        self.assertIsNone(self._guardian([], None).detect())


class RecoverTest(unittest.TestCase):

    def test_cooldown_then_launch_then_nav(self):
        bridge = FakeBridge([list(RISK_KILL_TEXTS)[0]], u"com.huawei.android.launcher")
        flow = FakeFlow()
        launches = []
        guardian = RiskGuardian(
            bridge, flow, None, lambda: launches.append(1),
            cooldown=0, max_relaunch=6,
        )
        guardian._stop = FakeStop()

        ok = guardian.recover(u"测试")

        self.assertTrue(ok)
        self.assertEqual(len(launches), 1, u"应该重拉一次")
        self.assertEqual(len(flow.force_calls), 1, u"应该通知状态机回 NAV")
        self.assertEqual(guardian.relaunch_count, 1)

    def test_no_launch_after_flow_done(self):
        bridge = FakeBridge([], MOUTAI)
        flow = FakeFlow()
        flow.is_done = True
        launches = []
        guardian = RiskGuardian(
            bridge, flow, None, lambda: launches.append(1), cooldown=0
        )
        guardian._stop = FakeStop()

        self.assertFalse(guardian.recover(u"测试"))
        self.assertEqual(launches, [])


class FlowResetTest(unittest.TestCase):
    """状态机被强制拉回 NAV 时，临时状态必须清干净。"""

    def test_force_restart_clears_state(self):
        flow = FlowCore(FakeBridge(), None)
        flow.profile = None
        flow._preheated = True
        flow._soldout_pending = True
        flow._rapid_click_count = 7
        flow._rapid_reenter_rounds = 3
        flow._rapid_reenter_limit = 12

        flow.force_restart_to_nav(u"测试")

        self.assertEqual(flow.state, NAVIGATE_IGOU)
        self.assertFalse(flow._preheated)
        self.assertFalse(flow._soldout_pending)
        self.assertEqual(flow._rapid_click_count, 0)
        self.assertEqual(flow._rapid_reenter_rounds, 0)
        self.assertEqual(flow._risk_kills, 1)

    def test_killed_twice_slows_click_delay(self):
        """被杀过之后连点间隔要落在放慢区间内"""
        from config import RISK_SLOW_CLICK_MIN, RISK_SLOW_CLICK_MAX
        flow = FlowCore(FakeBridge(), None)
        flow.profile = None
        for value in [flow.click_delay() for _ in range(40)]:
            self.assertTrue(0.0 <= value <= 0.09)

        flow._risk_kills = 1
        for value in [flow.click_delay() for _ in range(40)]:
            self.assertGreaterEqual(value, RISK_SLOW_CLICK_MIN - 1e-9)
            self.assertLessEqual(value, RISK_SLOW_CLICK_MAX + 1e-9)


if __name__ == "__main__":
    unittest.main()
