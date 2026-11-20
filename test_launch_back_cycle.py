# -*- coding: utf-8 -*-
"""
端到端仿真：拉起 i茅台 → 识别进入（首页→i购→经典→列表→详情）
→ 详情返回上一层 → 再进入详情 → 再返回，共两次。

覆盖的链路（全部走真实状态机，只把"手机"换成可控的假设备）：
    IDLE    到点调用 on_launch_app（拉起）
    NAV     首页点 i购 → i购页点 经典
    ENTER   列表双确认后点商品
    WAIT_DETAIL → YEAR → QTY(2→6) → READ → RAPID
    RAPID   第一次点完后按钮变「售罄」
    ENTER   售罄复核：back 回列表（第 1 次返回）→ 再次点商品进详情
    READ    二次确认仍售罄 → back 回列表（第 2 次返回）→ 结束

运行：
    python test_launch_back_cycle.py
"""

import unittest
from datetime import datetime, timedelta

from config import (
    PRODUCT_FULL_TEXTS,
    BUY_NOW_TEXTS,
    SOLD_OUT_TEXTS,
    YEAR_CHOICES,
    QTY_REGEX,
    QTY_TARGET,
)
from flow_core import (
    FlowCore,
    IDLE,
    NAVIGATE_IGOU,
    ENTER_PRODUCT,
    WAIT_DETAIL,
    SELECT_YEAR,
    SELECT_QTY,
    READ_DETAIL,
    RAPID_BUY,
    DONE,
)

START = datetime(2026, 11, 14, 9, 0, 0)
DT = 0.02


class FakePhone(object):
    """极简真机模型：home → igou → list → detail，可点、可返回。

    allow_year_click=True 时支持「点别的年份再点回来」（页内刷新）；
    设成 False 用来验证「切年份不可用 → 退回列表」的兜底路径。
    """

    def __init__(self, allow_year_click=True):
        self.page = u"home"
        self.soldout = False
        self.qty = 2
        self.launch_count = 0
        self.product_clicks = 0
        self.buy_clicks = 0
        self.back_count = 0
        self.year_clicks = 0
        self.allow_year_click = bool(allow_year_click)

    # ---------------- 页面内容 ----------------
    def _texts(self):
        if self.page == u"home":
            return {u"i购"}
        if self.page == u"igou":
            return {u"i购", u"经典"}
        if self.page == u"list":
            return {u"i购", u"经典"} | set(PRODUCT_FULL_TEXTS)
        texts = {u"i购", u"数量"}
        texts.add(u"售罄" if self.soldout else u"立即抢购")
        return texts

    def is_connected(self):
        return True

    def current_package(self):
        return u"com.moutai.mall"

    def text_exists(self, text):
        return any(text in t for t in self._texts())

    def any_text_exists(self, texts):
        return any(self.text_exists(t) for t in texts)

    def text_exists_in_px_region(self, text, region):
        if self.page != u"detail":
            return False
        return self.text_exists(text)

    def node_center(self, keywords):
        if self.page == u"list" and all(
                any(k in name for name in PRODUCT_FULL_TEXTS)
                for k in keywords):
            for name in PRODUCT_FULL_TEXTS:
                if all(k in name for k in keywords):
                    return (313, 1807)
        return None

    def dump_nodes(self):
        return []

    def find_exact_regex_texts(self, regex):
        return []

    def find_regex_in_px_region(self, regex, region):
        if regex == QTY_REGEX and self.page == u"detail":
            return [u"%d" % self.qty]
        return []

    def average_color_in_px_region(self, region):
        return None

    # ---------------- 点击 ----------------
    def _click(self, text):
        if text == u"i购" and self.page == u"home":
            self.page = u"igou"
            return True
        if text == u"经典" and self.page == u"igou":
            self.page = u"list"
            return True
        if text in PRODUCT_FULL_TEXTS and self.page == u"list":
            self.page = u"detail"
            self.product_clicks += 1
            return True
        if self.allow_year_click and text in YEAR_CHOICES \
                and self.page == u"detail":
            # 切年份 = 页内换 SKU：数量回到默认 2 瓶
            self.year_clicks += 1
            self.qty = 2
            return True
        if text in BUY_NOW_TEXTS and self.page == u"detail" and not self.soldout:
            self.buy_clicks += 1
            self.soldout = True          # 点一次就售罄，逼出「复核」流程
            return True
        return False

    def click_text(self, text):
        return self._click(text)

    def click_text_in_px_region(self, text, region):
        return self._click(text)

    def click_node_by_parts(self, keywords):
        return False

    def tap_px(self, x, y, jitter=6):
        return True

    def tap_multi_px(self, x, y, count, jitter=6, gap_ms=130):
        self.qty += int(count)
        return True

    def back(self):
        if self.page == u"detail":
            self.page = u"list"
        self.back_count += 1
        return True

    def launch(self):
        self.launch_count += 1
        return True


