# -*- coding: utf-8 -*-
"""
i茅台启动器 - 主入口

说明：Buildozer 打包要求入口文件名必须为 main.py（相当于你以往
工程里的 APP_RUN.py），各功能模块独立拆分、由本文件统一导入。

当前功能：
定时自动申购——在界面填写时间（如 08:00:01），到点启动 i茅台 →
进入 i购 → 上滑查找目标商品 → 进详情读取开售时间（如 08:05）→
返回列表，在开售时间 +1 秒（08:05:01）再次点击商品并点购买。
电脑端运行时控制台会打印 "正在启动I茅台"。
"""

from kivy.app import App
from kivy.clock import Clock

import threading
import time
from datetime import datetime

from config import APP_TITLE
from font_setup import register_cjk_font
from android_launcher import AndroidLauncher
from a11y_bridge import A11yBridge
from purchase_flow import PurchaseFlow
from scheduler import LaunchScheduler, parse_target_time, format_remaining
from app_ui import MainScreen

# 主循环间隔（秒）。越小触发越准
TICK_INTERVAL = 0.3


class FlowWorker(threading.Thread):
    """
    自动申购流程工作线程。

    关键：启动 i茅台后我们的 Activity 会进入后台，Kivy/SDL 主循环
    （Clock）被系统暂停；若状态机跑在 Clock 里，到点后的点击、滑动
    全部不会执行。普通 Python 线程不受 Activity 前后台影响，因此
    由本线程以固定间隔推进状态机。
    """

    def __init__(self, purchase_flow):
        super(FlowWorker, self).__init__(daemon=True)
        self.purchase_flow = purchase_flow
        self.stop_event = threading.Event()

    def stop(self):
        """请求线程退出（取消定时时调用）"""
        self.stop_event.set()

    def run(self):
        last = time.monotonic()
        while not self.stop_event.is_set() \
                and not self.purchase_flow.is_done:
            current = time.monotonic()
            dt = current - last
            last = current
            now_dt = datetime.now()
            try:
                self.purchase_flow.update(dt, now_dt)
            except Exception as exc:
                # 单次异常不杀线程，打印后下一轮继续
                print(u"流程推进异常: %s" % exc)

            # pyjnius 在本线程上附着的 JNI 环境主动释放，
            # 下一轮调用会重新附着，避免持有过期环境。
            try:
                from jnius import detach
                detach()
            except Exception:
                pass

            self.stop_event.wait(TICK_INTERVAL)


class IMtLauncherApp(App):
    """Kivy 应用主类"""

    def build(self):
        self.title = APP_TITLE

        # 功能模块
        self.launcher = AndroidLauncher()
        self.bridge = A11yBridge()
        self.purchase_flow = PurchaseFlow(self.launcher, self.bridge)
        self.scheduler = LaunchScheduler()
        self.flow_worker = None

        # 界面
        self.screen = MainScreen()
        self.screen.schedule_btn.bind(on_press=self._on_schedule_pressed)

        # 启动后打印一次屏幕参数，确认自适应取到的尺寸
        Clock.schedule_once(self._print_screen_metrics, 0.5)

        # 界面刷新循环（只更新界面；流程推进在工作线程）
        Clock.schedule_interval(self._tick, TICK_INTERVAL)
        return self.screen

    def _print_screen_metrics(self, *args):
        """打印屏幕物理尺寸与像素密度（Kivy 侧）"""
        from kivy.core.window import Window
        from kivy.metrics import Metrics
        print(
            u"屏幕尺寸: %dx%d 像素密度: %.2f"
            % (int(Window.width), int(Window.height), Metrics.density)
        )

    # ---------------- 定时武装 ----------------
    def _on_schedule_pressed(self, instance):
        """设置定时 / 取消定时 按钮回调"""
        if self.scheduler.is_armed:
            self._disarm(u"已取消定时")
            return

        try:
            target = parse_target_time(self.screen.get_time_text())
        except ValueError as exc:
            self.screen.set_status(str(exc))
            return

        self.scheduler.arm(target)
        self.purchase_flow.reset(target)

        # 启动后台工作线程推进流程（Activity 进后台也不中断）
        self.flow_worker = FlowWorker(self.purchase_flow)
        self.flow_worker.start()

        self.screen.set_schedule_button_armed(True)
        self.screen.set_status(
            u"已设定：%s 启动 i茅台"
            % target.strftime(u"%Y-%m-%d %H:%M:%S")
        )

    def _disarm(self, status_text=None):
        """取消定时并恢复界面"""
        if self.flow_worker is not None:
            self.flow_worker.stop()
            self.flow_worker = None
        self.scheduler.cancel()
        self.screen.set_schedule_button_armed(False)
        self.screen.set_countdown(u"倒计时：未设定")
        if status_text:
            self.screen.set_status(status_text)

    # ---------------- 界面刷新 ----------------
    def _tick(self, dt):
        if not self.scheduler.is_armed:
            return

        now_dt = datetime.now()

        # 倒计时跟随流程目标：启动时刻；侦察到开售时间后切换为二次点击时刻
        target_dt = self.purchase_flow.display_target
        if target_dt is not None:
            remaining = (target_dt - now_dt).total_seconds()
            self.screen.set_countdown(
                u"倒计时：%s" % format_remaining(remaining)
            )

        # 状态文字由工作线程更新，这里只负责显示
        self.screen.set_status(self.purchase_flow.status)

        if self.purchase_flow.is_done:
            result = self.purchase_flow.status
            self._disarm(result)


def main():
    register_cjk_font()
    IMtLauncherApp().run()


if __name__ == "__main__":
    main()
