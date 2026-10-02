# -*- coding: utf-8 -*-
"""
i茅台 i购定时自动申购流程（两段式状态机）

第一阶段（设定时刻，如 08:00:01）：
  启动 i茅台 → 点击底部 "i购" → 上滑查找
  "飞天53%vol 500ml贵州茅台酒(带杯)" → 点进商品详情页，
  读取右下角开售时间（如 08:05）→ 返回列表待命。

第二阶段（开售时间 +1 秒，如 08:05:01）：
  再次点击商品进入详情 → 点击购买按钮（立即购买等）；
  按钮识别不到时按屏幕比例兜底点击。

本模块不直接依赖 Kivy，由主程序以固定间隔调用 update(dt, now)，
电脑端可注入模拟的 launcher / bridge 做完整流程演练。
"""

import re
from datetime import timedelta

from config import (
    TARGET_PACKAGE,
    I_GOU_TAB_TEXT,
    PRODUCT_KEYWORDS,
    SALE_TIME_REGEX,
    SECOND_CLICK_EXTRA_SECONDS,
    FINAL_BUTTON_TEXTS,
    SCROLL_INTERVAL,
    BUY_CLICK_WAIT_SECONDS,
    BUY_BUTTON_REGION,
    BACK_LIST_TIMEOUT,
    FALLBACK_FINAL_CLICK_RATIO,
)

# 状态常量
IDLE = "IDLE"
LAUNCHING = "LAUNCHING"
ENTER_I_GOU = "ENTER_I_GOU"
SEARCHING = "SEARCHING"
RECON_DETAIL = "RECON_DETAIL"
READ_SALE_TIME = "READ_SALE_TIME"
BACK_TO_LIST = "BACK_TO_LIST"
WAIT_SALE = "WAIT_SALE"
CLICK_PRODUCT = "CLICK_PRODUCT"
WAIT_BUY_BUTTON = "WAIT_BUY_BUTTON"
DONE = "DONE"


def choose_sale_time(matches, now):
    """
    从正则匹配文字中解析开售时刻。
    返回未来最早的 datetime；若只有已过去的时刻，返回 now（视为已开售）；
    没有有效时间返回 None。
    """
    candidates = []
    for text in matches:
        match = re.search(r"(\d{1,2}):(\d{2})", text)
        if not match:
            continue
        hour, minute = int(match.group(1)), int(match.group(2))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            continue
        candidates.append(
            now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        )

    future = [t for t in candidates if t > now]
    if future:
        return min(future)
    if candidates:
        # 开售时间点已过，按"立即开售"处理
        return now
    return None