class TimedPhone(FakePhone):
    """
    详情页按钮先显示「09:00投放」，到点后变成「立即抢购」。

    用来验证完整等待时序：进详情 → 切邻格年份 → 等到点 → 切回目标年份
    → 刷新识别 → 连点。now_ref 是单元素列表，由测试推进。
    """

    def __init__(self, target, now_ref, allow_year_click=True):
        super(TimedPhone, self).__init__(allow_year_click)
        self.target = target
        self.now_ref = now_ref
        # 按钮上的投放时间与目标时刻一致（如 09:03）
        self.time_text = target.strftime(u"%H:%M")

    def _texts(self):
        texts = set(super(TimedPhone, self)._texts())
        if self.page == u"detail":
            texts.discard(u"立即抢购")
            texts.discard(u"售罄")
            if self.now_ref[0] < self.target:
                texts.add(self.time_text + u"投放")
            else:
                texts.add(u"立即抢购")
        return texts

    def find_exact_regex_texts(self, regex):
        # 到点前整段匹配返回投放时间；到点后页面已刷新成「立即抢购」
        return [] if self.now_ref[0] >= self.target else [self.time_text]

    def _click(self, text):
        if text in BUY_NOW_TEXTS and self.page == u"detail":
            self.buy_clicks += 1
            return True
        return super(TimedPhone, self)._click(text)


