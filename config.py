# -*- coding: utf-8 -*-
"""
全局配置模块（重构版 v1.0.0）

所有坐标一律使用"绝对像素 / getevent 原始值"，不做屏幕比例换算。
目标设备：OPPO PDSM00，安卓 13，物理屏 1080x2400。
"""

# ---------------- 基础信息 ----------------
APP_TITLE = u"i茅台助手"
APP_VERSION = "1.0.0"

# 物理屏幕像素（adb shell wm size: 1080x2400）
SCREEN_WIDTH = 1080
SCREEN_HEIGHT = 2400

# getevent -lp 触摸屏原始坐标范围（/dev/input/event2）：
# ABS_MT_POSITION_X max=5399，ABS_MT_POSITION_Y max=11999
TOUCH_RAW_MAX_X = 5399
TOUCH_RAW_MAX_Y = 11999

# ---------------- 流程参数 ----------------
# 商品识别关键字：控件文字需同时包含（商品名：飞天53%vol 500ml...）
PRODUCT_KEYWORDS = (u"飞天", u"%vol")

# 右下角按钮区（绝对像素）：开售时间 / 立即抢购 都在此区域读取
BUTTON_REGION_PX = (0, 1968, 1080, 2400)

# "立即抢购"类按钮文字（识别到任一即直接点击）
BUY_NOW_TEXTS = (u"立即抢购", u"立即购买")

# 开售时间特征（含 ":"，如 8:00 / 8:05 / 8:14 / 8:20）
SALE_TIME_REGEX = r"\d{1,2}:\d{2}"

# 读到开售时间后，二次点击额外加的秒数（如 8:05 -> 8:05:01）
SECOND_CLICK_EXTRA_SECONDS = 1

# 到点后等待商品文字出现的超时（秒）
FIND_PRODUCT_TIMEOUT = 60.0
# 点击商品后等待详情页加载的超时（秒）
DETAIL_READ_TIMEOUT = 10.0
# 执行返回后等待列表恢复的时间（秒）
BACK_SETTLE_SECONDS = 2.0

# 二次点击的拟人化落点抖动（像素）
TAP_JITTER_PX = 6

# 主循环间隔（秒）
TICK_INTERVAL = 0.3

# 界面默认时间
DEFAULT_TIME_TEXT = u"08:00:01"
