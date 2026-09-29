# -*- coding: utf-8 -*-
"""
i茅台启动器 - 主入口

说明：Buildozer 打包要求入口文件名必须为 main.py（相当于你以往
工程里的 APP_RUN.py），各功能模块独立拆分、由本文件统一导入。

当前功能：
1. 一键启动手机本地已安装的 i茅台 APP；
2. 定时启动：在界面填写时间（如 08:00:01），到点自动启动 i茅台；
   电脑端运行时到点在控制台打印 "正在启动I茅台"。
"""

from kivy.app import App
from kivy.clock import Clock

from config import APP_TITLE, TARGET_APP_NAME
from font_setup import register_cjk_font
from android_launcher import AndroidLauncher
from scheduler import LaunchScheduler, parse_target_time, format_remaining
from app_ui import MainScreen

# 倒计时刷新间隔（秒）。越小触发越准时
TICK_INTERVAL = 0.3


class IMtLauncherApp(App):
    """Kivy 应用主类"""

    def build(self):
        self.title = APP_TITLE

        # 功能模块
        self.launcher = AndroidLauncher()
        self.scheduler = LaunchScheduler()

        # 界面
        self.screen = MainScreen(self.launcher)
        self.screen.launch_btn.bind(on_press=self._on_launch_pressed)
        self.screen.schedule_btn.bind(on_press=self._on_schedule_pressed)

        # 启动后再做检测，避免阻塞界面渲染
        Clock.schedule_once(self._refresh_status, 0.3)

        # 定时刷新倒计时 / 到点触发
        Clock.schedule_interval(self._tick, TICK_INTERVAL)
        return self.screen

    def _refresh_status(self, *args):
        """检测 i茅台 安装状态并更新界面"""
        if not self.launcher.is_android:
            self.screen.set_status(
                u"电脑调试模式：可测试定时，到点控制台打印启动信息"
            )
            return

        package = self.screen.get_package()
        if self.launcher.is_installed(package):
            self.screen.set_status(
                u"已检测到 %s，可立即启动或设置定时" % TARGET_APP_NAME
            )
            return

        # 兜底：扫描已安装应用中的茅台系 APP
        found = self.launcher.scan_moutai_packages()
        if found:
            pkg, name = found[0]
            self.screen.set_package(pkg)
            self.screen.set_status(u"已找到：%s（%s）" % (name, pkg))
        else:
            self.screen.set_status(u"未检测到 i茅台，请先安装后再使用")

    # ---------------- 定时相关 ----------------
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
        self.screen.set_schedule_button_armed(True)
        self.screen.set_status(
            u"已设定定时启动：%s"
            % target.strftime(u"%Y-%m-%d %H:%M:%S")
        )

    def _disarm(self, status_text=None):
        """取消定时并恢复界面"""
        self.scheduler.cancel()
        self.screen.set_schedule_button_armed(False)
        self.screen.set_countdown(u"倒计时：未设定")
        if status_text:
            self.screen.set_status(status_text)

    def _tick(self, dt):
        """定时刷新：更新倒计时，到点则触发启动"""
        if not self.scheduler.is_armed:
            return

        remaining = self.scheduler.remaining()
        self.screen.set_countdown(
            u"倒计时：%s" % format_remaining(remaining)
        )

        if self.scheduler.should_fire():
            self._fire_scheduled()

    def _fire_scheduled(self):
        """到点触发：电脑端打印，安卓端启动 i茅台"""
        package = self.screen.get_package()

        # 先取消定时，避免重复触发
        self._disarm()

        # 电脑端 / 安卓端统一打印（电脑端主要看这一行）
        print("正在启动I茅台")

        if not self.launcher.is_android:
            self.screen.set_status(
                u"电脑端：时间已到，控制台已打印 \"正在启动I茅台\""
            )
            return

        ok, message = self.launcher.launch(package)
        self.screen.set_status(message)
        self.launcher.toast(message)

    # ---------------- 手动启动 ----------------
    def _on_launch_pressed(self, instance):
        """立即启动按钮回调"""
        package = self.screen.get_package()
        if not package:
            self.screen.set_status(u"包名不能为空")
            return

        if not self.launcher.is_android:
            print("正在启动I茅台")
            self.screen.set_status(
                u"电脑调试模式：控制台已打印 \"正在启动I茅台\""
            )
            return

        ok, message = self.launcher.launch(package)
        if not ok:
            self.screen.set_status(message)
        self.launcher.toast(message)


def main():
    register_cjk_font()
    IMtLauncherApp().run()


if __name__ == "__main__":
    main()
