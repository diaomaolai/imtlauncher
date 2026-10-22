# -*- coding: utf-8 -*-
"""
多场次自动启动监控。

场次时间（config.py，可改）：
  上午：09:00 09:05 09:10 09:15 09:20 09:25
  晚上：20:00 20:05 20:10 20:15 20:20 20:25
  每个时间节点提前 SLOT_LEAD_SECONDS（默认 180 秒，即 3 分钟）自启动。

行为：
- 每个场次的「提前触发时刻」（场次整点 - SLOT_LEAD_SECONDS）后
  SLOT_FIRE_WINDOW_SECONDS 窗口内检查一次：
  - 抢购流程已在运行 → 只记日志，跳过；
  - 未启动 → 自动拉起 i茅台，并回调主程序立即武装流程，
    状态机当场开始导航（i购→经典→进详情），读到未来场次时间
    （如 09:00投放）后返回列表 WAIT 整点，到点再点记录位置进入。
- 同一场次当天只触发一次，不重复启动。
- 总开关 ENABLE_SLOT_AUTOSTART=False 时本模块不产生任何动作。
- 武装后流程先走 NAV 导航：区域识别点「i购」→ 点「经典」，
  经典列表出现飞天商品后才进入识别（见 flow_core.py）。
"""

import threading
from datetime import datetime, timedelta

from config import (
    ENABLE_SLOT_AUTOSTART,
    MORNING_SLOTS,
    EVENING_SLOTS,
    SLOT_FIRE_WINDOW_SECONDS,
    SLOT_LEAD_SECONDS,
    SLOT_APP_LAUNCH_LOG,
)
from android_launcher import launch_moutai


def _slot_target(hhmm, now):
    """把 "HH:MM" 落到今天的该时刻"""
    hour, minute = (int(v) for v in hhmm.split(u":"))
    return now.replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )


class SlotMonitor(threading.Thread):
    """场次监控守护线程，每 0.5 秒检查一次"""

    def __init__(self, is_running_fn, autostart_fn, logger=None):
        super(SlotMonitor, self).__init__(daemon=True)
        self.is_running_fn = is_running_fn
        self.autostart_fn = autostart_fn
        self.logger = logger
        self._fired = set()
        self._stop_event = threading.Event()
        # 运行期开关：卡密授权登录成功后才置 True；未登录时空转
        self.enabled = False

    def set_enabled(self, enabled):
        """卡密登录解锁/锁定到点自启动"""
        self.enabled = bool(enabled)

    def stop(self):
        self._stop_event.set()

    def _log(self, line):
        if self.logger is not None:
            self.logger.log(line)
        else:
            print(line)

    def check_once(self, now):
        """供线程每轮调用，也可单测时直接调用。

        触发时刻 = 场次整点 - SLOT_LEAD_SECONDS（提前 3 分钟）。
        回调 autostart_fn 传入场次整点本身，状态机提前武装开始导航，
        读到未来场次时间后在列表 WAIT 到整点。
        """
        if not ENABLE_SLOT_AUTOSTART or not self.enabled:
            return
        for hhmm in tuple(MORNING_SLOTS) + tuple(EVENING_SLOTS):
            try:
                slot_target = _slot_target(hhmm, now)
            except Exception:
                continue
            fire_target = slot_target - timedelta(
                seconds=SLOT_LEAD_SECONDS
            )
            delta = (now - fire_target).total_seconds()
            if delta < 0 or delta > SLOT_FIRE_WINDOW_SECONDS:
                continue

            key = (now.strftime(u"%Y-%m-%d"), hhmm)
            if key in self._fired:
                continue
            self._fired.add(key)

            try:
                running = bool(self.is_running_fn())
            except Exception:
                running = False

            if running:
                self._log(
                    u"场次 %s 提前 %d 秒触发，流程已在运行，跳过自启动"
                    % (hhmm, SLOT_LEAD_SECONDS)
                )
                continue

            self._log(
                u"场次 %s 提前 %d 秒触发，流程未启动，执行自启动"
                % (hhmm, SLOT_LEAD_SECONDS)
            )
            launch_moutai(self.logger)
            self._log(SLOT_APP_LAUNCH_LOG)
            try:
                self.autostart_fn(slot_target)
            except Exception as exc:
                self._log(u"自启动武装流程异常：%s" % exc)

    def run(self):
        while not self._stop_event.is_set():
            try:
                self.check_once(datetime.now())
            except Exception as exc:
                self._log(u"场次监控异常：%s" % exc)
            self._stop_event.wait(0.5)
