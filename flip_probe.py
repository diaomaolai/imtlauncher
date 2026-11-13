# -*- coding: utf-8 -*-
"""
按钮翻转探针（App 内诊断功能，不依赖电脑/adb）。

回答一个问题：
    「停在商品详情页不动，整点到了，按钮会不会自己从『xx:xx投放』
      变成『立即购买』？」

为什么需要它：抢购第一击慢，主要慢在「整点后点进详情 → 页面重载 2~6 秒」。
如果按钮能原地翻转，就可以提前停在详情页，第一击压到 0.3 秒级；如果必须
整点后重进，那「在列表等」就是唯一解。这决定了下一版怎么改。

做法：
    1. 复用 FlowCore 的页面判定/点击逻辑，把 App 导航到详情页；
    2. 从目标时刻前 lead 秒开始，反复取按钮区域颜色（一次截图一次采样）；
    3. 记录「灰 → 黄橙」的翻转时刻，结果写成 txt + csv 到日志目录。

取色用的是 Java 的 maxRedInRegions：一次截图内取「最红像素」，
不会被白底稀释，比平均色更适合判断细边框/文字颜色变化。
"""

import threading
import time
from datetime import datetime, timedelta

from config import (
    BUY_NOW_TEXTS,
    YEAR_RED_MIN,
    PROBE_LEAD_SECONDS,
    PROBE_TAIL_SECONDS,
    PROBE_SAMPLE_GAP,
    IGOU_TAB_TEXT,
    IGOU_TAB_REGION_PX,
    JINGDIAN_TAB_TEXT,
    JINGDIAN_TAB_REGION_PX,
)
from flow_core import FlowCore


def _redness(rgb):
    """红度 R - max(G,B)；取不到返回 -1。"""
    if not rgb:
        return -1
    red, green, blue = rgb
    return int(red) - max(int(green), int(blue))


