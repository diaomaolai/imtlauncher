# -*- coding: utf-8 -*-
"""
抢购连点逻辑单元测试（电脑端可直接运行，无需安卓环境）。

覆盖业务口径：
1. 每点一次后独立随机等 0.[X][X] 秒再点下一次（不是攒连击）；
2. 出现安全组件（填字/点选）验证弹窗 → 立即停止点击，只等待；
3. 等待期间界面刷新成订单/支付页 → 上报一次并结束（不点击）；
4. 验证弹窗关闭、回到详情页 → 继续连点；
5. 识别到「已售罄」→ 返回列表二次复核（原逻辑保持）。

运行：
    D:\\python\\python.exe test_rapid_click.py
"""

import unittest
from datetime import datetime

import flow_core
from flow_core import (
    FlowCore,
    RAPID_BUY,
    WAIT_VERIFY,
    ENTER_PRODUCT,
)

BUY = u"立即抢购"


class RapidBridge(object):
    """详情页模拟：只有买入按钮，弹窗文字由用例动态注入"""

    def __init__(self):
        self.texts = {BUY}
        self.soldout = False
        self.buy_clicks = 0
        self.back_count = 0
        # 第 N 次点击后自动弹出安全验证弹窗
        self.verify_after_clicks = None

    def is_connected(self):
        return True

    def node_center(self, keywords):
        return None

    def text_exists(self, text):
        if text in (u"已售罄", u"已售磬"):
            return self.soldout
        # 真机语义：控件文字「包含」即命中
        return any(text in t for t in self.texts)

    def any_text_exists(self, texts):
        return any(self.text_exists(text) for text in texts)

    def click_text(self, text):
        if text == BUY and BUY in self.texts:
            self.buy_clicks += 1
            if self.verify_after_clicks is not None \
                    and self.buy_clicks >= self.verify_after_clicks:
                self.verify_after_clicks = None   # 只弹一次
                self.texts.discard(BUY)
                self.texts.add(u"填字")
            return True
        return False

    def find_regex_in_px_region(self, regex, region):
        return []

    def text_exists_in_px_region(self, text, region):
        return False

    def click_text_in_px_region(self, text, region):
        return False

    def click_node_by_parts(self, keywords):
        return False

    def tap_px(self, x, y, jitter=6):
        return True

    def back(self):
        self.back_count += 1
        return True


class RapidClickTest(unittest.TestCase):

    def setUp(self):
        self._delay = flow_core.rapid_click_delay
        # 固定 0.5 秒间隔，便于用虚拟时间断言次数
        flow_core.rapid_click_delay = lambda: 0.5
        self.bridge = RapidBridge()
        self.logs = []
        self.flow = FlowCore(
            self.bridge,
            type("L", (), {"log": lambda s, m: self.logs.append(m)})(),
        )
        self.flow.reset(datetime(2026, 11, 2, 9, 0, 0))
        self.flow.state = RAPID_BUY
        self.flow._rapid_wait_left = 0.0
        self.now = datetime(2026, 11, 2, 9, 0, 0)

    def tearDown(self):
        flow_core.rapid_click_delay = self._delay

    def _run(self, seconds, dt=0.01):
        steps = int(round(seconds / dt))
        for _ in range(steps):
            self.flow.update(dt, self.now)

    def test_interval_is_independent_random(self):
        """3 秒 / 0.5 秒间隔：首点 + 约 6 次 = 7 次左右"""
        self._run(3.0)
        self.assertGreaterEqual(self.bridge.buy_clicks, 6)
        self.assertLessEqual(self.bridge.buy_clicks, 8)
        self.assertEqual(self.flow.state, RAPID_BUY)

    def test_verify_popup_stops_clicking(self):
        """出现填字弹窗后必须停手：点击次数不再增长"""
        self.bridge.verify_after_clicks = 2
        self._run(2.0)
        self.assertEqual(self.flow.state, WAIT_VERIFY)
        clicks_at_popup = self.bridge.buy_clicks
        self.assertEqual(clicks_at_popup, 2)
        # 等待期间（20 秒）绝不再点
        self._run(20.0)
        self.assertEqual(self.bridge.buy_clicks, clicks_at_popup)
        self.assertEqual(self.flow.state, WAIT_VERIFY)

    def test_order_page_reports_once_and_finishes(self):
        """等待期间刷新成订单页：只上报一次并结束"""
        reported = []
        self.flow.on_popup_success = lambda: reported.append(1)
        self.bridge.verify_after_clicks = 1
        self._run(1.0)
        self.assertEqual(self.flow.state, WAIT_VERIFY)
        # 人工完成验证 → 界面刷新成订单页
        self.bridge.texts = {u"提交订单"}
        self._run(3.0)
        self.assertTrue(self.flow.is_done)
        self.assertTrue(self.flow.success)
        self.assertEqual(len(reported), 1)
        self.assertEqual(self.bridge.buy_clicks, 1)

    def test_verify_closed_resumes_clicking(self):
        """验证弹窗关闭且回到详情页：继续连点"""
        self.bridge.verify_after_clicks = 2
        self._run(1.0)
        self.assertEqual(self.flow.state, WAIT_VERIFY)
        self.bridge.texts = {BUY, u"数量"}
        clicks = self.bridge.buy_clicks
        self._run(2.0)
        self.assertEqual(self.flow.state, RAPID_BUY)
        self.assertGreater(self.bridge.buy_clicks, clicks)

    def test_soft_hint_keeps_clicking(self):
        """「人数过多」Toast：不停止点击、不改节奏，只记日志"""
        self._run(3.0)
        before = self.bridge.buy_clicks
        self.bridge.texts.add(u"当前人数过多")
        self._run(3.0)
        self.assertEqual(self.flow.state, RAPID_BUY)
        self.assertGreater(self.bridge.buy_clicks, before)
        self.assertTrue(
            any(u"人数过多" in line for line in self.logs),
            u"未记录人数过多提示：%s" % self.logs[-5:],
        )

    def test_generic_page_text_not_treated_as_verify(self):
        """详情页正常文案『请选择年份』不能被当成验证弹窗而停手"""
        self.bridge.texts.add(u"请选择年份")
        self._run(3.0)
        self.assertEqual(self.flow.state, RAPID_BUY)
        self.assertGreater(self.bridge.buy_clicks, 3)

    def test_sold_out_goes_to_recheck(self):
        """售罄仍走二次复核"""
        self.bridge.soldout = True
        self._run(0.5)
        self.assertEqual(self.flow.state, ENTER_PRODUCT)

    def test_no_click_when_button_missing(self):
        """按钮不在（弹窗遮挡）：连续点不中后回详情重识别"""
        self.bridge.texts = set()
        self._run(2.0)
        self.assertEqual(self.bridge.buy_clicks, 0)
        self.assertEqual(self.flow.state, u"READ")


if __name__ == "__main__":
    unittest.main()
