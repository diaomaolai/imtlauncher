# -*- coding: utf-8 -*-
"""
双机模拟测试（基于 OPPO / 华为真机截图与实测参数）。

验证内容：
1. 首次武装无档案：真实 DeviceCalibrator 走导航链建档（节点树采集
   bounds + 截图存证，详情页绝不点抢购），JSON/TXT 落 profiles/；
2. 再次武装：FlowCore 加载档案，在档案 bounds 矩形内实时识别点击，
   跑通 导航→年份→数量2→6→立即抢购→弹窗成功→售罄复核→退出；
3. 华为 bounds 与 OPPO legacy px 不同，证明档案按机型独立生效；
4. 无档案时退回 legacy 固定 px；节点加载中动态等待（不再重校）。

运行：
    D:\\python\\python.exe sim_two_devices.py
"""

import os
import random
import re
import shutil
import tempfile

from datetime import datetime

from config import (
    YEAR_CHOICES,
    BUTTON_REGION_PX,
    IGOU_TAB_REGION_PX,
    JINGDIAN_TAB_REGION_PX,
    YEAR_CELL_REGION_PX,
    QTY_VALUE_REGION_PX,
    PRODUCT_FULL_TEXTS,
    RUNTIME_STALL_RECAL_SECONDS,
    STALL_RECAL_AFTER,
)
from device_profile import ProfileStore
from calibration import DeviceCalibrator
from flow_core import FlowCore, NAVIGATE_IGOU, WAIT_VERIFY


# ------------------------------------------------------------------
# 日志与节点构造
# ------------------------------------------------------------------

class ListLogger(object):
    def __init__(self):
        self.lines = []

    def log(self, message):
        self.lines.append(message)


