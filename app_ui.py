# -*- coding: utf-8 -*-
"""
界面模块：i茅台启动器主界面（竖屏）

包含：
- 本机设备 ID 展示（启动自动获取，可手动编辑）+ 复制按钮
- 提示语：复制设备ID联系管理员，获取使用卡密
- 卡密输入 + 卡密登录按钮（登录前定时区锁定）
- 卡密信息（剩余次数/到期时间）
- 定时时间输入（HH:MM:SS）+ 设置定时按钮 + 倒计时
"""

from kivy.core.clipboard import Clipboard
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from config import (
    APP_TITLE,
    DEFAULT_TIME_TEXT,
    YEAR_CHOICES,
    YEAR_TARGET_TEXT,
)
from device_info import get_device_code


def _time_input_filter(substring, undo):
    """时间输入框：只允许半角数字、冒号、点（小数秒），
    挡掉全角数字/全角冒号/中文等"""
    return u"".join(
        c
        for c in substring
        if c in u"0123456789:."
    )


def _card_input_filter(substring, undo):
    """卡密输入框：只允许英文字母、数字、中划线，并统一转大写"""
    return u"".join(
        c
        for c in substring
        if c == u"-" or (c.isascii() and c.isalnum())
    ).upper()


class MainScreen(BoxLayout):
    """主界面：卡密授权 + 定时设置"""

    def __init__(self, **kwargs):
        super(MainScreen, self).__init__(**kwargs)
        self.orientation = "vertical"
        # padding/spacing 用 dp：随屏幕密度自动缩放，不同分辨率观感一致
        self.padding = [dp(36), dp(48), dp(36), dp(36)]
        self.spacing = dp(10)

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
            size_hint=(1, 0.07),
        )
        self.add_widget(self.title_label)

        # 状态文字
        self.status_label = Label(
            text=u"请先完成卡密授权登录",
            font_size="16sp",
            color=(0.25, 0.25, 0.25, 1),
            halign="center",
            valign="middle",
            size_hint=(1, 0.08),
        )
        self.status_label.bind(
            width=lambda instance, value: setattr(
                instance, "text_size", (value, None)
            )
        )
        self.add_widget(self.status_label)

        # ---- 设备 ID ----
        self.device_caption = Label(
            text=u"本机设备 ID（SN + Android ID，可手动补全）",
            font_size="14sp",
            color=(0.35, 0.35, 0.35, 1),
            size_hint=(1, 0.035),
        )
        self.add_widget(self.device_caption)

        self.device_input = TextInput(
            text=get_device_code(),
            font_size="15sp",
            halign="center",
            multiline=False,
            size_hint=(1, 0.055),
        )
        self.add_widget(self.device_input)

        # 提示语 + 复制按钮
        self.device_hint = Label(
            text=u"复制设备ID联系管理员，获取使用卡密",
            font_size="14sp",
            color=(0.55, 0.2, 0.1, 1),
            size_hint=(1, 0.04),
        )
        self.add_widget(self.device_hint)

        self.copy_btn = Button(
            text=u"复制设备ID",
            font_size="15sp",
            color=(1, 1, 1, 1),
            background_color=(0.3, 0.4, 0.6, 1),
            size_hint=(1, 0.055),
        )
        self.copy_btn.bind(on_press=self._on_copy_pressed)
        self.add_widget(self.copy_btn)

        # ---- 卡密 ----
        self.card_caption = Label(
            text=u"卡密（如 7XZJ5-HFTN6-7LN8R-2MD3L）",
            font_size="14sp",
            color=(0.35, 0.35, 0.35, 1),
            size_hint=(1, 0.035),
        )
        self.add_widget(self.card_caption)

        self.card_input = TextInput(
            text=u"",
            font_size="15sp",
            halign="center",
            multiline=False,
            write_tab=False,
            input_filter=_card_input_filter,
            size_hint=(1, 0.055),
        )
        # max_length 不能在构造参数里传（Kivy 2.3.10 构造期会原生崩溃），
        # 必须构造后再设置
        self.card_input.max_length = 19
        self.add_widget(self.card_input)

        self.login_btn = Button(
            text=u"卡密登录",
            font_size="18sp",
            bold=True,
            color=(1, 1, 1, 1),
            background_color=(0.2, 0.35, 0.7, 1),
            size_hint=(1, 0.07),
        )
        self.add_widget(self.login_btn)

        # 卡密信息（剩余次数/到期时间）
        self.card_info_label = Label(
            text=u"未授权",
            font_size="14sp",
            color=(0.4, 0.4, 0.4, 1),
            halign="center",
            valign="middle",
            size_hint=(1, 0.04),
        )
        self.card_info_label.bind(
            width=lambda instance, value: setattr(
                instance, "text_size", (value, None)
            )
        )
        self.add_widget(self.card_info_label)

        # ---- 年份（规格）下拉：卡密登录后显现，位于卡密与时间之间 ----
        self.year_row = BoxLayout(
            orientation="horizontal",
            spacing=dp(8),
            size_hint=(1, 0.055),
            opacity=0,
            disabled=True,
        )
        self.year_caption = Label(
            text=u"年份（规格）",
            font_size="14sp",
            color=(0.35, 0.35, 0.35, 1),
            size_hint=(0.4, 1),
        )
        self.year_row.add_widget(self.year_caption)
        self.year_spinner = Spinner(
            text=YEAR_TARGET_TEXT,
            values=list(YEAR_CHOICES),
            font_size="16sp",
            disabled=True,
            size_hint=(0.6, 1),
        )
        self.year_row.add_widget(self.year_spinner)
        self.add_widget(self.year_row)

        # ---- 定时区域（登录前锁定）----
        self.time_caption = Label(
            text=u"定时启动时间（HH:MM:SS）",
            font_size="14sp",
            color=(0.35, 0.35, 0.35, 1),
            size_hint=(1, 0.04),
        )
        self.add_widget(self.time_caption)

        self.time_input = TextInput(
            text=DEFAULT_TIME_TEXT,
            font_size="20sp",
            halign="center",
            multiline=False,
            write_tab=False,
            input_filter=_time_input_filter,
            disabled=True,
            size_hint=(1, 0.07),
        )
        # max_length 构造后再设置（见 card_input 说明）
        self.time_input.max_length = 12
        self.add_widget(self.time_input)

        self.schedule_btn = Button(
            text=u"设置定时（需先登录）",
            font_size="18sp",
            bold=True,
            color=(1, 1, 1, 1),
            background_color=(0.15, 0.45, 0.25, 1),
            disabled=True,
            size_hint=(1, 0.08),
        )
        self.add_widget(self.schedule_btn)

        self.countdown_label = Label(
            text=u"倒计时：未设定",
            font_size="18sp",
            bold=True,
            color=(0.72, 0.16, 0.10, 1),
            size_hint=(1, 0.06),
        )
        self.add_widget(self.countdown_label)

        # 弹簧
        self.add_widget(Widget(size_hint=(1, 0.04)))

    def _redraw_background(self, *args):
        self._background.pos = self.pos
        self._background.size = self.size

    # ---- 设备 ID ----
    def get_device_code(self):
        """获取设备标识文本框内容（SN + Android ID）"""
        return self.device_input.text.strip()

    def _on_copy_pressed(self, instance):
        """复制设备 ID 到剪贴板"""
        Clipboard.copy(self.get_device_code())
        self.status_label.text = u"设备 ID 已复制，联系管理员获取卡密"

    # ---- 卡密 ----
    def get_card_key(self):
        """获取卡密文本框内容（默认空）"""
        return self.card_input.text.strip()

    def set_login_button_busy(self, busy):
        """登录请求中：按钮置灰防重复点击"""
        self.login_btn.disabled = bool(busy)
        self.login_btn.text = u"登录中…" if busy else u"卡密登录"

    def set_card_info(self, text):
        """显示卡密信息（剩余次数/到期时间）"""
        self.card_info_label.text = text

    # ---- 年份 ----
    def get_year_text(self):
        """获取下拉菜单选定的年份；未选择时为默认年份"""
        year = (self.year_spinner.text or u"").strip()
        return year or YEAR_TARGET_TEXT

    # ---- 授权解锁 ----
    def set_unlocked(self, unlocked):
        """卡密登录成功后解锁定时区与到点自启动；失败保持锁定"""
        self.schedule_btn.disabled = not unlocked
        self.time_input.disabled = not unlocked
        # 年份下拉：登录成功后显现并可点，未登录隐藏且禁用
        self.year_row.opacity = 1 if unlocked else 0
        self.year_row.disabled = not unlocked
        self.year_spinner.disabled = not unlocked
        if unlocked:
            self.schedule_btn.text = u"设置定时"
            self.login_btn.text = u"已授权（重新登录）"
            self.login_btn.background_color = (0.2, 0.5, 0.3, 1)
        else:
            self.schedule_btn.text = u"设置定时（需先登录）"
            self.login_btn.text = u"卡密登录"
            self.login_btn.background_color = (0.2, 0.35, 0.7, 1)

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
