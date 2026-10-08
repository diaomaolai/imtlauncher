# -*- coding: utf-8 -*-
"""
全局配置模块（v1.2.0 循环作战版）

所有坐标一律使用"绝对像素"，不做屏幕比例换算。
目标设备：OPPO PDSM00，安卓 13，物理屏 1080x2400。
"""

# ---------------- 基础信息 ----------------
APP_TITLE = u"i茅台助手"
APP_VERSION = "1.2.0"

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

# 右下角按钮区（绝对像素）：只覆盖按钮本身（节点中心落在此
# 区域才会被读取），排除"每日09:00、20:00投放"说明文字。
BUTTON_REGION_PX = (600, 2124, 1080, 2200)

# "立即抢购"类按钮文字（识别到任一即 1 秒内点击）
BUY_NOW_TEXTS = (u"立即抢购", u"立即购买")

# "已售罄"按钮文字（识别到即返回列表并结束启动器；两种写法都兼容）
SOLD_OUT_TEXTS = (u"已售罄", u"已售磬")

# 开售时间特征：按钮文字为"09:00投放"/"20:00投放"，
# 用前瞻只匹配紧跟"投放"的时间，取出的分组仍是 "09:00"
SALE_TIME_REGEX = r"\d{1,2}:\d{2}(?=投放)"

# 读到"已过时间"后，重新进入商品侦察下一场的间隔（秒）
RE_SCOUT_INTERVAL = 4.0

# 详情页动态判断：连续读到相同时间的次数达到该值即采信，
# 不设固定等待秒数，页面刷新多快就多快通过
STABLE_READ_COUNT = 2

# 弹窗/等待期间心跳日志间隔（秒）
WAIT_HEARTBEAT = 5.0

# 点击的拟人化落点抖动（像素）
TAP_JITTER_PX = 6

# 主循环间隔（秒）
TICK_INTERVAL = 0.3

# 界面默认时间
DEFAULT_TIME_TEXT = u"08:00:01"
