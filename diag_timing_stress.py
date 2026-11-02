# -*- coding: utf-8 -*-
"""
时序压力测试（虚拟时钟 + 模拟每次无障碍调用的 JNI 耗时）。

场景1：08:30:00 武装 09:00:00
    验收：拉起 → i购 → 经典 → 认到完整商品名 → 预热读时间 → 回列表等整点
          → 整点重进详情 → 选年份 → 改 6 瓶 → 点立即抢购 的毫秒级时序。

场景2a：整点进入时按钮还没刷新（页面 09:00:01.5 才变成立即抢购）
    验收：读到本场时间后退出重进，直到刷新出按钮。

场景2b：详情页显示的是未来场次（09:05投放）
    验收：读取时间值并替换当前目标，等到 09:05:00 再精确重进。

场景2c：同一小时内页面仍是已过场次（09:00投放，现在 09:04:59）
    验收：是否按"读取时间值 → 延续/替换目标"处理，而不是直接顺延次日。

运行：
    D:\\python\\python.exe diag_timing_stress.py
"""

import sys
from datetime import datetime, timedelta

from config import (
    YEAR_TARGET_TEXT,
    QTY_REGEX,
    SALE_TIME_REGEX,
    BUY_NOW_TEXTS,
    IGOU_TAB_REGION_PX,
    JINGDIAN_TAB_REGION_PX,
    YEAR_CELL_REGION_PX,
    QTY_VALUE_REGION_PX,
)
from flow_core import (
    FlowCore,
    READ_DETAIL,
    SELECT_QTY,
    SELECT_YEAR,
    WAIT_DETAIL,
    WAIT_TIME,
    WAIT_VERIFY,
    RAPID_BUY,
)

BUY = u"立即抢购"
PRODUCT = u"飞天53%vol 500ml贵州茅台酒（带杯）"
YEAR = YEAR_TARGET_TEXT if YEAR_TARGET_TEXT in YEAR_CELL_REGION_PX else u"2026"
YEAR_CENTER = (
    (YEAR_CELL_REGION_PX[YEAR][0] + YEAR_CELL_REGION_PX[YEAR][2]) // 2,
    (YEAR_CELL_REGION_PX[YEAR][1] + YEAR_CELL_REGION_PX[YEAR][3]) // 2,
)
QTY_CENTER = (909, 1962)
PLUS_CENTER = (994, 1962)
BUTTON_CENTER = (840, 2162)
IGOU_CENTER = (330, 2080)
JD_CENTER = (275, 1010)
PRODUCT_CENTER = (540, 1300)

# 每个状态的主循环节拍（与 main.FlowWorker 一致）
TICKS = {
    RAPID_BUY: 0.01,
    SELECT_YEAR: 0.02,
    SELECT_QTY: 0.02,
    WAIT_TIME: 0.02,
    WAIT_VERIFY: 0.02,
    READ_DETAIL: 0.05,
    WAIT_DETAIL: 0.02,
}
DEFAULT_TICK = 0.3


def _in(center, region):
    return region[0] <= center[0] <= region[2] \
        and region[1] <= center[1] <= region[3]


class Harness(object):
    """虚拟时钟：每次 update 后按 节拍 + 调用次数×JNI 推进时间"""

    def __init__(self, flow, phone, start, jni=0.03):
        self.f = flow
        self.p = phone
        self.t = start
        self.last = start
        self.jni = jni
        self.events = []

    def record(self, label):
        self.events.append((self.t, label))

    def run(self, until, max_seconds=7200):
        end = self.t + timedelta(seconds=max_seconds)
        while self.t < end:
            if until():
                return True
            self.p.calls = 0
            now = self.t
            dt = (now - self.last).total_seconds()
            self.last = now
            self.f.update(dt, now)
            sleep = TICKS.get(self.f.state, DEFAULT_TICK)
            self.t += timedelta(seconds=sleep)
        return False


