# -*- coding: utf-8 -*-
"""
自动重进与数量兜底宽限单元测试（电脑端可直接运行，无需安卓环境）。

覆盖业务口径：
1. 页面加载时按钮区先渲染、规格/数量延迟：宽限内不兜底放行，
   坚持等规格，最终把数量从 2 改成 6（修复"跳过改数量"）；
2. 连点达到随机阈值（本测试固定 5）：自动 back 返回上一层再
   重进详情，状态进 ENTER，重进轮次 +1（替代手动返回）；
3. 重进阈值未到时：保持 RAPID 继续连点，不提前返回。

运行：
    D:\\python\\python.exe test_auto_reenter.py
"""

import unittest
from datetime import datetime, timedelta

import flow_core
from flow_core import (
    FlowCore,
    SELECT_YEAR,
    SELECT_QTY,
    READ_DETAIL,
    RAPID_BUY,
    ENTER_PRODUCT,
    WAIT_TIME,
    WAIT_DETAIL,
)
from config import (
    QTY_REGEX, QTY_TARGET, QTY_PLUS_CENTER_PX,
    YEAR_CHOICES, DETAIL_DEFAULT_YEAR,
)

YEAR = u"2026"
BUY = u"立即抢购"


class DetailBridge(object):
    """可控详情页：按钮区可先于规格区渲染，重进时切到列表。"""

    def __init__(self):
        # 规格区（年份/数量）是否已渲染；按钮区默认先就绪
        self.spec_ready = False
        self.button_ready_flag = True
        self.value = 2
        self.buy_clicks = 0
        self.back_count = 0
        self.plus_taps = 0
        self.year_clicks = 0
        self.page = u"detail"

    def is_connected(self):
        return True

    def node_center(self, keywords):
        return None

    def text_exists(self, text):
        # _current_page 判 detail 靠"数量"；按钮文字也要能被全局找到
        if text == u"数量":
            return self.spec_ready
        if text in (u"立即抢购", u"立即购买"):
            return self.button_ready_flag
        return False

    def any_text_exists(self, texts):
        return any(self.text_exists(t) for t in texts)

    def text_exists_in_px_region(self, text, region):
        if text in YEAR_CHOICES and self.spec_ready:
            return True
        if text in (u"立即抢购", u"立即购买") and self.button_ready_flag:
            return True
        return False

    def click_text_in_px_region(self, text, region):
        if text in YEAR_CHOICES:
            self.year_clicks += 1
        return self.text_exists_in_px_region(text, region)

    def find_regex_in_px_region(self, regex, region):
        if regex == QTY_REGEX and self.spec_ready:
            return [str(self.value)]
        return []

    def tap_px(self, x, y, jitter=6):
        self.plus_taps += 1
        self.value += 1
        return True

    def click_text(self, text):
        if text in (u"立即抢购", u"立即购买") and self.button_ready_flag:
            self.buy_clicks += 1
            return True
        return False

    def click_node_by_parts(self, keywords):
        return False

    def back(self):
        self.back_count += 1
        # 真机语义：详情 back 退回列表
        if self.page == u"detail":
            self.page = u"list"
        return True


