# -*- coding: utf-8 -*-
"""
验证修复后的 SlotMonitor 行为：
1. 流程在跑（running=True，模拟手动定时 IDLE 等待）：仍拉起一次
   i茅台 保证前台，但不重复武装；
2. 无流程（running=False）：拉起 + 武装；
3. 可补偿：旧 3 秒窗口之外、整点之前的时间点仍能触发；
4. 整点宽限：整点后 SLOT_GRACE_SECONDS 内仍可触发；
5. 超过宽限：放弃，不触发。
"""

from datetime import datetime, timedelta

import slot_monitor


class FakeLogger(object):
    def __init__(self):
        self.lines = []

    def log(self, line):
        self.lines.append(line)


def run_once(now, running):
    logger = FakeLogger()
    launch_calls = []
    auto_calls = []

    def fake_launch(_logger=None):
        launch_calls.append(1)
        return True

    original = slot_monitor.launch_moutai
    slot_monitor.launch_moutai = fake_launch
    try:
        monitor = slot_monitor.SlotMonitor(
            is_running_fn=lambda: running,
            autostart_fn=lambda target: auto_calls.append(target),
            logger=logger,
        )
        monitor.set_enabled(True)
        monitor.check_once(now)
    finally:
        slot_monitor.launch_moutai = original

    return len(launch_calls), len(auto_calls), logger.lines


def main():
    # 1) running=True：保证前台（launch 1），不重复武装（auto 0）
    n_launch, n_auto, _ = run_once(
        datetime(2026, 11, 1, 8, 57, 1), running=True
    )
    print("running=True  08:57:01 -> launch=%d autostart=%d"
          % (n_launch, n_auto))
    assert n_launch == 1 and n_auto == 0

    # 2) running=False：拉起 + 武装
    n_launch, n_auto, _ = run_once(
        datetime(2026, 11, 1, 8, 57, 1), running=False
    )
    print("running=False 08:57:01 -> launch=%d autostart=%d"
          % (n_launch, n_auto))
    assert n_launch == 1 and n_auto == 1

    # 3) 可补偿：08:57:10 已超旧 3 秒窗口，但整点前，仍触发
    n_launch, n_auto, _ = run_once(
        datetime(2026, 11, 1, 8, 57, 10), running=False
    )
    print("补偿         08:57:10 -> launch=%d autostart=%d"
          % (n_launch, n_auto))
    assert n_launch == 1 and n_auto == 1

    # 4) 整点宽限：09:00:03 在 5 秒宽限内，仍触发
    n_launch, n_auto, _ = run_once(
        datetime(2026, 11, 1, 9, 0, 3), running=False
    )
    print("宽限         09:00:03 -> launch=%d autostart=%d"
          % (n_launch, n_auto))
    assert n_launch == 1 and n_auto == 1

    # 5) 超过宽限：09:00:10 放弃，不触发
    n_launch, n_auto, _ = run_once(
        datetime(2026, 11, 1, 9, 0, 10), running=False
    )
    print("超宽限       09:00:10 -> launch=%d autostart=%d"
          % (n_launch, n_auto))
    assert n_launch == 0 and n_auto == 0

    # 6) 未到提前时刻：08:56:59 不触发
    n_launch, n_auto, _ = run_once(
        datetime(2026, 11, 1, 8, 56, 59), running=False
    )
    print("未到时刻     08:56:59 -> launch=%d autostart=%d"
          % (n_launch, n_auto))
    assert n_launch == 0 and n_auto == 0

    print("\n全部断言通过：i茅台 被可靠拉起，触发可补偿，宽限正确。")


if __name__ == "__main__":
    main()