class Phone(object):
    """模拟 i茅台：页面切换 + 详情页按钮"加载时渲染、不自动刷新" """

    def __init__(self, harness_setter, slot, flip_at):
        self.h = None          # 由 build 注入
        self.slot = slot       # "09:00"
        self.flip_at = flip_at
        self.page = u"outside"
        self.detail_button = u""
        self.entered_at = None
        self.qty = 2
        self.calls = 0
        self.buy_clicks = 0
        self.entries = 0
        self.year_clicks = 0
        self.jni = 0.03
        self._qty6_logged = False

    # ---- 模拟耗时：每次桥接调用都真实占用时间 ----
    def _cost(self):
        self.calls += 1
        if self.h is not None:
            self.h.t += timedelta(seconds=self.jni)

    # ---- 页面元素 ----
    def _elements(self):
        if self.page == u"outside":
            return []
        if self.page == u"home":
            return [(u"i购", IGOU_CENTER)]
        if self.page == u"igou":
            return [(u"经典", JD_CENTER), (u"全部", (134, 1011)),
                    (u"精品", (404, 1011))]
        if self.page == u"list":
            return [(PRODUCT, PRODUCT_CENTER), (u"经典", JD_CENTER),
                    (u"全部", (134, 1011)), (u"精品", (404, 1011))]
        return [
            (u"数量", (60, 1962)),
            (YEAR, YEAR_CENTER),
            (str(self.qty), QTY_CENTER),
            (self.detail_button, BUTTON_CENTER),
        ]

    def _find(self, text):
        for t, c in self._elements():
            if text in t:
                return c
        return None

    # ---- 桥接接口 ----
    def is_connected(self):
        self._cost()
        return True

    def text_exists(self, text):
        self._cost()
        if text in (u"已售罄", u"已售磬"):
            return False
        return self._find(text) is not None

    def any_text_exists(self, texts):
        self._cost()
        return any(self._find(t) is not None for t in texts)

    def node_center(self, keywords):
        self._cost()
        for t, c in self._elements():
            if all(k in t for k in keywords):
                return c
        return None

    def text_exists_in_px_region(self, text, region):
        self._cost()
        c = self._find(text)
        return c is not None and _in(c, region)

    def click_text_in_px_region(self, text, region):
        self._cost()
        c = self._find(text)
        if c is None or not _in(c, region):
            return False
        return self._click(text)

    def click_text(self, text):
        self._cost()
        if self._find(text) is None:
            return False
        return self._click(text)

    def find_regex_in_px_region(self, regex, region):
        self._cost()
        if self.page != u"detail":
            return []
        if regex == QTY_REGEX:
            return [str(self.qty)] if _in(QTY_CENTER, region) else []
        if regex == SALE_TIME_REGEX:
            if self.detail_button.endswith(u"投放"):
                return [self.slot] if _in(BUTTON_CENTER, region) else []
            return []
        return []

    def tap_px(self, x, y, jitter=6):
        self._cost()
        if self.page == u"detail" and abs(x - PLUS_CENTER[0]) < 25 \
                and abs(y - PLUS_CENTER[1]) < 25:
            self.qty += 1
            if self.qty >= 6 and not self._qty6_logged:
                self._qty6_logged = True
                self.h.record(u"数量改为 6 瓶")
        return True

    def tap_multi_px(self, x, y, count, jitter=6, gap_ms=130):
        """一次手势多点（新 APK 的能力）：只算 1 次跨语言调用"""
        self._cost()
        if self.page == u"detail" and abs(x - PLUS_CENTER[0]) < 25 \
                and abs(y - PLUS_CENTER[1]) < 25:
            self.qty += int(count)
            if self.qty >= 6 and not self._qty6_logged:
                self._qty6_logged = True
                self.h.record(u"数量改为 6 瓶（一次手势 %d 连点）" % count)
        return True

    def back(self):
        self._cost()
        if self.page == u"detail":
            self.page = u"list"
            self.h.record(u"退回列表")
            return True
        return False

    def launch(self):
        self._cost()
        if self.page == u"outside":
            self.page = u"home"
            self.h.record(u"拉起 i茅台")
        return True

    # ---- 点击语义 ----
    def _click(self, text):
        if text == u"i购":
            self.page = u"igou"
            self.h.record(u"点 i购")
        elif text == u"经典":
            self.page = u"list"
            self.h.record(u"点 经典")
        elif text in (u"立即抢购", u"立即购买"):
            self.buy_clicks += 1
            self.h.record(u"点 立即抢购（第 %d 次）" % self.buy_clicks)
        elif text == YEAR:
            self.year_clicks += 1
            self.h.record(u"选年份 %s" % YEAR)
        elif text == PRODUCT:
            self.page = u"detail"
            self.entries += 1
            self.entered_at = self.h.t
            # 业务规则：按钮状态由"这次加载的时刻"决定，之后不再自动刷新
            self.detail_button = BUY if self.h.t >= self.flip_at \
                else u"%s投放" % self.slot
            self.qty = 2
            self._qty6_logged = False
            self.h.record(u"进入详情页（按钮=%s）" % self.detail_button)
        return True