class PurchaseFlow(object):
    """i购定时自动申购流程"""

    def __init__(self, launcher, bridge):
        self.launcher = launcher
        self.bridge = bridge

        self.state = IDLE
        self.launch_target = None
        self.sale_target = None
        self.display_target = None  # 供界面倒计时
        self.recon_done = False

        # 计时器与计数
        self._timer = 0.0
        self._stage_elapsed = 0.0
        self._scroll_count = 0
        self._attempts = 0
        self._last_scroll = None

        self.status = u""
        self.success = False

    # ---------------- 生命周期 ----------------
    def reset(self, launch_target):
        """武装流程，launch_target 为启动 i茅台 的目标时刻"""
        self.launch_target = launch_target
        self.sale_target = None
        self.display_target = launch_target
        self.recon_done = False

        self.state = IDLE
        self._timer = 0.0
        self._stage_elapsed = 0.0
        self._scroll_count = 0
        self._attempts = 0
        self._last_scroll = None

        self.success = False
        self.status = u"等待启动时刻…"

    @property
    def is_done(self):
        return self.state == DONE

    # ---------------- 主循环 ----------------
    def update(self, dt, now=None):
        if self.state == IDLE:
            self._update_idle(now)
        elif self.state == LAUNCHING:
            self._update_launching(dt)
        elif self.state == ENTER_I_GOU:
            self._update_enter_i_gou(dt)
        elif self.state == SEARCHING:
            self._update_searching(dt, now)
        elif self.state == RECON_DETAIL:
            self._update_recon_detail()
        elif self.state == READ_SALE_TIME:
            self._update_read_sale_time(dt, now)
        elif self.state == BACK_TO_LIST:
            self._update_back_to_list(dt, now)
        elif self.state == WAIT_SALE:
            self._update_wait_sale(now)
        elif self.state == CLICK_PRODUCT:
            self._update_click_product()
        elif self.state == WAIT_BUY_BUTTON:
            self._update_wait_buy_button(dt)
        return self.status

    # ---------------- 第一阶段 ----------------
    def _update_idle(self, now):
        """到达启动时刻则开始；安卓环境先确认无障碍已连接"""
        if self.launch_target is None or now is None:
            return
        if now < self.launch_target:
            return

        if self.launcher.is_android and not self.bridge.is_connected():
            self._finish(
                False,
                u"无障碍服务未开启，请先到设置中开启后重新定时",
            )
            return

        self.state = LAUNCHING
        self._timer = 0.0
        self.status = u"启动时刻到，正在启动 i茅台…"

    def _update_launching(self, dt):
        """启动 i茅台并等待冷启动"""
        if self._timer == 0.0:
            print("正在启动I茅台")
            if self.launcher.is_android:
                ok, message = self.launcher.launch(TARGET_PACKAGE)
                if not ok:
                    self._finish(False, message)
                    return
        self._timer += dt
        if self._timer >= 3.0:
            self._set_state(ENTER_I_GOU, u"正在进入 i购…")

    def _update_enter_i_gou(self, dt):
        """点击 i购 标签，直到商品列表出现或超时"""
        if self.bridge.node_contains_all(PRODUCT_KEYWORDS):
            self._set_state(SEARCHING, u"已进入 i购，查找目标商品…")
            return

        self._stage_elapsed += dt
        if self._stage_elapsed >= 8.0:
            self._set_state(SEARCHING, u"正在 i购中查找目标商品…")
            return

        self._timer += dt
        if self._timer >= 1.5:
            print("正在访问i购")
            self.bridge.click_text(I_GOU_TAB_TEXT)
            self._timer = 0.0

    def _update_searching(self, dt, now):
        """周期性上滑，直到找到目标商品"""
        if self.bridge.node_contains_all(PRODUCT_KEYWORDS):
            if self.recon_done:
                # 第二阶段列表丢失后重新找到：直接继续待命
                self._set_state(WAIT_SALE, u"已重新定位商品，继续待命")
            else:
                self._set_state(
                    RECON_DETAIL, u"已找到目标商品，正在进入详情侦察…"
                )
            return

        self._stage_elapsed += dt
        if self._stage_elapsed - (self._last_scroll or 0.0) >= SCROLL_INTERVAL:
            print("正在模拟人为滑动")
            if not self.bridge.scroll_forward():
                self.bridge.swipe_up()
            self._scroll_count += 1
            self._last_scroll = self._stage_elapsed
            self.status = u"查找商品中（已上滑 %d 次）" % self._scroll_count

    def _update_recon_detail(self):
        """第一次点击商品，进入详情页"""
        clicked = self.bridge.click_all_parts(PRODUCT_KEYWORDS)
        self._attempts += 1
        if clicked or self._attempts >= 3:
            self.recon_done = True
            self._set_state(READ_SALE_TIME, u"已进入详情页，读取开售时间…")

    def _update_read_sale_time(self, dt, now):
        """
        侦察详情页：
        - 右下角是购买按钮（立即购买等）：立即点击；
        - 1 秒内没识别到购买按钮，且右下角是开售时间（特征 ":"）：
          返回列表待命；
        - 两者都没有：按预设位置兜底点击。
        """
        self._stage_elapsed += dt

        # 情况一：右下角按钮区出现购买按钮，立即点击
        for text in FINAL_BUTTON_TEXTS:
            if self.bridge.click_text(text, region=BUY_BUTTON_REGION):
                self._finish(True, u"商品已开售，已点击 \"%s\"" % text)
                return

        # 未到识别窗口：继续等待购买按钮出现
        if self._stage_elapsed < BUY_CLICK_WAIT_SECONDS:
            return

        # 超过窗口没有购买按钮：检查按钮区开售时间（特征 ":"）
        matches = self.bridge.find_regex_texts(
            SALE_TIME_REGEX, region=BUY_BUTTON_REGION
        )
        sale = choose_sale_time(matches, now)
        if sale is not None:
            self.sale_target = sale + timedelta(
                seconds=SECOND_CLICK_EXTRA_SECONDS
            )
            self.display_target = self.sale_target
            self._set_state(
                BACK_TO_LIST,
                u"读到开售时间，返回列表待命（二次点击：%s）"
                % self.sale_target.strftime(u"%H:%M:%S"),
            )
            return

        # 既没有购买按钮、也没有开售时间：兜底点击
        self._fallback_or_fail(
            u"详情页未识别到按钮或开售时间，已按预设位置点击"
        )

    def _update_back_to_list(self, dt, now):
        """返回商品列表，确认商品仍在屏幕上"""
        if self._timer == 0.0:
            self.bridge.back()

        if self.bridge.node_contains_all(PRODUCT_KEYWORDS):
            self._set_state(
                WAIT_SALE,
                u"已返回列表，等待 %s 二次点击"
                % self.sale_target.strftime(u"%H:%M:%S"),
            )
            return

        self._timer += dt
        if self._timer >= 1.0:
            self.bridge.back()  # 仍在详情页则再按返回
            self._timer = 0.0
        self._stage_elapsed += dt
        if self._stage_elapsed >= BACK_LIST_TIMEOUT:
            self._finish(False, u"返回列表失败，流程中止")

    # ---------------- 第二阶段 ----------------
    def _update_wait_sale(self, now):
        """列表上待命，到二次点击时刻则点击商品"""
        if not self.bridge.node_contains_all(PRODUCT_KEYWORDS):
            # 商品滑出屏幕，回查找阶段（recon_done 已为 True）
            self._set_state(SEARCHING, u"商品不在屏幕上，重新查找…")
            return

        if now is not None and now >= self.sale_target:
            self._set_state(CLICK_PRODUCT, u"二次点击时刻到，点击商品…")

    def _update_click_product(self):
        """第二次点击商品，进入详情页"""
        clicked = self.bridge.click_all_parts(PRODUCT_KEYWORDS)
        self._attempts += 1
        if clicked or self._attempts >= 5:
            self._set_state(WAIT_BUY_BUTTON, u"已进入详情页，等待购买按钮…")

    def _update_wait_buy_button(self, dt):
        """1 秒识别窗口内在按钮区点击购买按钮，超时立刻兜底坐标点击"""
        self._stage_elapsed += dt

        for text in FINAL_BUTTON_TEXTS:
            if self.bridge.click_text(text, region=BUY_BUTTON_REGION):
                self._finish(True, u"已点击 \"%s\"，流程完成" % text)
                return

        if self._stage_elapsed >= BUY_CLICK_WAIT_SECONDS:
            self._fallback_or_fail(
                u"未识别到按钮，已按预设位置兜底点击"
            )

    # ---------------- 工具 ----------------
    def _fallback_or_fail(self, success_text):
        """按预设屏幕比例兜底点击；未配置或点击失败则失败收尾"""
        if FALLBACK_FINAL_CLICK_RATIO is not None:
            x_ratio, y_ratio = FALLBACK_FINAL_CLICK_RATIO
            if self.bridge.tap_ratio(x_ratio, y_ratio):
                self._finish(True, success_text)
                return
        self._finish(False, u"未识别到可点击内容，且兜底点击未成功")

    def _set_state(self, state, status=None):
        self.state = state
        self._timer = 0.0
        self._stage_elapsed = 0.0
        self._last_scroll = None
        self._attempts = 0
        if status is not None:
            self.status = status

    def _finish(self, success, text):
        self.success = success
        self.status = text
        self.state = DONE
