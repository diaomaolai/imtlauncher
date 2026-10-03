# -*- coding: utf-8 -*-
"""
i茅台助手 - 主入口（重构版 v1.0.0）

说明：Buildozer 打包要求入口文件名必须为 main.py，各功能模块独立
拆分、由本文件统一导入。

功能（极简）：
界面填写时间（如 08:00:01）→ 到点识别商品文字「飞天%vol」→
点击文字并记录位置 → 读详情页右下角：立即抢购则点击；开售时间
则返回列表，在开售时间 +1 秒二次点击记录的位置。
"""

from kivy.app import App
from kivy.clock import Clock

import threading
import time
from datetime import datetime

from config import APP_TITLE, TICK_INTERVAL
from font_setup import register_cjk_font
from a11y_bridge import A11yBridge
from flow_core import FlowCore
from scheduler import parse_target_time, format_remaining
from app_ui import MainScreen


class FlowWorker(threading.Thread):
    """
    流程工作线程。

    关键：切换到 i茅台后我们的 Activity 进入后台，Kivy/SDL 主循环
    （Clock）被系统暂停；普通 Python 线程不受前后台影响，因此由本
    线程以固定间隔推进状态机。
    """

    def __init__(self, flow):
        super(FlowWorker, self).__init__(daemon=True)
        self.flow = flow
        self.stop_event = threading.Event()

    def stop(self):
        """请求线程退出（取消定时时调用）"""
        self.stop_event.set()

    def run(self):
        last = time.monotonic()
        while not self.stop_event.is_set() and not self.flow.is_done:
            current = time.monotonic()
            dt = current - last
            last = current
            now_dt = datetime.now()
            try:
                self.flow.update(dt, now_dt)
            except Exception as exc:
                # 单次异常不杀线程，打印后下一轮继续
                print(u"流程推进异常: %s" % exc)

            # 主动释放本线程上附着的 JNI 环境
            try:
                from jnius import detach
                detach()
            except Exception:
                pass

            self.stop_event.wait(TICK_INTERVAL)


class IMtAssistantApp(App):
    """Kivy 应用主类"""

    def build(self):
        self.title = APP_TITLE

        # 功能模块
        self.bridge = A11yBridge()
        self.flow = FlowCore(self.bridge)
        self.flow_worker = None

        # 界面
        self.screen = MainScreen()
        self.screen.schedule_btn.bind(on_press=self._on_schedule_pressed)

        # 界面刷新循环（只更新界面；流程推进在工作线程）
        Clock.schedule_interval(self._tick, TICK_INTERVAL)
        return self.screen

    # ---------------- 定时武装 ----------------
    def _on_schedule_pressed(self, instance):
        """设置定时 / 取消定时 按钮回调"""
        if self.flow_worker is not None and not self.flow.is_done:
            self._disarm(u"已取消定时")
            return

        try:
            target = parse_target_time(self.screen.get_time_text())
        except ValueError as exc:
            self.screen.set_status(str(exc))
            return

        self.flow.reset(target)

        # 启动后台工作线程推进流程（Activity 进后台也不中断）
        self.flow_worker = FlowWorker(self.flow)
        self.flow_worker.start()

        self.screen.set_schedule_button_armed(True)
        self.screen.set_status(
            u"已设定：%s" % target.strftime(u"%Y-%m-%d %H:%M:%S")
        )

    def _disarm(self, status_text=None):
        """取消定时并恢复界面"""
        if self.flow_worker is not None:
            self.flow_worker.stop()
            self.flow_worker = None
        self.screen.set_schedule_button_armed(False)
        self.screen.set_countdown(u"倒计时：未设定")
        if status_text:
            self.screen.set_status(status_text)

    # ---------------- 界面刷新 ----------------
    def _tick(self, dt):
        if self.flow.is_done:
            self.screen.set_status(self.flow.status)
            self._disarm(self.flow.status)
            return
        if self.flow_worker is None:
            return

        now_dt = datetime.now()
        target_dt = self.flow.display_target
        if target_dt is not None:
            remaining = (target_dt - now_dt).total_seconds()
            self.screen.set_countdown(
                u"倒计时：%s" % format_remaining(remaining)
            )
        self.screen.set_status(self.flow.status)


def main():
    register_cjk_font()
    IMtAssistantApp().run()


if __name__ == "__main__":
    main()