def build(slot, flip_at, start, target, jni=0.03):
    phone = Phone(None, slot, flip_at)
    phone.jni = jni
    logs = []
    flow = FlowCore(phone, type("L", (), {"log": lambda s, m: logs.append(m)})())
    flow.year_target = YEAR
    harness = Harness(flow, phone, start, jni=jni)
    phone.h = harness
    flow.on_launch_app = phone.launch
    flow.reset(target)
    return flow, phone, harness, logs


def ms_text(t):
    return t.strftime(u"%H:%M:%S.%f")[:-3]


def show(title, harness, base, keys, limit=26):
    print(u"\n" + u"=" * 68)
    print(title)
    print(u"-" * 68)
    for t, label in harness.events[:limit]:
        delta = (t - base).total_seconds()
        print(u"  %s  (%+8.1f ms)  %s" % (ms_text(t), delta * 1000, label))
    if len(harness.events) > limit:
        print(u"  … 另有 %d 条事件未展开" % (len(harness.events) - limit))


def scenario1(jni=0.03):
    start = datetime(2026, 11, 2, 8, 30, 0)
    target = datetime(2026, 11, 2, 9, 0, 0)
    flow, phone, h, logs = build(u"09:00", target, start, target, jni)
    h.run(lambda: phone.buy_clicks >= 1, max_seconds=3600 * 2)
    show(u"场景1：08:30 武装 09:00:00（单次无障碍调用 %.0f ms）"
         % (jni * 1000), h, target,
         [u"拉起", u"进入详情", u"点 立即抢购"])
    entries = [e for e in h.events if u"进入详情页" in e[1]]
    first_entry = entries[0][0] if entries else None
    slot_entry = None
    for t, label in h.events:
        if u"进入详情页" in label and t >= target:
            slot_entry = t
            break
    buy = next((t for t, lb in h.events if u"点 立即抢购" in lb), None)
    print(u"-" * 68)
    if slot_entry:
        print(u"  整点重进详情：%s  距 09:00:00.000 = %+.1f ms"
              % (ms_text(slot_entry), (slot_entry - target).total_seconds() * 1000))
    if buy:
        print(u"  首次点抢购  ：%s  距 09:00:00.000 = %+.1f ms"
              % (ms_text(buy), (buy - target).total_seconds() * 1000))
    print(u"  预热进入次数：%d，整点后进入次数：%d，年份点击：%d 次"
          % (len([e for e in entries if e[0] < target]),
             len([e for e in entries if e[0] >= target]),
             phone.year_clicks))
    return {
        "slot_entry_ms": (slot_entry - target).total_seconds() * 1000
        if slot_entry else None,
        "buy_ms": (buy - target).total_seconds() * 1000 if buy else None,
        "entries": len(entries),
    }


def scenario2a(jni=0.03):
    start = datetime(2026, 11, 2, 9, 0, 0) - timedelta(seconds=15)
    target = datetime(2026, 11, 2, 9, 0, 0)
    flip = target + timedelta(seconds=1.5)
    flow, phone, h, logs = build(u"09:00", flip, start, target, jni)
    h.run(lambda: phone.buy_clicks >= 1, max_seconds=120)
    show(u"场景2a：整点进入时按钮未刷新（页面 09:00:01.5 才翻牌）",
         h, target, [u"进入详情", u"点 立即抢购"])
    buy = next((t for t, lb in h.events if u"点 立即抢购" in lb), None)
    print(u"-" * 68)
    print(u"  整点后进入次数：%d，重进重试 %d 次"
          % (len([1 for t, lb in h.events
                  if u"进入详情页" in lb and t >= target]),
             len([1 for t, lb in h.events
                  if u"进入详情页" in lb and t >= target]) - 1))
    if buy:
        print(u"  首次点抢购：%s  距整点 = %+.1f ms"
              % (ms_text(buy), (buy - target).total_seconds() * 1000))
    return {"entries_after_slot": len([1 for t, lb in h.events
                                       if u"进入详情页" in lb and t >= target])}


