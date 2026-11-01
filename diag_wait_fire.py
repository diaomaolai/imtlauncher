# -*- coding: utf-8 -*-
"""
诊断（v1.3.3 目标逻辑）：后台等待 -> 到点自行拉起 -> 任意页面接入 ->
读开售时间（未来 WAIT / 已过顺延）-> 到点节点点击进 RAPID。

用可控虚拟时钟驱动 FlowCore（不依赖真实时间），验证：
  场景1 同天提前武装：IDLE 不拉起，到 target-15 才拉起，WAIT 到点 RAPID；
  场景2 跨天晚上备次日：IDLE 长等到次日拉起，不再 SCOUT 死循环；
  场景3 任意页面接入：拉起时已在列表，从列表直接进详情；
  场景4 过点顺延：进详情时按钮时刻已过，自动 +1 天 WAIT。

运行：
    D:\\python\\python.exe diag_wait_fire.py
"""

import re
from datetime import datetime, timedelta

from config import (
    QTY_PLUS_CENTER_PX,
    SALE_TIME_REGEX,
    YEAR_TARGET_TEXT,
    MANUAL_LAUNCH_LEAD_SECONDS,
)
from flow_core import FlowCore, RAPID_BUY, WAIT_TIME, DONE


class ListLogger(object):
    def __init__(self):
        self.lines = []

    def log(self, message):
        self.lines.append(message)


class MockBridge(object):
    """页面状态机：outside -> home -> igou -> list -> detail。

    outside 表示不在 i茅台（启动器/桌面），由 on_launch_app 回调拉起。
    按钮文字随虚拟时间变化；always_future 始终显示投放时间。
    """

    CENTERS = {
        u"igou": (330, 2080),
        u"jingdian": (275, 1010),
        u"product": (540, 1250),
        u"year": (292, 1540),
        u"qty": (909, 1962),
        u"action": (840, 2162),
        u"plus": QTY_PLUS_CENTER_PX,
    }

    def __init__(self, slot_hour=9, start_qty=2, start_page=u"outside",
                 always_future=False):
        self.page = start_page
        self.slot_hour = slot_hour
        self.qty = start_qty
        self.taps = []
        self.backs = 0
        self.buy_clicks = 0
        self.launch_count = 0
        self._now = None
        self.always_future = always_future

    def set_now(self, now):
        self._now = now

    def _slot_target(self):
        return self._now.replace(
            hour=self.slot_hour, minute=0, second=0, microsecond=0
        )

    def _button_text(self):
        if self.always_future:
            return u"%02d:00投放" % self.slot_hour
        if self._now < self._slot_target():
            return u"%02d:00投放" % self.slot_hour
        return u"立即抢购"

    # on_launch_app 回调：幂等拉起，outside -> home；已在 i茅台 保持当前页
    def launch(self):
        self.launch_count += 1
        if self.page == u"outside":
            self.page = u"home"
        return True

    def _elements(self):
        if self.page == u"outside":
            return []
        if self.page == u"home":
            return [(u"i购", self.CENTERS[u"igou"])]
        if self.page == u"igou":
            return [(u"经典", self.CENTERS[u"jingdian"])]
        if self.page == u"list":
            return [
                (u"飞天53%vol 500ml贵州茅台酒（带杯）",
                 self.CENTERS[u"product"]),
                (u"经典", self.CENTERS[u"jingdian"]),
            ]
        return [
            (u"数量", (60, 1962)),
            (YEAR_TARGET_TEXT, self.CENTERS[u"year"]),
            (str(self.qty), self.CENTERS[u"qty"]),
            (self._button_text(), self.CENTERS[u"action"]),
        ]

    @staticmethod
    def _in_region(center, region):
        return region[0] <= center[0] <= region[2] \
            and region[1] <= center[1] <= region[3]

    def _find_text(self, text):
        for t, c in self._elements():
            if text in t:
                return c
        return None

    def is_connected(self):
        return True

    def node_center(self, keywords):
        for t, c in self._elements():
            if all(k in t for k in keywords):
                return c
        return None

    def text_exists(self, text):
        return self._find_text(text) is not None

    def text_exists_in_px_region(self, text, region):
        c = self._find_text(text)
        return c is not None and self._in_region(c, region)

    def click_text_in_px_region(self, text, region):
        if self.text_exists_in_px_region(text, region):
            self._on_click(text)
            return True
        return False

    def click_text(self, text):
        c = self._find_text(text)
        if c is not None:
            self.buy_clicks += 1
            self._on_click(text)
            return True
        return False

    def find_regex_in_px_region(self, regex, region):
        out = []
        for t, c in self._elements():
            if not self._in_region(c, region):
                continue
            m = re.compile(regex).search(t)
            if m:
                out.append(m.group(0))
        return out

    def click_node_by_parts(self, keywords):
        c = self.node_center(keywords)
        if c is not None:
            self.page = u"detail"
            return True
        return False

    def tap_px(self, x, y, jitter=6):
        self.taps.append((x, y))
        pc = self.CENTERS[u"product"]
        if self.page == u"list" and abs(x - pc[0]) < 30 \
                and abs(y - pc[1]) < 30:
            self.page = u"detail"

    def back(self):
        self.backs += 1
        if self.page == u"detail":
            self.page = u"list"

    def _on_click(self, text):
        if text == u"i购":
            self.page = u"igou"
        elif text == u"经典":
            self.page = u"list"


