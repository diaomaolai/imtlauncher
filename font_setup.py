# -*- coding: utf-8 -*-
"""
中文字体注册模块

Kivy 自带的 Roboto 字体不含中文字形，不处理的话界面中文会显示成方块。
这里在运行时注册系统自带中文字体（Windows 调试用微软雅黑/黑体，
安卓用系统 Noto/Droid 中文字体），并覆盖 Kivy 默认字体名 "Roboto"，
所有控件无需单独指定 font_name 即可正常显示中文。
"""

import glob
import os

from kivy.core.text import LabelBase

# 覆盖 Kivy 默认字体名，全部控件自动生效
_DEFAULT_FONT_NAME = "Roboto"


def register_cjk_font():
    """
    查找并注册中文字体。
    返回成功注册的字体路径；未找到则返回 None。
    """
    candidates = []

    # ---- Windows（电脑端调试）----
    candidates += [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
    ]

    # ---- Android 系统字体 ----
    candidates += [
        "/system/fonts/NotoSansCJK-Regular.ttc",
        "/system/fonts/NotoSerifCJK-Regular.ttc",
        "/system/fonts/DroidSansFallback.ttf",
    ]
    candidates += sorted(glob.glob("/system/fonts/*CJK*.ttc"))
    candidates += sorted(glob.glob("/system/fonts/*CJK*.otf"))
    candidates += sorted(glob.glob("/system/fonts/*Fallback*.ttf"))

    # ---- 随 APP 打包的兜底字体（把 ttf 放进 fonts/ 目录即可）----
    local_font_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "fonts"
    )
    if os.path.isdir(local_font_dir):
        candidates += sorted(glob.glob(os.path.join(local_font_dir, "*.ttf")))
        candidates += sorted(glob.glob(os.path.join(local_font_dir, "*.ttc")))

    for font_path in candidates:
        if font_path and os.path.isfile(font_path):
            try:
                LabelBase.register(
                    _DEFAULT_FONT_NAME,
                    fn_regular=font_path,
                    fn_bold=font_path,
                )
                return font_path
            except Exception:
                continue

    return None
