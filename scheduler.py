# -*- coding: utf-8 -*-
"""
时间解析模块

职责：
1. 解析 UI 中填写的时间字符串（如 "08:00:01"）；
2. 计算目标时刻（只填时分秒时默认今天，今天已过则顺延到明天）；
3. 把剩余秒数格式化为 HH:MM:SS 供界面倒计时显示。

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


def next_slot(now=None):
    """
    返回下一个场次整点（今天剩余场次优先，否则明天第一场）。

    用于运行期重校后重新武装：旧目标可能早已过去，不能再用它。
    """
    from config import MORNING_SLOTS, EVENING_SLOTS
    now = now if now is not None else datetime.now()
    slots = list(MORNING_SLOTS) + list(EVENING_SLOTS)
    candidates = []
    for text in slots:
        hour_text, minute_text = text.split(u":")
        candidate = now.replace(
            hour=int(hour_text), minute=int(minute_text),
            second=0, microsecond=0,
        )
        if candidate > now:
            candidates.append(candidate)
        else:
            candidates.append(candidate + timedelta(days=1))
    return min(candidates) if candidates else now + timedelta(minutes=5)


def next_two_minute_mark(now=None):
    """
    计算"下一个两分钟整点"（分钟为偶数、秒和微秒为 0 的时刻）。
    用于"点按钮自动设置时间"：不再手动填写。

    例（实拍口径）：
      14:04:05 → 14:06:00
      14:04:00 → 14:06:00（整点当下也取下一个）
      14:03:30 → 14:04:00
      14:05:59 → 14:06:00
      23:59:30 → 次日 00:00:00
    """
    now = now if now is not None else datetime.now()
    minute = now.minute
    if now.second > 0 or now.microsecond > 0:
        minute += 1
    minute += minute % 2  # 奇数分进到偶数分
    target = now.replace(hour=now.hour, minute=0, second=0, microsecond=0) \
        + timedelta(minutes=minute)
    if target <= now:
        target += timedelta(minutes=2)
    return target