def scenario2b(jni=0.03):
    start = datetime(2026, 11, 2, 9, 0, 5)
    target = datetime(2026, 11, 2, 9, 0, 0)      # 已过点武装
    slot = u"09:05"
    flip = datetime(2026, 11, 2, 9, 5, 0)
    flow, phone, h, logs = build(slot, flip, start, target, jni)
    h.run(lambda: phone.buy_clicks >= 1, max_seconds=600)
    show(u"场景2b：详情页显示未来场次 09:05投放（09:00:05 武装）",
         h, target, [u"进入详情", u"点 立即抢购"])
    entry = next((t for t, lb in h.events
                  if u"进入详情页" in lb and t >= flip), None)
    buy = next((t for t, lb in h.events if u"点 立即抢购" in lb), None)
    print(u"-" * 68)
    if entry:
        print(u"  09:05 重进详情：距 09:05:00.000 = %+.1f ms"
              % ((entry - flip).total_seconds() * 1000))
    if buy:
        print(u"  首次点抢购  ：距 09:05:00.000 = %+.1f ms"
              % ((buy - flip).total_seconds() * 1000))
    print(u"  目标是否被替换为 09:05：%s"
          % (u"是" if flow.session_target == flip else
             u"否（%s）" % flow.session_target))
    return {"replaced": flow.session_target == flip}


def scenario2c(jni=0.03):
    start = datetime(2026, 11, 2, 9, 4, 59)
    target = datetime(2026, 11, 2, 9, 0, 0)
    flip = datetime(2026, 11, 2, 9, 10, 0)       # 页面要 9:10 才翻牌
    flow, phone, h, logs = build(u"09:00", flip, start, target, jni)
    # 先跑到第一次读到已过时间，再观察 8 秒内的重进行为
    h.run(lambda: flow.state == WAIT_TIME and flow._reenter_count >= 1,
          max_seconds=30)
    h.run(lambda: flow.is_done or phone.buy_clicks >= 1, max_seconds=8)
    show(u"场景2c：同一小时内页面仍显示已过的 09:00投放（现在 09:04:59）",
         h, target, [u"进入详情", u"点 立即抢购"])
    print(u"-" * 68)
    print(u"  最终状态：%s  当前目标：%s  重进次数：%d"
          % (flow.state, flow.session_target, flow._reenter_count))
    today = datetime(2026, 11, 2).date()
    jumped = bool(flow.session_target and flow.session_target.date() > today)
    print(u"  是否直接顺延到次日：%s"
          % (u"是（违背“同小时内延续当前设定”）" if jumped
             else u"否（仍在本场重进刷新）"))
    return {"next_day": jumped,
            "entries": len([1 for t, lb in h.events if u"进入详情页" in lb])}


if __name__ == u"__main__":
    r1 = scenario1(0.03)
    scenario1(0.08)
    r2a = scenario2a(0.03)
    r2b = scenario2b(0.03)
    r2c = scenario2c(0.03)
    print(u"\n" + u"=" * 68)
    print(u"汇总")
    print(u"  场景1  整点重进延迟：%.0f ms / 首点延迟：%.0f ms"
          % (r1["slot_entry_ms"], r1["buy_ms"]))
    print(u"  场景2a 整点后进入次数：%d" % r2a["entries_after_slot"])
    print(u"  场景2b 目标替换为 09:05：%s" % (u"是" if r2b["replaced"] else u"否"))
    print(u"  场景2c 顺延次日：%s（重进 %d 次）"
          % (u"是" if r2c["next_day"] else u"否", r2c["entries"]))
