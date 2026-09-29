# -*- coding: utf-8 -*-
"""
i茅台启动器 - 主入口

说明：Buildozer 打包要求入口文件名必须为 main.py（相当于你以往
工程里的 APP_RUN.py），各功能模块独立拆分、由本文件统一导入。

当前功能：一键启动手机本地已安装的 i茅台 APP。
"""

from kivy.app import App
from kivy.clock import Clock

from config import APP_TITLE, TARGET_APP_NAME
from font_setup import register_cjk_font
from android_launcher import AndroidLauncher
from app_ui import MainScreen


class IMtLauncherApp(App):
    """Kivy 应用主类"""

    def build(self):
        self.title = APP_TITLE

        # 功能模块
        self.launcher = AndroidLauncher()

        # 界面
        self.screen = MainScreen(self.launcher)
        self.screen.launch_btn.bind(on_press=self._on_launch_pressed)

        # 启动后再做检测，避免阻塞界面渲染
        Clock.schedule_once(self._refresh_status, 0.3)
        return self.screen

    def _refresh_status(self, *args):
        """检测 i茅台 安装状态并更新界面"""
        if not self.launcher.is_android:
            self.screen.set_status(
                u"电脑调试模式：界面可预览，启动功能请在安卓手机上使用"
            )
            return

        package = self.screen.get_package()
        if self.launcher.is_installed(package):
            self.screen.set_status(
                u"已检测到 %s，点击下方按钮启动" % TARGET_APP_NAME
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

    def _on_launch_pressed(self, instance):
        """启动按钮回调"""
        package = self.screen.get_package()
        if not package:
            self.screen.set_status(u"包名不能为空")
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