def node(index, parent, bounds, text=u"", desc=u"",
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


# ------------------------------------------------------------------
# 两台设备的几何参数
# ------------------------------------------------------------------

OPPO_YEAR = {
    u"2026": (150, 1490, 435, 1590),
    u"2024": (430, 1490, 715, 1590),
    u"2023": (710, 1490, 990, 1590),
    u"2022": (150, 1610, 435, 1715),
    u"2021": (430, 1610, 715, 1715),
    u"2020": (710, 1610, 990, 1715),
    u"2019": (150, 1730, 435, 1835),
}

# OPPO：真机 uiautomator dump 实测绝对像素
OPPO_GEO = {
    u"igou": [216, 2043, 432, 2161],
    u"jd": [202, 966, 337, 1056],
    u"product": [120, 1100, 960, 1400],
    u"year": OPPO_YEAR,
    u"qty_label": [42, 1932, 120, 1992],
    u"qty_minus": [783, 1923, 870, 2001],
    u"qty_value": [867, 1923, 954, 2001],
    u"qty_plus": [951, 1923, 1038, 2001],
    u"action": [600, 2124, 1080, 2200],
}
OPPO_FP = {
    u"brand": u"OPPO", u"model": u"PDSM00",
    u"android_sdk": 33, u"screen_w": 1080,
    u"screen_h": 2400, u"density": 3.0,
    u"moutai_package": u"com.moutai.mall",
    u"moutai_version": u"1.9.15",
    u"moutai_version_code": 10915,
    u"installed": True,
}

# 华为：按真机截图（1200x2652）观察估算的模拟 bounds，
# 非真机 dump；用于证明档案按机型独立、与 OPPO px 不通用
HUAWEI_YEAR = {
    u"2026": (170, 1640, 480, 1760),
    u"2024": (510, 1640, 820, 1760),
    u"2023": (850, 1640, 1160, 1760),
    u"2022": (170, 1775, 480, 1895),
    u"2021": (510, 1775, 820, 1895),
    u"2020": (850, 1775, 1160, 1895),
    u"2019": (170, 1910, 480, 2030),
}
HUAWEI_GEO = {
    u"igou": [250, 2430, 480, 2580],
    u"jd": [220, 1060, 370, 1180],
    u"product": [130, 1200, 1070, 1550],
    u"year": HUAWEI_YEAR,
    u"qty_label": [45, 2130, 135, 2220],
    u"qty_minus": [830, 2120, 940, 2230],
    u"qty_value": [950, 2120, 1060, 2230],
    u"qty_plus": [1070, 2120, 1180, 2230],
    u"action": [660, 2350, 1200, 2440],
}
HUAWEI_FP = {
    u"brand": u"HUAWEI", u"model": u"GOA-AL80",
    u"android_sdk": 31, u"screen_w": 1200,
    u"screen_h": 2652, u"density": 3.25,
    u"moutai_package": u"com.moutai.mall",
    u"moutai_version": u"1.9.15",
    u"moutai_version_code": 10915,
    u"installed": True,
}


# ------------------------------------------------------------------
# 模拟桥接：页面节点 + 事件驱动切页
# ------------------------------------------------------------------

class SimBridge(object):

    def __init__(self, geo, width, height):
        self.geo = geo
        self.W = width
        self.H = height
        self.page = u"home"
        self.value = 2
        self.verify_on = False
        self.order_on = False
        self.soldout_on = False
        self.buy_clicks = 0
        self.taps = []
        self.region_calls = []
        self.actions = []
        b = geo[u"qty_plus"]
        self.plus_center = ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2)

    def reset_runtime(self):
        self.page = u"home"
        self.value = 2
        self.verify_on = False
        self.order_on = False
        self.soldout_on = False
        self.buy_clicks = 0
        self.taps = []
        self.region_calls = []
        self.actions = []

    # ---------------- 节点集合 ----------------
    def _all_nodes(self):
        if self.page == u"detail":
            return self._detail_nodes()
        return self._static_pages()[self.page]

    def _node_map(self):
        return {(0, int(n[u"i"])): n for n in self._all_nodes()}

    def _static_pages(self):
        g = self.geo
        home = [
            node(0, -1, (0, 0, self.W, self.H)),
            node(3, 0, g[u"igou"], clickable=True),
            node(1, 3, (0, 0, 0, 0), text=u"i购"),
        ]
        igou = [
            node(0, -1, (0, 0, self.W, self.H)),
            node(5, 0, (40, 1080, 170, 1160), text=u"全部"),
            node(4, 0, g[u"jd"], text=u"经典", clickable=True),
            node(6, 0, (390, 1080, 520, 1160), text=u"精品"),
        ]
        product_text = u"飞天53%vol 500ml贵州茅台酒（带杯）"
        list_page = [
            node(0, -1, (0, 0, self.W, self.H)),
            node(6, 0, (40, 1080, 170, 1160), text=u"全部"),
            node(4, 0, g[u"jd"], text=u"经典"),
            node(5, 0, g[u"product"], text=product_text, clickable=True),
        ]
        return {u"home": home, u"igou": igou, u"list": list_page}

    def _detail_nodes(self):
        g = self.geo
        out = [node(0, -1, (0, 0, self.W, self.H))]
        index = 20
        for year in YEAR_CHOICES:
            out.append(node(index, 0, g[u"year"][year],
                            text=year, clickable=True))
            index += 1
        top = g[u"qty_label"][1]
        bottom = g[u"qty_value"][3]
        out.append(node(16, 0, (0, top, self.W, bottom)))
        out.append(node(13, 16, g[u"qty_label"], text=u"数量"))
        out.append(node(14, 16, g[u"qty_minus"],
                        class_name=u"android.widget.Button", clickable=True))
        out.append(node(15, 16, g[u"qty_value"],
                        class_name=u"android.widget.EditText",
                        text=str(self.value)))
        out.append(node(17, 16, g[u"qty_plus"],
                        class_name=u"android.widget.Button", clickable=True))
        btn_text = u"已售罄" if self.soldout_on else u"立即抢购"
        out.append(node(30, 0, g[u"action"], text=btn_text,
                        class_name=u"android.widget.Button", clickable=True))
        # 安全组件（填字）验证弹窗：出现后流程必须停手等待
        if self.verify_on:
            out.append(node(40, 0, (100, 900, self.W - 100, 1900),
                            class_name=u"android.widget.FrameLayout"))
            out.append(node(42, 40, (250, 1250, 850, 1370), text=u"填字"))
        # 人工完成验证后界面刷新成订单/支付页
        if self.order_on:
            out.append(node(41, 0, (250, 1000, 850, 1120),
                            text=u"提交订单", clickable=True))
        return out

    # ---------------- 通用能力 ----------------
    def is_connected(self):
        return True

    def _effective_center(self, target):
        nodes = self._node_map()
        cur = target
        while cur is not None:
            b = cur[u"b"]
            if b[2] - b[0] > 1 and b[3] - b[1] > 1:
                return (b[0] + b[2]) // 2, (b[1] + b[3]) // 2
            cur = nodes.get((0, int(cur[u"p"])))
        return None

    @staticmethod
    def _in_region(center, region):
        return center is not None \
            and region[0] <= center[0] <= region[2] \
            and region[1] <= center[1] <= region[3]

    def text_exists(self, text):
        for n in self._all_nodes():
            if text in (n.get(u"t") or u"") \
                    or text in (n.get(u"d") or u""):
                return True
        return False

    def text_exists_in_px_region(self, text, region):
        self.region_calls.append((text, tuple(region)))
        for n in self._all_nodes():
            if text in (n.get(u"t") or u"") \
                    or text in (n.get(u"d") or u""):
                if self._in_region(self._effective_center(n), region):
                    return True
        return False

    def click_text_in_px_region(self, text, region):
        if self.text_exists_in_px_region(text, region):
            self._on_text_click(text)
            return True
        return False

    def find_regex_in_px_region(self, regex, region):
        pattern = re.compile(regex)
        out = []
        for n in self._all_nodes():
            center = self._effective_center(n)
            if not self._in_region(center, region):
                continue
            matched = pattern.search(n.get(u"t") or u"")
            if matched:
                out.append(matched.group(0))
        return out

    def node_center(self, keywords):
        for n in self._all_nodes():
            text = u"%s %s" % (
                n.get(u"t") or u"", n.get(u"d") or u""
            )
            if all(part in text for part in keywords):
                center = self._effective_center(n)
                if center is not None:
                    return center
        return None

    def click_node_by_parts(self, keywords):
        if self.node_center(keywords) is not None:
            self.page = u"detail"
            self.actions.append((u"parts", tuple(keywords)))
            return True
        return False

    def click_text(self, text):
        for n in self._all_nodes():
            if text in (n.get(u"t") or u""):
                self._on_text_click(text)
                return True
        return False

    def _on_text_click(self, text):
        if text == u"i购":
            self.page = u"igou"
        elif text == u"经典":
            self.page = u"list"
        elif text in PRODUCT_FULL_TEXTS:
            # 按完整商品名点击：直接进详情页
            self.page = u"detail"
        elif text in (u"立即抢购", u"立即购买"):
            self.buy_clicks += 1
            # 第二次点击（进入 RAPID 后第一下）弹出安全组件验证弹窗
            if self.buy_clicks >= 2:
                self.verify_on = True

    def tap_px(self, x, y, jitter_px=6):
        self.taps.append((x, y))
        if self.page == u"detail":
            cx, cy = self.plus_center
            if abs(x - cx) < 25 and abs(y - cy) < 25:
                self.value += 1
        return True

    def back(self):
        if self.page == u"detail":
            self.page = u"list"
            return True
        return False

    def dump_nodes(self):
        return [dict(n) for n in self._all_nodes()]

    def save_screenshot(self, path):
        with open(path, u"wb") as handle:
            handle.write(b"sim-screenshot")
        return True