class LaunchBackCycleTest(unittest.TestCase):

    def test_inplace_refresh_on_soldout(self):
        """新模型：售罄不离开详情页，靠「切年份往返」刷新后复核第二遍"""
        phone = FakePhone()
        logs = []
        logger = type("L", (), {"log": lambda s, m: logs.append(m)})()
        flow = FlowCore(phone, logger)
        flow.profile = None
        flow.on_launch_app = phone.launch

        flow.reset(START, launch_target=START)

        # 第一拍 update() 里就会从 IDLE 切到 NAV，所以先记下初始状态
        states = [flow.state]
        now = START
        for _ in range(4000):
            flow.update(DT, now)
            if not states or states[-1] != flow.state:
                states.append(flow.state)
            if flow.is_done:
                break
            now += timedelta(seconds=DT)

        # 1) 拉起
        self.assertGreaterEqual(phone.launch_count, 1, u"没有拉起 i茅台")

        # 2) 完整识别链：首页→i购→经典→列表→详情
        #    新模型下整条导航由 NAV 一次走完，不再经过 ENTER_PRODUCT
        for expected in (IDLE, NAVIGATE_IGOU, WAIT_DETAIL,
                         SELECT_YEAR, SELECT_QTY, READ_DETAIL, RAPID_BUY):
            self.assertIn(expected, states, u"缺少状态 %s" % expected)

        # 3) 只在最初进了一次详情，之后全靠切年份刷新
        self.assertEqual(phone.product_clicks, 1, u"不应再重进详情页")
        self.assertEqual(phone.back_count, 0, u"不应退回列表")
        self.assertEqual(phone.year_clicks, 2, u"应切一次年份往返")

        # 4) 切 SKU 会把数量重置成 2，必须重新改回 6
        self.assertEqual(phone.qty, QTY_TARGET)

        # 5) 以「二次确认售罄」正常结束，且始终停在详情页
        self.assertEqual(flow.state, DONE)
        self.assertTrue(flow.success)
        self.assertEqual(phone.page, u"detail")

    def test_stuck_recover_prefers_year_switch(self):
        """3 秒无进展时：优先切年份刷新，不退回列表"""
        phone = FakePhone()
        phone.page = u"detail"
        flow = FlowCore(phone)
        flow.profile = None
        flow.state = READ_DETAIL
        flow._state_elapsed = 99.0

        self.assertTrue(flow._stuck_recover(ENTER_PRODUCT))

        self.assertEqual(flow.state, SELECT_QTY, u"应回数量重新确认")
        self.assertEqual(phone.back_count, 0, u"不应退回列表")
        self.assertEqual(phone.year_clicks, 2, u"应切一次年份往返")

    def test_stuck_recover_falls_back_to_back(self):
        """切年份不可用时：才 back 回列表兜底"""
        phone = FakePhone(allow_year_click=False)
        flow = FlowCore(phone)
        flow.profile = None
        flow.state = READ_DETAIL
        flow._state_elapsed = 99.0

        self.assertTrue(flow._stuck_recover(ENTER_PRODUCT))

        self.assertEqual(flow.state, ENTER_PRODUCT)
        self.assertEqual(phone.back_count, 1, u"应退回列表兜底")

    def test_wait_switches_out_then_back_at_target(self):
        """完整时序：进详情→切邻格年份→等到点→切回目标年份→识别→连点"""
        target = START + timedelta(seconds=180)
        now_ref = [START]
        phone = TimedPhone(target, now_ref)
        flow = FlowCore(phone)
        flow.profile = None
        flow.on_launch_app = phone.launch
        flow.reset(target, launch_target=START)

        now = START
        for _ in range(200000):
            flow.update(DT, now)
            now_ref[0] = now
            if flow.state == RAPID_BUY and phone.buy_clicks > 0:
                break
            now += timedelta(seconds=DT)

        self.assertEqual(flow.state, RAPID_BUY, u"应进入连点")
        self.assertEqual(phone.product_clicks, 1, u"只进一次详情")
        self.assertEqual(phone.back_count, 0, u"全程不返回上一层")
        self.assertGreaterEqual(phone.year_clicks, 3, u"应切出去再切回来")
        self.assertGreaterEqual(phone.buy_clicks, 1, u"应点到立即抢购")
        self.assertEqual(phone.qty, QTY_TARGET, u"切回后数量要重新改到 6")

    def test_soldout_ends_when_year_click_unsupported(self):
        """切年份不可用（旧 APK / 档案缺年份格）：无法二次复核，直接结束"""
        phone = FakePhone(allow_year_click=False)
        flow = FlowCore(phone)
        flow.profile = None
        flow.on_launch_app = phone.launch
        flow.reset(START, launch_target=START)

        states = [flow.state]
        now = START
        for _ in range(4000):
            flow.update(DT, now)
            if not states or states[-1] != flow.state:
                states.append(flow.state)
            if flow.is_done:
                break
            now += timedelta(seconds=DT)

        self.assertEqual(flow.state, DONE)
        self.assertTrue(flow.success)
        # 新模型：不返回上一层，也不再重进详情
        self.assertNotIn(ENTER_PRODUCT, states, u"不应回到 ENTER 重进")
        self.assertEqual(phone.product_clicks, 1)
        self.assertEqual(phone.back_count, 0)
        self.assertEqual(phone.year_clicks, 0)


if __name__ == "__main__":
    unittest.main()
