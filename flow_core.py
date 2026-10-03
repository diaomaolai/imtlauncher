# -*- coding: utf-8 -*-
"""
核心流程模块（重构版 v1.0.0）

极简四步：
1. 界面填写倒计时；
2. 到点识别商品文字（"飞天" + "%vol"）；
3. 识别到直接点击该文字节点，并记录点击位置（绝对像素）；
4. 进详情页读右下角：
   - "立即抢购"：立即点击；
   - 开售时间（含 ":"，如 8:00 / 8:05 / 8:14）：返回列表，
     倒计时设为开售时间 +1 秒，到点点击记录的位置。

所有点击均为文字节点点击或绝对像素点击，不做比例换算；
全程商品只点击一次（二次点击的是返回列表后的记录位置）。
"""

from datetime import timedelta

from config import (
    PRODUCT_KEYWORDS,
    BUTTON_REGION_PX,
    BUY_NOW_TEXTS,
    SALE_TIME_REGEX,
    SECOND_CLICK_EXTRA_SECONDS,
    FIND_PRODUCT_TIMEOUT,
    DETAIL_READ_TIMEOUT,
    BACK_SETTLE_SECONDS,
    TAP_JITTER_PX,
)

# 状态
IDLE = u"IDLE"                # 等待首次倒计时
FINDING = u"FINDING"          # 到点，查找商品文字
READING = u"READING"          # 已点商品，读取详情页右下角
WAIT_SECOND = u"WAIT_SECOND"  # 返回列表，等待二次点击时刻
DONE = u"DONE"                # 流程结束（成功或失败）


class FlowCore(object):
    """定时申购状态机"""

    def __init__(self, bridge):
        self.bridge = bridge
        self.first_target = None
        self.second_target = None
        self.display_target = None
        self.recorded_pos = None
        self.state = DONE
        self.status = u""
        self.success = False
        self._elapsed = 0.0
        self._back_settle = 0.0

    # ---------------- 生命周期 ----------------
    def reset(self, first_target):
        """武装流程，first_target 为首次倒计时目标时刻"""
        self.first_target = first_target
        self.second_target = None
        self.display_target = first_target
        self.recorded_pos = None
        self.state = IDLE
        self.status = u"等待启动时刻…"
        self.success = False
        self._elapsed = 0.0
        self._back_settle = 0.0

    @property
    def is_done(self):
        return self.state == DONE

    def _finish(self, success, message):
        self.success = success
        self.status = message
        self.state = DONE

    # ---------------- 主循环 ----------------
    def update(self, dt, now):
        if self.state == IDLE:
            self._update_idle(now)
        elif self.state == FINDING:
            self._update_finding(dt, now)
        elif self.state == READING:
            self._update_reading(dt, now)
        elif self.state == WAIT_SECOND:
            self._update_wait_second(dt, now)

    # ---------------- 各状态 ----------------
    def _update_idle(self, now):
        """等待首次倒计时到达"""
        if now >= self.first_target:
            print(u"倒计时到达，开始识别商品「飞天%vol」")
            self.state = FINDING
            self._elapsed = 0.0
            self.status = u"正在识别商品…"

    def _update_finding(self, dt, now):
        """查找商品文字：找到即记录位置并点击节点"""
        if not self.bridge.is_connected():
            self._finish(
                False,
                u"无障碍服务未开启，请先到设置中开启后重新定时",
            )
            return

        center = self.bridge.node_center(PRODUCT_KEYWORDS)
        if center is not None:
            self.recorded_pos = center
            print(u"找到商品，点击位置 (%d, %d)" % center)
            self.bridge.click_node_by_parts(PRODUCT_KEYWORDS)
            self.state = READING
            self._elapsed = 0.0
            self.status = u"已点击商品，读取详情页…"
            return

        self._elapsed += dt
        self.status = u"正在识别商品文字…（已等待 %.0f 秒）" % self._elapsed
        if self._elapsed >= FIND_PRODUCT_TIMEOUT:
            self._finish(False, u"未找到商品文字，流程中止")

    def _update_reading(self, dt, now):
        """详情页：优先识别立即抢购；否则读取开售时间"""
        self._elapsed += dt

        # 1) 立即抢购：识别到即点击
        for text in BUY_NOW_TEXTS:
            if self.bridge.click_text(text):
                print(u"识别到「%s」，已点击购买" % text)
                self._finish(True, u"已点击「%s」" % text)
                return

        # 2) 开售时间（右下角区域，含 ":"）
        hits = self.bridge.find_regex_in_px_region(
            SALE_TIME_REGEX, BUTTON_REGION_PX
        )
        if hits:
            hhmm = hits[0]
            try:
                hour, minute = (int(v) for v in hhmm.split(u":"))
            except ValueError:
                hour = minute = None
            if hour is not None:
                second_target = now.replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                ) + timedelta(seconds=SECOND_CLICK_EXTRA_SECONDS)
                if second_target <= now:
                    self._finish(
                        False,
                        u"读取到开售时间 %s 已过，流程中止" % hhmm,
                    )
                    return
                print(
                    u"读取到开售时间 %s，返回列表，二次点击时刻 %s"
                    % (hhmm, second_target.strftime(u"%H:%M:%S"))
                )
                self.bridge.back()
                self.second_target = second_target
                self.display_target = second_target
                self.state = WAIT_SECOND
                self._back_settle = 0.0
                self.status = u"已返回列表，等待 %s 二次点击" \
                    % second_target.strftime(u"%H:%M:%S")
                return

        # 3) 超时未识别
        if self._elapsed >= DETAIL_READ_TIMEOUT:
            self._finish(
                False,
                u"详情页未识别到开售时间或立即抢购，流程中止",
            )

    def _update_wait_second(self, dt, now):
        """返回列表后等待二次点击时刻，到点点击记录的位置"""
        self._back_settle += dt
        if self._back_settle < BACK_SETTLE_SECONDS:
            return
        if now >= self.second_target and self.recorded_pos is not None:
            x, y = self.recorded_pos
            print(u"二次点击商品位置 (%d, %d)" % (x, y))
            self.bridge.tap_px(x, y, TAP_JITTER_PX)
            self._finish(True, u"已在 %s 二次点击商品"
                         % self.second_target.strftime(u"%H:%M:%S"))