# ------------------------------------------------------------------
# 空节点桥接（停滞重校用）
# ------------------------------------------------------------------

class EmptyBridge(SimBridge):

    def _all_nodes(self):
        return [node(0, -1, (0, 0, self.W, self.H))]


# ------------------------------------------------------------------
# 单设备完整流程
# ------------------------------------------------------------------

def run_device(name, geo, fp, width, height, base_dir):
    random.seed(42)

    # ---------- 第一轮：校准建档 ----------
    cal_logger = ListLogger()
    store = ProfileStore(base_dir=base_dir, logger=cal_logger)
    bridge = SimBridge(geo, width, height)
    calibrator = DeviceCalibrator(bridge, store, cal_logger)
    calibrator._build_fingerprint = lambda: (fp, {}, {})
    ok, profile = calibrator.run()
    assert ok, u"校准失败"
    assert bridge.buy_clicks == 0, u"校准阶段发生了购买点击"
    assert len(profile.controls[u"year_cells"]) == 7
    assert os.path.isfile(store.json_path(fp))
    assert os.path.isfile(store.txt_path(fp))

    # ---------- 第二轮：档案驱动运行 ----------
    bridge.reset_runtime()
    run_logger = ListLogger()
    flow = FlowCore(bridge, run_logger)
    flow.profile = profile
    flow.year_target = u"2026"
    successes = []
    flow.on_popup_success = lambda: successes.append(1)
    flow.reset(datetime(2026, 10, 31, 8, 0, 0))

    ticks = 0
    verify_ticks = 0
    while not flow.is_done and ticks < 5000:
        flow.update(0.01, datetime(2026, 10, 31, 9, 0, ticks % 60))
        ticks += 1
        # 模拟人工完成填字验证：等待约 0.6 秒后界面刷新成订单页
        if flow.state == WAIT_VERIFY:
            verify_ticks += 1
            if verify_ticks == 60:
                bridge.verify_on = False
                bridge.order_on = True

    assert flow.is_done, u"流程未结束"
    assert flow.success, u"未判定抢购成功"
    assert len(successes) == 1, u"成功上报次数异常"
    # 出现验证弹窗后必须停止点击：整场只有首点 + RAPID 第一下
    assert bridge.buy_clicks == 2, u"验证弹窗后仍在点击：%d" \
        % bridge.buy_clicks
    # 数量 2→6：恰好 4 次加号，且落在档案加号中心
    plus_taps = [t for t in bridge.taps
                 if abs(t[0] - bridge.plus_center[0]) < 25]
    assert len(plus_taps) == 4, u"加号点击次数异常"
    # 档案区域被真正使用（经典区域 = 本机型 bounds，不是 legacy）
    assert (u"经典", tuple(geo[u"jd"])) in bridge.region_calls
    return cal_logger, run_logger, flow, bridge