def drive(flow, bridge, start, max_seconds=200000, verbose=True):
    """虚拟时钟驱动，返回状态轨迹与最终状态。"""
    now = start
    last_state = None
    trace = []
    steps = 0
    while steps < max_seconds:
        bridge.set_now(now)
        if flow.state in (WAIT_TIME,):
            target = flow.session_target
            if target is not None and (target - now).total_seconds() > 20:
                step = 30.0
            else:
                step = 0.5
        elif flow.state == u"IDLE":
            target = flow.launch_target
            if target is not None and (target - now).total_seconds() > 20:
                step = 30.0
            else:
                step = 0.5
        else:
            step = 0.1

        flow.update(step, now)

        if flow.state != last_state:
            disp = flow.display_target
            remaining = None
            if disp is not None:
                remaining = (disp - now).total_seconds()
            trace.append((
                now.strftime(u"%m-%d %H:%M:%S"),
                flow.state,
                None if remaining is None else int(remaining),
            ))
            if verbose:
                print(u"  [%s] 状态=%-18s 倒计时remaining=%s"
                      % (now.strftime(u"%H:%M:%S"), flow.state,
                         u"--" if remaining is None else int(remaining)))
            last_state = flow.state

        if flow.state == RAPID_BUY or flow.state == DONE:
            break
        now += timedelta(seconds=step)
        steps += 1
    return trace, flow.state


def scenario(name, target, arm_dt, start_page=u"outside",
             always_future=False, expect_rapid=True):
    print(u"=" * 64)
    print(u"场景：%s" % name)
    logger = ListLogger()
    bridge = MockBridge(
        start_page=start_page, always_future=always_future
    )
    flow = FlowCore(bridge, logger)
    flow.year_target = YEAR_TARGET_TEXT
    # 模拟手动武装：reset(target)，launch_target 自动 = target-提前量
    bridge.set_now(arm_dt)
    flow.reset(target)
    flow.on_launch_app = bridge.launch

    # 武装瞬间不应已拉起（outside 场景）
    if start_page == u"outside":
        assert bridge.page == u"outside", u"武装后立即拉起，违反后台等待"
        assert bridge.launch_count == 0, u"武装后不应调用 launch"

    trace, final = drive(flow, bridge, arm_dt)
    print(u"  最终状态：%s" % final)
    print(u"  launch 次数：%d，back：%d，taps：%d，购买点击：%d"
          % (bridge.launch_count, bridge.backs, len(bridge.taps),
             bridge.buy_clicks))
    ok = (final == RAPID_BUY) if expect_rapid else True
    print(u"  结果：%s" % (u"PASS" if ok else u"FAIL"))
    return ok, flow, bridge, trace


if __name__ == u"__main__":
    day = datetime(2026, 11, 2)
    results = []

    # 场景1：同天 08:30 武装，target 09:00，launch_target=08:45
    ok1, _, _, _ = scenario(
        u"同天提前武装（后台等待，08:45 拉起）",
        day.replace(hour=9), day.replace(hour=8, minute=30),
    )
    results.append((u"场景1", ok1))

    # 场景2：当天 22:00 武装，target 次日 09:00；按钮随虚拟时间在
    # 整点后变立即抢购（真实行为），验证跨天等待且不再 SCOUT 死循环
    ok2, _, _, _ = scenario(
        u"跨天晚上备次日（长等到次日 08:45 拉起，不死循环）",
        day.replace(hour=9) + timedelta(days=1),
        day.replace(hour=22),
    )
    results.append((u"场景2", ok2))

    # 场景3：拉起时已在列表（任意页面接入），target 09:00
    ok3, _, _, _ = scenario(
        u"任意页面接入（已在列表，直接进详情）",
        day.replace(hour=9), day.replace(hour=8, minute=45),
        start_page=u"list",
    )
    results.append((u"场景3", ok3))

    # 场景4：进详情时已过点（09:10），验证 +1 天顺延。
    # always_future 让按钮在 09:10 仍显示「09:00投放」（下一场），
    # 手动推进有限拍直到进入 WAIT，再断言，不跑到次日。
    print(u"\n" + u"=" * 64)
    print(u"场景：过点顺延（09:10 已在详情，按钮 09:00，应顺延次日）")
    lg = ListLogger()
    br = MockBridge(start_page=u"detail", always_future=True)
    fl = FlowCore(br, lg)
    fl.year_target = YEAR_TARGET_TEXT
    arm4 = day.replace(hour=9, minute=10)
    cur = arm4
    br.set_now(cur)
    fl.reset(day.replace(hour=9), launch_target=arm4)
    fl.on_launch_app = br.launch
    for _i in range(200):
        br.set_now(cur)
        fl.update(0.1, cur)
        if fl.state == WAIT_TIME:
            break
        cur += timedelta(seconds=0.1)
    expect_target = day.replace(hour=9) + timedelta(days=1)
    ok4 = fl.state == WAIT_TIME and fl.session_target == expect_target
    if fl.session_target is not None:
        print(u"  session_target=%s，状态=%s"
              % (fl.session_target.strftime(u"%Y-%m-%d %H:%M"), fl.state))
    else:
        print(u"  session_target 未设置，状态=%s" % fl.state)
    print(u"  结果：%s" % (u"PASS" if ok4 else u"FAIL"))
    results.append((u"场景4", ok4))

    print(u"\n" + u"=" * 64)
    print(u"汇总：")
    for n, ok in results:
        print(u"  %s：%s" % (n, u"PASS" if ok else u"FAIL"))
    print(u"全部通过：%s" % all(ok for _, ok in results))
