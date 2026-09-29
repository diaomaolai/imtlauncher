# -*- coding: utf-8 -*-
"""
定时调度模块

职责：
1. 解析 UI 中填写的时间字符串（如 "08:00:01"）；
2. 计算目标时刻（只填时分秒时默认今天，今天已过则顺延到明天）；
3. 提供倒计时与"是否到点"判断。

本模块不依赖 Kivy，方便在电脑端直接单元测试。
"""

from datetime import datetime, timedelta

# 支持的时间格式，按顺序尝试解析
TIME_FORMATS = (
    "%H:%M:%S.%f",  # 08:00:01.5  （含小数秒）
    "%H:%M:%S",     # 08:00:01
    "%H:%M",        # 08:00
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
)

# strptime 只解析时分秒时，年份会是 1900，以此判断"纯时间"输入
_TIME_ONLY_MARKER_YEAR = 1900


def parse_target_time(text, now=None):
    """
    解析时间字符串，返回目标 datetime。

    - "08:00:01"：今天 08:00:01；若此刻已过，则自动顺延到明天；
    - "2026-10-01 08:00:01"：必须是未来时间，否则抛 ValueError。

    解析失败或时间已过（完整日期写法）时抛 ValueError，并带中文说明。
    """
    now = now if now is not None else datetime.now()
    raw = (text or "").strip()
    if not raw:
        raise ValueError(u"时间不能为空，请填写 HH:MM:SS，例如 08:00:01")

    parsed = None
    for fmt in TIME_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt)
            break
        except ValueError:
            continue

    if parsed is None:
        raise ValueError(
            u"时间格式不正确，请填写 HH:MM:SS，例如 08:00:01"
        )

    if parsed.year == _TIME_ONLY_MARKER_YEAR:
        # 只填了时分秒：补成今天的日期
        target = parsed.replace(
            year=now.year, month=now.month, day=now.day
        )
        if target <= now:
            # 今天的这个时刻已经过去，顺延到明天，避免"设了不触发"
            target += timedelta(days=1)
        return target

    if parsed <= now:
        raise ValueError(u"目标时间已过，请填写一个未来的时间")

    return parsed


def format_remaining(seconds):
    """把剩余秒数格式化为 HH:MM:SS"""
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return u"%02d:%02d:%02d" % (hours, minutes, secs)


class LaunchScheduler(object):
    """定时启动调度器：武装/取消、倒计时、到点判定"""

    def __init__(self):
        self._target = None

    @property
    def target(self):
        """当前目标时刻；未武装时为 None"""
        return self._target

    @property
    def is_armed(self):
        """是否已设定定时任务"""
        return self._target is not None

    def arm(self, target):
        """武装定时任务，target 为 datetime"""
        if not isinstance(target, datetime):
            raise TypeError(u"target 必须是 datetime 对象")
        self._target = target

    def cancel(self):
        """取消定时任务"""
        self._target = None

    def remaining(self, now=None):
        """剩余秒数（float）；未武装时返回 None"""
        if self._target is None:
            return None
        now = now if now is not None else datetime.now()
        return (self._target - now).total_seconds()

    def should_fire(self, now=None):
        """是否已到触发时刻"""
        remaining = self.remaining(now)
        return remaining is not None and remaining <= 0