def main():
    base = tempfile.mkdtemp(prefix=u"sim_two_devices_")
    reports = []
    try:
        devices = [
            (u"OPPO PDSM00（1080x2400，density 3.0）",
             OPPO_GEO, OPPO_FP, 1080, 2400),
            (u"华为 GOA-AL80（1200x2652，density 3.25）",
             HUAWEI_GEO, HUAWEI_FP, 1200, 2652),
        ]
        for name, geo, fp, width, height in devices:
            device_dir = os.path.join(base, fp[u"model"])
            os.makedirs(device_dir)
            cal_logger, run_logger, flow, bridge = run_device(
                name, geo, fp, width, height, device_dir
            )
            reports.append((name, fp, cal_logger, run_logger, flow, geo))

        # ---------- legacy 兜底 ----------
        legacy_flow = FlowCore(EmptyBridge(OPPO_GEO, 1080, 2400))
        assert legacy_flow._button_region() == BUTTON_REGION_PX
        assert legacy_flow._region(
            u"igou_tab", IGOU_TAB_REGION_PX
        ) == IGOU_TAB_REGION_PX

        # ---------- 停滞等待不重校（多轮次口径：加载中等同首轮）----------
        empty = EmptyBridge(HUAWEI_GEO, 1200, 2652)
        stall_flow = FlowCore(empty)
        stall_flow._goto(NAVIGATE_IGOU, u"导航中…")
        for _ in range(80):
            stall_flow.update(0.3, datetime.now())
        assert not stall_flow.needs_recalibration

        # ---------- 输出两份日志 ----------
        here = os.path.dirname(os.path.abspath(__file__))
        short_names = {
            OPPO_FP[u"model"]: u"模拟日志_双机_OPPO.txt",
            HUAWEI_FP[u"model"]: u"模拟日志_双机_华为.txt",
        }
        for name, fp, cal_logger, run_logger, flow, geo in reports:
            lines = [
                u"双机模拟日志：%s" % name,
                u"i茅台版本：%s（%d）" % (
                    fp[u"moutai_version"], fp[u"moutai_version_code"]
                ),
                u"",
                u"========== 第一轮：自动校准建档（不抢购） ==========",
            ]
            lines.extend(cal_logger.lines)
            lines.extend([
                u"",
                u"========== 第二轮：档案驱动运行 ==========",
            ])
            lines.extend(run_logger.lines)
            lines.extend([
                u"",
                u"最终状态：%s（%s）" % (flow.state, flow.status),
                u"经典区域 bounds：%s" % geo[u"jd"],
                u"按钮区域 bounds：%s" % geo[u"action"],
            ])
            out_path = os.path.join(here, short_names[fp[u"model"]])
            with open(out_path, u"w", encoding=u"utf-8") as handle:
                handle.write(u"\n".join(lines))
            print(u"已输出：%s" % out_path)

        print(u"全部断言通过：校准建档 / 档案驱动 / 验证弹窗停手 / "
              u"订单页上报 / legacy 兜底 / 停滞等待不重校")
    finally:
        shutil.rmtree(base, ignore_errors=True)


if __name__ == u"__main__":
    main()
