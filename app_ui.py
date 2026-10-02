# -*- coding: utf-8 -*-
"""
界面模块：i茅台启动器主界面（竖屏）

包含：
- 状态提示
- 定时时间输入（HH:MM:SS）+ 设置定时按钮 + 倒计时
"""

from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from config import APP_TITLE, DEFAULT_TIME_TEXT


class MainScreen(BoxLayout):
    """主界面：状态提示 + 定时设置 + 倒计时"""

    def __init__(self, **kwargs):
        super(MainScreen, self).__init__(**kwargs)
        self.orientation = "vertical"
        # padding/spacing 用 dp：随屏幕密度自动缩放，不同分辨率观感一致
        self.padding = [dp(36), dp(64), dp(36), dp(48)]
        self.spacing = dp(16)

        # 浅色背景
        with self.canvas.before:
            Color(0.97, 0.96, 0.92, 1)
            self._background = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._redraw_background, size=self._redraw_background)

        # 标题
        self.title_label = Label(
            text=APP_TITLE,
            font_size="30sp",
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
            size_hint=(1, 0.16),
        )
        self.status_label.bind(
            width=lambda instance, value: setattr(
                instance, "text_size", (value, None)
            )
        )
        self.add_widget(self.status_label)

        # 弹簧
        self.add_widget(Widget(size_hint=(1, 0.08)))

        # ---- 定时区域 ----
        self.time_caption = Label(
            text=u"定时启动时间（HH:MM:SS）",
            font_size="15sp",
            color=(0.35, 0.35, 0.35, 1),
            size_hint=(1, 0.06),
        )
        self.add_widget(self.time_caption)

        self.time_input = TextInput(
            text=DEFAULT_TIME_TEXT,
            font_size="22sp",
            halign="center",
            multiline=False,
            size_hint=(1, 0.09),
        )
        self.add_widget(self.time_input)

        self.schedule_btn = Button(
            text=u"设置定时",
            font_size="20sp",
            bold=True,
            color=(1, 1, 1, 1),
            background_color=(0.15, 0.45, 0.25, 1),
            size_hint=(1, 0.10),
        )
        self.add_widget(self.schedule_btn)

        self.countdown_label = Label(
            text=u"倒计时：未设定",
            font_size="20sp",
            bold=True,
            color=(0.72, 0.16, 0.10, 1),
            size_hint=(1, 0.09),
        )
        self.add_widget(self.countdown_label)

        # 弹簧
        self.add_widget(Widget(size_hint=(1, 0.12)))

    def _redraw_background(self, *args):
        self._background.pos = self.pos
        self._background.size = self.size

    # ---- 定时相关 ----
    def get_time_text(self):
        """获取时间输入框内容"""
        return self.time_input.text.strip()

    def set_countdown(self, text):
        """更新倒计时文字"""
        self.countdown_label.text = text

    def set_schedule_button_armed(self, armed):
        """定时武装后按钮变为"取消定时"，取消后恢复"""
        self.schedule_btn.text = u"取消定时" if armed else u"设置定时"
        self.schedule_btn.background_color = (
            (0.55, 0.25, 0.25, 1) if armed else (0.15, 0.45, 0.25, 1)
        )

    def set_status(self, text):
        """更新状态提示"""
        self.status_label.text = text
