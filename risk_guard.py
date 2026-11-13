# -*- coding: utf-8 -*-
"""
风控自愈守护。

背景（真机确认）：每天 09:00–10:00、20:00–21:00 两场抢购期间，一旦触发
风控，i茅台 会弹「当前设备异常，i茅台无法运行！」并在几秒后**杀掉自己的
进程**。此时状态机还停在 READ/RAPID 之类的中间态，页面已经从它脚下消失。

本模块负责在这两个窗口内持续自检，发现被杀了就：
    冷却 → 重新拉起 → 通知状态机强制回到 NAV（重新走 i购→经典→商品）

单独成线程的理由：主流程可能正卡在某个状态里，指望它自己发现「App 没了」
要多绕 6~10 秒；而风控杀进程恰恰发生在最宝贵的整点窗口。

本模块不依赖 Kivy，可在电脑上直接单测。
"""

import threading
from datetime import datetime

from config import (
    SALE_WINDOWS,
    RISK_KILL_TEXTS,
    RISK_CHECK_INTERVAL,
    RISK_COOLDOWN_SECONDS,
    RISK_MAX_RELAUNCH,
    IGNORED_FOREGROUND_PACKAGES,
)
from android_launcher import MOUTAI_PACKAGE


def in_sale_window(now):
    """当前是否在两场抢购窗口内（09:00–10:00、20:00–21:00）。"""
    for start_h, start_m, end_h, end_m in SALE_WINDOWS:
        start = now.replace(
            hour=start_h, minute=start_m, second=0, microsecond=0
        )
        end = now.replace(
            hour=end_h, minute=end_m, second=0, microsecond=0
        )
        if start <= now <= end:
            return True
    return False


class RiskGuardian(threading.Thread):
    """两场窗口内自检 i茅台 是否被风控杀掉，并负责冷却重拉。"""

    def __init__(self, bridge, flow, logger, launch_fn,
                 cooldown=None, check_interval=None, max_relaunch=None):
        """初始化 RiskGuardian 实例。"""
        super(RiskGuardian, self).__init__(daemon=True)
        self.bridge = bridge
        self.flow = flow
        self.logger = logger
        self.launch_fn = launch_fn
        self.cooldown = (
            RISK_COOLDOWN_SECONDS if cooldown is None else float(cooldown)
        )
        self.check_interval = (
            RISK_CHECK_INTERVAL if check_interval is None
            else float(check_interval)
        )
        self.max_relaunch = (
            RISK_MAX_RELAUNCH if max_relaunch is None else int(max_relaunch)
        )
        self._stop = threading.Event()
        self.relaunch_count = 0

    def stop(self):
        """请求停止线程。"""
        self._stop.set()

    def _log(self, line):
        """写一行日志。"""
        if self.logger is None:
            return
        try:
            self.logger.log(line)
        except Exception:
            pass

    def detect(self):
        """
        返回「被杀」的原因；正常时返回 None。

        判定顺序：
          1) 屏幕上有风控弹窗文字 → 直接判定被杀（此时进程还没退）；
          2) 前台包名既不是 i茅台、也不在白名单（我们自己的进程/系统 UI）
             → 判定进程已经退出。
        取不到包名（旧 APK）时只靠文字判，不误杀。
        """
        try:
            if self.bridge.any_text_exists(RISK_KILL_TEXTS):
                return u"识别到风控弹窗（当前设备异常）"
        except Exception:
            pass
        try:
            package = self.bridge.current_package()
        except Exception:
            package = None
        if not package:
            return None
        if package == MOUTAI_PACKAGE:
            return None
        if package in IGNORED_FOREGROUND_PACKAGES:
            return None
        return u"i茅台 已退出（前台 %s）" % package

    def recover(self, reason):
        """冷却 → 重拉 → 通知状态机回 NAV。"""
        self.relaunch_count += 1
        self._log(
            u"风控自愈：%s；冷却 %.0f 秒后重拉（本场第 %d/%d 次）"
            % (reason, self.cooldown,
               self.relaunch_count, self.max_relaunch)
        )
        self._stop.wait(self.cooldown)
        if self._stop.is_set() or self.flow.is_done:
            return False
        try:
            self.launch_fn()
        except Exception as exc:
            self._log(u"风控重拉失败：%s" % exc)
            return False
        # 冷启动约 13 秒：先让它把开屏/广告走完，再切回 NAV
        self._stop.wait(3.0)
        try:
            self.flow.force_restart_to_nav(reason)
        except Exception as exc:
            self._log(u"风控重拉后切换状态失败：%s" % exc)
            return False
        return True

    def run(self):
        """线程主循环。"""
        while not self._stop.is_set() and not self.flow.is_done:
            self._stop.wait(self.check_interval)
            if self._stop.is_set() or self.flow.is_done:
                break
            try:
                now = self.flow.server_now()
            except Exception:
                now = datetime.now()
            if not in_sale_window(now):
                continue
            if self.relaunch_count >= self.max_relaunch:
                continue
            reason = self.detect()
            if reason is None:
                continue
            self.recover(reason)
