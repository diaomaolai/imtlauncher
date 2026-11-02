# -*- coding: utf-8 -*-
"""
首轮校准之后的时序压力测试（档案驱动模式）。

前提：首轮已用 DeviceCalibrator 建档（品牌/型号/宽高/密度 + 控件 bounds），
本脚本用 OPPO 1080x2400 与华为 1200x2652 两套已定几何分别构造档案，
验证加载档案后的整点重进 / 选年份改数量 / 连点 / 时间回读。

场景1：08:30 武装 09:00:00
    整点重进详情 → 选年份 → 改 6 瓶 → 首点抢购 的毫秒级时序。
场景2a：整点进入时按钮还没刷新（页面 09:00:01.5 才翻）
    读到本场时间后退出重进，直到刷新出按钮。
场景2b：详情页显示未来场次（09:05投放）
    读取时间并替换目标，等到 09:05:00 再精确重进。
场景2c：同一小时内页面仍是已过场次（09:00投放，现在 09:04:59）
    应继续重进刷新，不顺延次日。

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
    PRODUCT_FULL_TEXTS,
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
from device_profile import DeviceProfile
from sim_two_devices import OPPO_GEO, HUAWEI_GEO, OPPO_FP, HUAWEI_FP

BUY = u"立即抢购"
PRODUCT = PRODUCT_FULL_TEXTS[0]
YEAR = YEAR_TARGET_TEXT

DEVICES = (
    (u"OPPO PDSM00 1080x2400", OPPO_GEO, OPPO_FP),
    (u"华为 GOA-AL80 1200x2652", HUAWEI_GEO, HUAWEI_FP),
)

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


def _center(rect):
    return [(rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2]


def build_profile(geo, fingerprint):
    """模拟首轮校准产出的档案（控件 bounds 全部来自该机型实测/标定）"""
    def rec(rect):
        return {u"bounds": list(rect), u"center": _center(rect)}

    controls = {
        u"igou_tab": rec(geo[u"igou"]),
        u"jingdian_tab": rec(geo[u"jd"]),
        u"product_card": rec(geo[u"product"]),
        u"year_cells": {
            year: rec(rect) for year, rect in geo[u"year"].items()
        },
        u"qty_value": rec(geo[u"qty_value"]),
        u"qty_minus": rec(geo[u"qty_minus"]),
        u"qty_plus": rec(geo[u"qty_plus"]),
        u"action_button": rec(geo[u"action"]),
    }
    return DeviceProfile(fingerprint=fingerprint, controls=controls)


def _in(center, region):
    return region[0] <= center[0] <= region[2] \
        and region[1] <= center[1] <= region[3]


class Harness(object):
    """虚拟时钟：每次 update 后按 节拍 推进；桥接调用另计 JNI 耗时"""

    def __init__(self, flow, phone, start):
        self.f = flow
        self.p = phone
        self.t = start
        self.last = start
        self.events = []

    def record(self, label):
        self.events.append((self.t, label))

    def run(self, until, max_seconds=7200):
        end = self.t + timedelta(seconds=max_seconds)
        while self.t < end:
            if until():
                return True
            now = self.t
            dt = (now - self.last).total_seconds()
            self.last = now
            self.f.update(dt, now)
            self.t += timedelta(seconds=TICKS.get(self.f.state, DEFAULT_TICK))
        return False


class Phone(object):
    """模拟 i茅台：页面切换；详情页按钮按"加载时状态渲染、不自动刷新" """

    def __init__(self, geo, slot, flip_at, jni):
        self.geo = geo
        self.slot = slot
        self.flip_at = flip_at
        self.jni = jni
        self.h = None
        self.page = u"outside"
        self.detail_button = u""
        self.qty = 2
        self.calls = 0
        self.buy_clicks = 0
        self.year_clicks = 0
        self._qty6_logged = False
        self.igou_c = _center(geo[u"igou"])
        self.jd_c = _center(geo[u"jd"])
        self.product_c = _center(geo[u"product"])
        self.year_cents = {
            y: _center(r) for y, r in geo[u"year"].items()
        }
        self.qty_c = _center(geo[u"qty_value"])
        self.plus_c = _center(geo[u"qty_plus"])
        self.button_c = _center(geo[u"action"])

    # ---- 每次桥接调用都真实占用 JNI 时间 ----
    def _cost(self):
        self.calls += 1
        if self.h is not None:
            self.h.t += timedelta(seconds=self.jni)

    def _elements(self):
        if self.page == u"outside":
            return []
        if self.page == u"home":
            return [(u"i购", self.igou_c)]
        if self.page == u"igou":
            return [(u"经典", self.jd_c),
                    (u"全部", (self.jd_c[0] - 141, self.jd_c[1])),
                    (u"精品", (self.jd_c[0] + 135, self.jd_c[1]))]
        if self.page == u"list":
            return [(PRODUCT, self.product_c), (u"经典", self.jd_c),
                    (u"全部", (self.jd_c[0] - 141, self.jd_c[1])),
                    (u"精品", (self.jd_c[0] + 135, self.jd_c[1]))]
        return [
            (u"数量", (self.geo[u"qty_label"][0] + 30,
                      self.qty_c[1])),
            (YEAR, self.year_cents.get(YEAR, self.year_cents[
                sorted(self.year_cents)[0]])),
            (str(self.qty), self.qty_c),
            (self.detail_button, self.button_c),
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
            return [str(self.qty)] if _in(self.qty_c, region) else []
        if regex == SALE_TIME_REGEX:
            if self.detail_button.endswith(u"投放"):
                return [self.slot] if _in(self.button_c, region) else []
            return []
        return []

    def find_exact_regex_texts(self, regex):
        """新 APK 的整段匹配：只有按钮整段 "09:00投放" 会命中"""
        self._cost()
        if self.page != u"detail":
            return []
        if self.detail_button.endswith(u"投放"):
            return [self.slot]
        return []

    def tap_px(self, x, y, jitter=6):
        self._cost()
        if self.page == u"detail" and abs(x - self.plus_c[0]) < 25 \
                and abs(y - self.plus_c[1]) < 25:
            self.qty += 1
        return True

    def tap_multi_px(self, x, y, count, jitter=6, gap_ms=130):
        self._cost()
        if self.page == u"detail" and abs(x - self.plus_c[0]) < 25 \
                and abs(y - self.plus_c[1]) < 25:
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
            self.detail_button = BUY if self.h.t >= self.flip_at \
                else u"%s投放" % self.slot
            self.qty = 2
            self._qty6_logged = False
            self.h.record(u"进入详情页（按钮=%s）" % self.detail_button)
        return True


def build(geo, fp, slot, flip_at, start, target, jni=0.03):
    phone = Phone(geo, slot, flip_at, jni)
    logs = []
    flow = FlowCore(phone, type("L", (), {"log": lambda s, m: logs.append(m)})())
    flow.year_target = YEAR
    flow.profile = build_profile(geo, fp)
    flow.on_launch_app = phone.launch
    harness = Harness(flow, phone, start)
    phone.h = harness
    flow.reset(target)
    return flow, phone, harness, logs


def ms_text(t):
    return t.strftime(u"%H:%M:%S.%f")[:-3]


def show(title, harness, base, limit=26):
    print(u"\n" + u"=" * 70)
    print(title)
    print(u"-" * 70)
    for t, label in harness.events[:limit]:
        print(u"  %s  (%+9.1f ms)  %s"
              % (ms_text(t), (t - base).total_seconds() * 1000, label))
    if len(harness.events) > limit:
        print(u"  … 另有 %d 条事件未展开" % (len(harness.events) - limit))


def scenario1(device_name, geo, fp, jni):
    start = datetime(2026, 11, 2, 8, 30, 0)
    target = datetime(2026, 11, 2, 9, 0, 0)
    flow, phone, h, logs = build(geo, fp, u"09:00", target, start, target, jni)
    h.run(lambda: phone.buy_clicks >= 1, max_seconds=3600 * 2)
    show(u"场景1：%s（档案驱动，单次调用 %.0f ms）"
         % (device_name, jni * 1000), h, target)
    slots = [t for t, lb in h.events if u"进入详情页" in lb and t >= target]
    buy = next((t for t, lb in h.events if u"点 立即抢购" in lb), None)
    print(u"-" * 70)
    if slots:
        print(u"  整点重进详情：距 09:00:00.000 = %+.1f ms"
              % ((slots[0] - target).total_seconds() * 1000))
    if buy:
        print(u"  首次点抢购  ：距 09:00:00.000 = %+.1f ms"
              % ((buy - target).total_seconds() * 1000))
    print(u"  按钮区域（档案）：%s" % (geo[u"action"],))
    print(u"  商品区域（档案）：%s" % (geo[u"product"],))
    return {
        "entry": (slots[0] - target).total_seconds() * 1000 if slots else None,
        "buy": (buy - target).total_seconds() * 1000 if buy else None,
    }


def scenario2a(geo, fp, jni=0.03):
    start = datetime(2026, 11, 2, 9, 0, 0) - timedelta(seconds=15)
    target = datetime(2026, 11, 2, 9, 0, 0)
    flip = target + timedelta(seconds=1.5)
    flow, phone, h, logs = build(geo, fp, u"09:00", flip, start, target, jni)
    h.run(lambda: phone.buy_clicks >= 1, max_seconds=120)
    show(u"场景2a：整点进入时按钮未刷新（页面 09:00:01.5 才翻牌）", h, target)
    buy = next((t for t, lb in h.events if u"点 立即抢购" in lb), None)
    entries = len([1 for t, lb in h.events
                   if u"进入详情页" in lb and t >= target])
    print(u"-" * 70)
    print(u"  整点后进入次数：%d（重试 %d 次）" % (entries, max(0, entries - 1)))
    if buy:
        print(u"  首次点抢购：距整点 = %+.1f ms"
              % ((buy - target).total_seconds() * 1000))
    return {"entries": entries}


def scenario2b(geo, fp, jni=0.03):
    start = datetime(2026, 11, 2, 9, 0, 5)
    target = datetime(2026, 11, 2, 9, 0, 0)
    slot = u"09:05"
    flip = datetime(2026, 11, 2, 9, 5, 0)
    flow, phone, h, logs = build(geo, fp, slot, flip, start, target, jni)
    h.run(lambda: phone.buy_clicks >= 1, max_seconds=600)
    show(u"场景2b：详情页显示未来场次 09:05投放（09:00:05 武装）", h, target)
    entry = next((t for t, lb in h.events
                  if u"进入详情页" in lb and t >= flip), None)
    buy = next((t for t, lb in h.events if u"点 立即抢购" in lb), None)
    print(u"-" * 70)
    if entry:
        print(u"  09:05 重进详情：距 09:05:00.000 = %+.1f ms"
              % ((entry - flip).total_seconds() * 1000))
    if buy:
        print(u"  首次点抢购  ：距 09:05:00.000 = %+.1f ms"
              % ((buy - flip).total_seconds() * 1000))
    print(u"  目标是否被替换为 09:05：%s"
          % (u"是" if flow.session_target == flip else u"否"))
    return {"replaced": flow.session_target == flip}


def scenario2c(geo, fp, jni=0.03):
    start = datetime(2026, 11, 2, 9, 4, 59)
    target = datetime(2026, 11, 2, 9, 0, 0)
    flip = datetime(2026, 11, 2, 9, 10, 0)
    flow, phone, h, logs = build(geo, fp, u"09:00", flip, start, target, jni)
    h.run(lambda: flow.state == WAIT_TIME and flow._reenter_count >= 1,
          max_seconds=30)
    h.run(lambda: flow.is_done or phone.buy_clicks >= 1, max_seconds=8)
    show(u"场景2c：同一小时内页面仍显示已过的 09:00投放（现在 09:04:59）",
         h, target)
    today = datetime(2026, 11, 2).date()
    jumped = bool(flow.session_target and flow.session_target.date() > today)
    print(u"-" * 70)
    print(u"  最终目标：%s  重进次数：%d" % (flow.session_target,
                                            flow._reenter_count))
    print(u"  是否顺延次日：%s"
          % (u"是" if jumped else u"否（仍在本场重进刷新）"))
    return {"next_day": jumped}


if __name__ == u"__main__":
    results = []
    for name, geo, fp in DEVICES:
        r = scenario1(name, geo, fp, 0.03)
        results.append((name, r))

    geo, fp = OPPO_GEO, OPPO_FP
    r2a = scenario2a(geo, fp)
    r2b = scenario2b(geo, fp)
    r2c = scenario2c(geo, fp)

    print(u"\n" + u"=" * 70)
    print(u"汇总（全部为加载档案后）")
    for name, r in results:
        print(u"  %s：整点重进 %+.0f ms / 首点 %+.0f ms"
              % (name, r["entry"], r["buy"]))
    print(u"  场景2a 整点后进入 %d 次" % r2a["entries"])
    print(u"  场景2b 目标替换 09:05：%s" % (u"是" if r2b["replaced"] else u"否"))
    print(u"  场景2c 顺延次日：%s" % (u"是" if r2c["next_day"] else u"否"))