class AutoReenterTest(unittest.TestCase):

    def setUp(self):
        self._delay = flow_core.rapid_click_delay
        self._reenter = flow_core.rapid_reenter_count
        flow_core.rapid_click_delay = lambda: 0.0
        flow_core.rapid_reenter_count = lambda: 5
        self.bridge = DetailBridge()
        self.logs = []
        self.flow = FlowCore(
            self.bridge,
            type("L", (), {"log": lambda s, m: self.logs.append(m)})(),
        )
        self.flow.reset(datetime(2026, 11, 2, 9, 0, 0))
        # 明确选非默认年份（2026），保证流程走"点击年份格"分支
        self.flow.year_target = u"2026"
        self.now = datetime(2026, 11, 2, 9, 0, 0)

    def tearDown(self):
        flow_core.rapid_click_delay = self._delay
        flow_core.rapid_reenter_count = self._reenter

    def _goto_year(self):
        self.flow._goto(SELECT_YEAR, u"进入详情…")

    def test_preheat_enters_detail_then_backs_to_wait(self):
        """开售前 45~90 秒：先进详情预热，加载完回列表，且只预热一次"""
        self.flow.session_target = self.now + timedelta(seconds=60)
        self.flow._goto(WAIT_TIME, u"等待整点…")
        self.flow.update(0.2, self.now)
        self.assertEqual(self.flow.state, ENTER_PRODUCT)
        self.assertTrue(self.flow._preheat_pending)
        self.assertTrue(self.flow._preheated)
        # 详情页加载完成 → back 回列表等待
        self.bridge.spec_ready = True
        self.flow._goto(WAIT_DETAIL, u"预热中…")
        self.flow.update(0.1, self.now)
        self.assertEqual(self.flow.state, WAIT_TIME)
        self.assertFalse(self.flow._preheat_pending)
        self.assertEqual(self.bridge.back_count, 1)
        # 再等一拍：不重复预热
        self.flow.update(0.2, self.now)
        self.assertEqual(self.flow.state, WAIT_TIME)

    def test_default_year_skips_year_click(self):
        """UI 选 2024（详情页默认已选）→ 不点年份，直接进数量"""
        self.flow.year_target = u"2024"
        self.bridge.spec_ready = True
        self._goto_year()
        self.flow.update(0.02, self.now)
        self.assertEqual(self.flow.state, SELECT_QTY)
        self.assertEqual(self.bridge.year_clicks, 0)

    def test_every_non_default_year_clicks_its_cell(self):
        """UI 选 2026/2023/2022/2021/2020/2019 → 逐个都点对应年份格"""
        for year in (u"2026", u"2023", u"2022", u"2021", u"2020", u"2019"):
            self.flow.year_target = year
            self.bridge.spec_ready = True
            self.bridge.year_clicks = 0
            self._goto_year()
            self.flow.update(0.02, self.now)
            self.assertEqual(self.flow.state, SELECT_QTY, year)
            self.assertEqual(self.bridge.year_clicks, 1, year)

    def test_grace_waits_for_qty_and_changes_to_six(self):
        """按钮先渲染、规格延迟：宽限内不跳过，最终改 6 瓶。"""
        self._goto_year()
        # 前 2 秒（< 3 秒宽限）规格未渲染：状态必须停在 YEAR
        for _ in range(int(2.0 / 0.02)):
            self.flow.update(0.02, self.now)
        self.assertEqual(self.flow.state, SELECT_YEAR)
        self.assertEqual(self.bridge.plus_taps, 0)
        # 规格在宽限内渲染：年份→数量→改 6
        self.bridge.spec_ready = True
        for _ in range(200):
            self.flow.update(0.02, self.now)
            if self.flow.state == READ_DETAIL:
                break
        self.assertEqual(self.bridge.value, QTY_TARGET)
        self.assertEqual(self.bridge.plus_taps, 4)
        self.assertEqual(self.flow.state, READ_DETAIL)

    def test_reenter_after_threshold_clicks(self):
        """连点达到阈值 5：自动 back 重进，进 ENTER，轮次 +1。"""
        self._goto_year()
        self.bridge.spec_ready = True
        # 走到 RAPID（含 READ 首点 + 改数量）
        for _ in range(300):
            self.flow.update(0.01, self.now)
            if self.flow.state == RAPID_BUY:
                break
        self.assertEqual(self.flow.state, RAPID_BUY)
        # RAPID 内连点到阈值后自动重进
        for _ in range(200):
            self.flow.update(0.01, self.now)
            if self.flow.state == ENTER_PRODUCT:
                break
        self.assertEqual(self.flow.state, ENTER_PRODUCT)
        self.assertGreaterEqual(self.bridge.back_count, 1)
        self.assertEqual(self.flow._rapid_reenter_rounds, 1)

    def test_no_reenter_before_threshold(self):
        """未到阈值：保持 RAPID 继续点，不提前返回。"""
        self._goto_year()
        self.bridge.spec_ready = True
        for _ in range(300):
            self.flow.update(0.01, self.now)
            if self.flow.state == RAPID_BUY:
                break
        # 手动把计数设为 3（阈值 5），只推进一拍点到 4，不应重进
        self.flow._rapid_click_count = 3
        self.flow._rapid_wait_left = 0.0
        self.flow.update(0.01, self.now)
        self.assertEqual(self.flow.state, RAPID_BUY)
        self.assertEqual(self.flow._rapid_click_count, 4)
        self.assertEqual(self.bridge.back_count, 0)


if __name__ == "__main__":
    unittest.main()
