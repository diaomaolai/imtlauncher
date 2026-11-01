# -*- coding: utf-8 -*-
"""
高保真复现：真机点击「立即抢购」后，安全验证弹窗在不同延迟下出现，
观察 RAPID 实际点击次数与最终状态（验证弹窗下立即抢购节点仍在树中）。
"""
from datetime import datetime
from flow_core import FlowCore, RAPID_BUY, WAIT_VERIFY

BUY = u"立即抢购"


class RealPhoneBridge(object):
    def __init__(self, verify_delay_s):
        # 详情页常驻文字（含数量、年份、立即抢购）
        self.live_texts = {u"数量", u"2026", BUY}
        self.verify_delay = verify_delay_s   # 点击后多久弹验证；None=不弹
        self.elapsed = 0.0
        self.verify_on = False
        self.buy_clicks = 0
        self._clicked_at = None

    def is_connected(self):
        return True

    def node_center(self, keywords):
        return None

    def _current_texts(self):
        t = set(self.live_texts)
        if self.verify_on:
            # 验证弹窗特征词；立即抢购节点仍在树中（弹窗只是覆盖）
            t |= {u"填字", u"换一换"}
        return t

    def text_exists(self, text):
        if text in (u"已售罄", u"已售磬"):
            return False
        return text in self._current_texts()

    def any_text_exists(self, texts):
        cur = self._current_texts()
        return any(x in cur for x in texts)

    def click_text(self, text):
        if text == BUY and BUY in self.live_texts:
            self.buy_clicks += 1
            if self.verify_delay is not None and self._clicked_at is None:
                self._clicked_at = self.elapsed
            return True
        return False

    def find_regex_in_px_region(self, regex, region):
        return []

    def text_exists_in_px_region(self, text, region):
        return False

    def click_text_in_px_region(self, text, region):
        return False

    def click_node_by_parts(self, keywords):
        return False

    def tap_px(self, x, y, jitter=6):
        return True

    def back(self):
        return True

    def advance(self, dt):
        self.elapsed += dt
        if self.verify_delay is not None and self._clicked_at is not None:
            if self.elapsed - self._clicked_at >= self.verify_delay:
                self.verify_on = True


def run_case(name, verify_delay, seconds=4.0, dt=0.01):
    br = RealPhoneBridge(verify_delay)
    logs = []
    flow = FlowCore(br, type("L", (), {"log": lambda s, m: logs.append(m)})())
    flow.reset(datetime(2026, 11, 2, 20, 0, 0))
    flow.state = RAPID_BUY
    flow._rapid_wait_left = 0.0
    now = datetime(2026, 11, 2, 20, 0, 0)
    steps = int(round(seconds / dt))
    for _ in range(steps):
        flow.update(dt, now)
        br.advance(dt)
    print(u"[%s] 验证弹窗延迟=%s 实际点击=%d 次，最终状态=%s"
          % (name,
             (u"%s秒" % verify_delay) if verify_delay is not None else u"不弹",
             br.buy_clicks, flow.state))


if __name__ == u"__main__":
    run_case(u"无验证", None)
    run_case(u"验证立即弹", 0.0)
    run_case(u"验证0.1秒弹", 0.1)
    run_case(u"验证0.3秒弹", 0.3)
    run_case(u"验证0.6秒弹", 0.6)
    run_case(u"验证1.0秒弹", 1.0)