class FlipProbe(threading.Thread):
    """把 App 导航到详情页，测量按钮在整点前后是否原地翻转。"""

    def __init__(self, bridge, logger, target, profile=None,
                 lead=None, tail=None, sample_gap=None, nav_pause=1.2):
        """初始化 FlipProbe 实例。"""
        super(FlipProbe, self).__init__(daemon=True)
        self.bridge = bridge
        self.logger = logger
        self.target = target
        self.profile = profile
        self.lead = PROBE_LEAD_SECONDS if lead is None else float(lead)
        self.tail = PROBE_TAIL_SECONDS if tail is None else float(tail)
        self.sample_gap = (
            PROBE_SAMPLE_GAP if sample_gap is None else float(sample_gap)
        )
        # 导航时每次点击后的等待；单测里调小，真机上 1.2 秒比较稳
        self.nav_pause = float(nav_pause)
        self._stop = threading.Event()
        self.flow = FlowCore(bridge, logger)
        self.flow.profile = profile
        self.result_path = u""

    def stop(self):
        """请求停止线程。"""
        self._stop.set()

    def _log(self, line):
        """写一行日志。"""
        if self.logger is not None:
            try:
                self.logger.log(line)
            except Exception:
                pass

    # ---------------- 导航 ----------------

    def _navigate_to_detail(self, timeout=90.0):
        """
        用 FlowCore 的同一套判定把 App 带到详情页。

        返回 True 表示已在详情页。失败时打印当前页面类型，方便排查。
        """
        started = time.monotonic()
        while not self._stop.is_set():
            if time.monotonic() - started > timeout:
                self._log(u"探针：导航超时，放弃")
                return False
            now = datetime.now()
            # 开屏广告 / 首页弹窗 / 权限弹窗
            if self.flow._dismiss_overlay(now):
                time.sleep(min(self.nav_pause, 0.5))
                continue
            page = self.flow._current_page()
            if page == u"detail":
                self._log(u"探针：已进入详情页")
                return True
            if page == u"list":
                if self.flow._click_product():
                    time.sleep(self.nav_pause)
                    continue
            elif page == u"igou":
                region = self.flow._region(
                    u"jingdian_tab", JINGDIAN_TAB_REGION_PX
                )
                if not self.bridge.click_text_in_px_region(
                        JINGDIAN_TAB_TEXT, region):
                    self.bridge.click_text(JINGDIAN_TAB_TEXT)
                time.sleep(self.nav_pause)
                continue
            elif page == u"home":
                region = self.flow._region(u"igou_tab", IGOU_TAB_REGION_PX)
                if not self.bridge.click_text_in_px_region(
                        IGOU_TAB_TEXT, region):
                    self.bridge.click_text(IGOU_TAB_TEXT)
                time.sleep(self.nav_pause)
                continue
            else:
                # 认不出：可能是加载中，等一等再看
                time.sleep(self.nav_pause)
                continue
            time.sleep(self.nav_pause)
        return False

    # ---------------- 采样 ----------------

    def _sample_region(self):
        """按钮取色区：与生产逻辑一致（左侧竖带，避开文字与圆角）。"""
        try:
            region = self.flow._button_sample_region()
        except Exception:
            region = None
        return region

    def _sample(self, region):
        """取一次颜色，返回 (r,g,b) 或 None。"""
        sampler = getattr(self.bridge, "max_red_in_regions", None)
        if callable(sampler):
            try:
                colors = sampler([region])
            except Exception:
                colors = None
            if colors:
                return colors[0]
            return None
        # 旧 APK：退回平均色
        try:
            return self.bridge.average_color_in_px_region(region)
        except Exception:
            return None

    def run(self):
        """线程主循环。"""
        if not self.bridge.is_connected():
            self._log(u"探针：无障碍未开启，无法测量")
            return

        self._log(
            u"探针开始：目标 %s，提前 %.0f 秒采样，整点后再采 %.0f 秒"
            % (self.target.strftime(u"%H:%M:%S"), self.lead, self.tail)
        )

        # 不要一上来就停在详情页：页面会被 App 自己刷新，也容易吃风控。
        # 目标时刻前「提前量 + 30 秒」再开始导航。
        nav_at = self.target - timedelta(seconds=self.lead + 30.0)
        while not self._stop.is_set() and datetime.now() < nav_at:
            time.sleep(1.0)

        if not self._navigate_to_detail():
            return

        region = self._sample_region()
        if region is None:
            region = self.flow._button_region()
        self._log(
            u"探针：取色区 (%d,%d)-(%d,%d)"
            % (region[0], region[1], region[2], region[3])
        )

        # 按钮当前文字，作为"之前"的存证
        before_text = self._button_text()

        sample_from = self.target - timedelta(seconds=self.lead)
        sample_to = self.target + timedelta(seconds=self.tail)
        self._log(
            u"探针：等待采样窗口 %s ~ %s"
            % (sample_from.strftime(u"%H:%M:%S"),
               sample_to.strftime(u"%H:%M:%S"))
        )
        while not self._stop.is_set() and datetime.now() < sample_from:
            time.sleep(0.3)

        rows = [u"time,elapsed,r,g,b,redness,is_buy"]
        prev_buy = None
        first_buy = None
        flip_at = None

        while not self._stop.is_set() and datetime.now() < sample_to:
            stamp = datetime.now()
            rgb = self._sample(region)
            if rgb is not None:
                redness = _redness(rgb)
                is_buy = redness >= YEAR_RED_MIN
                elapsed = (stamp - self.target).total_seconds()
                rows.append(u"%s,%.3f,%d,%d,%d,%d,%s" % (
                    stamp.strftime(u"%H:%M:%S.%f")[:-3],
                    elapsed, rgb[0], rgb[1], rgb[2], redness, is_buy,
                ))
                if prev_buy is not None and prev_buy != is_buy:
                    flip_at = stamp
                    self._log(
                        u"探针：按钮翻转 %s  RGB=(%d,%d,%d)"
                        % (u"灰→可点" if is_buy else u"可点→灰",
                           rgb[0], rgb[1], rgb[2])
                    )
                    if is_buy and first_buy is None:
                        first_buy = stamp
                prev_buy = is_buy
            time.sleep(self.sample_gap)

        self._write_result(rows, before_text, first_buy, flip_at)

    def _button_text(self):
        """当前按钮上的文字（投放时间/立即购买/售罄），取不到返回空串。"""
        for text in BUY_NOW_TEXTS:
            try:
                if self.bridge.text_exists(text):
                    return text
            except Exception:
                pass
        try:
            hits = self.flow._button_time_hits()
            if hits:
                return hits[0]
        except Exception:
            pass
        return u""

    def _write_result(self, rows, before_text, first_buy, flip_at):
        """写 txt 结论 + csv 明细。"""
        after_text = self._button_text()
        path = self._resolve_path()
        summary = []
        summary.append(u"目标时刻：%s" % self.target.strftime(u"%H:%M:%S"))
        summary.append(u"采样点数：%d" % (len(rows) - 1))
        summary.append(u"开始前按钮：%s" % (before_text or u"(未识别)"))
        summary.append(u"结束后按钮：%s" % (after_text or u"(未识别)"))
        if len(rows) - 1 == 0:
            # 一个样本都没有：导航把采样窗口吃掉了。不能误报成"按钮没翻转"。
            summary.append(u"首次可点：无样本")
            summary.append(
                u"结论：未采到样本（导航耗时超过采样窗口），本次无效，请重跑"
            )
        elif first_buy is not None:
            delta = (first_buy - self.target).total_seconds()
            summary.append(
                u"首次可点：%s（相对整点 %+.3f 秒）"
                % (first_buy.strftime(u"%H:%M:%S.%f")[:-3], delta)
            )
            summary.append(
                u"结论：停在详情页不动，按钮【会】在整点后自己翻转"
            )
        else:
            summary.append(u"首次可点：窗口内未出现黄橙色")
            summary.append(
                u"结论：按钮没有自己翻转（或本场无货），需要整点后重进"
            )
        summary.append(u"CSV：%s" % path)

        base = path[:-4] if path.endswith(u".csv") else path
        try:
            with open(base + u".txt", u"w", encoding="utf-8") as handle:
                handle.write(u"\n".join(summary) + u"\n")
            with open(base + u".csv", u"w", encoding="utf-8") as handle:
                handle.write(u"\n".join(rows) + u"\n")
        except Exception as exc:
            self._log(u"探针：结果写入失败 %s" % exc)
            return

        self.result_path = base + u".txt"
        for line in summary:
            self._log(u"探针结果：%s" % line)
        self._log(u"探针：结果已写入 %s" % self.result_path)

    def _resolve_path(self):
        """结果文件放在与日志同一目录。"""
        try:
            from app_logger import resolve_log_dir
            import os
            folder = resolve_log_dir()
        except Exception:
            import os
            folder = os.getcwd()
        stamp = datetime.now().strftime(u"%Y%m%d_%H%M%S")
        import os
        return os.path.join(folder, u"flip_probe_%s.csv" % stamp)
