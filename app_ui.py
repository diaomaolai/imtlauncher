# -*- coding: utf-8 -*-
"""
界面模块：i茅台启动器主界面（竖屏）
"""

from kivy.graphics import Color, Rectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from config import APP_TITLE, TARGET_PACKAGE


class MainScreen(BoxLayout):
    """主界面：状态提示 + 大号启动按钮 + 包名设置"""

    def __init__(self, launcher, **kwargs):
        super(MainScreen, self).__init__(**kwargs)
        self.launcher = launcher
        self.orientation = "vertical"
        self.padding = [36, 56, 36, 36]
        self.spacing = 20

        # 浅色背景
        with self.canvas.before:
            Color(0.97, 0.96, 0.92, 1)
            self._background = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._redraw_background, size=self._redraw_background)

        # 标题
        self.title_label = Label(
            text=APP_TITLE,
            font_size="28sp",
            bold=True,
            color=(0.35, 0.12, 0.05, 1),
            size_hint=(1, 0.10),
        )
        self.add_widget(self.title_label)

        # 状态文字
        self.status_label = Label(
            text=u"正在检测……",
            font_size="17sp",
            color=(0.25, 0.25, 0.25, 1),
            halign="center",
            valign="middle",
            size_hint=(1, 0.18),
        )
        self.status_label.bind(
            width=lambda instance, value: setattr(
                instance, "text_size", (value, None)
            )
        )
        self.add_widget(self.status_label)

        # 弹簧
        self.add_widget(Widget(size_hint=(1, 0.06)))

        # 启动按钮
        self.launch_btn = Button(
            text=u"启动 i茅台",
            font_size="24sp",
            bold=True,
            color=(1, 1, 1, 1),
            background_color=(0.72, 0.16, 0.10, 1),
            size_hint=(1, 0.20),
        )
        self.add_widget(self.launch_btn)

        # 弹簧
        self.add_widget(Widget(size_hint=(1, 0.14)))

        # 包名设置（一般无需修改，留作兼容未来版本）
        self.pkg_caption = Label(
            text=u"目标包名（一般无需修改）",
            font_size="13sp",
            color=(0.45, 0.45, 0.45, 1),
            size_hint=(1, 0.05),
        )
        self.add_widget(self.pkg_caption)

        self.package_input = TextInput(
            text=TARGET_PACKAGE,
            font_size="15sp",
            multiline=False,
            size_hint=(1, 0.07),
        )
        self.add_widget(self.package_input)

    def _redraw_background(self, *args):
        self._background.pos = self.pos
        self._background.size = self.size

    def get_package(self):
        """获取输入框中的包名（已去空白）"""
        return self.package_input.text.strip()

    def set_package(self, package_name):
        """设置包名"""
        self.package_input.text = package_name

    def set_status(self, text):
        """更新状态提示"""
        self.status_label.text = text
