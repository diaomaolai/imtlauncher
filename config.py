# -*- coding: utf-8 -*-
"""
全局配置模块
"""

# APP 基本信息
APP_TITLE = u"i茅台启动器"
APP_VERSION = "0.3.0"

# i茅台 安卓包名（官方包名，应用宝等各渠道一致）
TARGET_PACKAGE = "com.moutai.mall"
TARGET_APP_NAME = u"i茅台"

# 兜底扫描已安装应用时使用的关键字（包名或应用名命中任一即可）
SCAN_KEYWORDS = ("moutai", "maotai", u"茅台")

# UI 中定时时间输入框的默认值：该时间 = 启动 i茅台 的时刻
DEFAULT_TIME_TEXT = u"08:00:01"

# ---------------- 无障碍自动化流程配置 ----------------

# i茅台 底部 "购" 标签。
# 实测（OPPO 安卓13，i茅台当前版本）该标签为自绘控件，文字不暴露给
# 无障碍（控件树里只有无文字的 LinearLayout 容器），按文字点不中；
# 因此保留候选文字（兼容未来版本），同时提供按屏幕比例的坐标兜底。
I_GOU_TAB_TEXTS = (u"i购", u"购")
# 点击容器实测 bounds=[216,2043][432,2161]，中心 (324,2102)，
# 物理屏 1080x2400 换算比例：
I_GOU_TAB_RATIO = (0.30, 0.876)

# 目标商品：同一控件文字需同时包含以下全部关键字才算找到
# （列表上的完整名称约为：飞天53%vol 500ml贵州茅台酒(带杯)）
PRODUCT_KEYWORDS = (u"飞天53%vol 500ml", u"带杯")

# 商品详情页右下角开售时间的识别正则（如 8:05 / 08:10）
SALE_TIME_REGEX = r"\d{1,2}:\d{2}"

# 读到开售时间 HH:MM 后，额外加多少秒执行第二次点击
# （开售瞬间按钮才会变成可购买，加 1 秒更稳）
SECOND_CLICK_EXTRA_SECONDS = 1

# 商品详情页要点击的购买按钮文字，按顺序尝试
FINAL_BUTTON_TEXTS = (u"立即购买", u"预约申购", u"确定")

# 滑动节奏（秒）：每次上滑/列表前滚之间的等待，给列表加载时间
SCROLL_INTERVAL = 1.2

# ---------------- 拟人化手势参数 ----------------
# 点击落点随机抖动范围（屏幕比例，0.01 ≈ 10px）
TAP_JITTER_RATIO = 0.01
# 兜底购买点击要求更准，抖动更小
FINAL_TAP_JITTER_RATIO = 0.006
# 上滑轨迹横向抖动（屏幕比例，0.02 ≈ 22px）
SWIPE_JITTER_RATIO = 0.02
# 上滑时长随机区间（毫秒）
SWIPE_DURATION_MIN_MS = 320
SWIPE_DURATION_MAX_MS = 520

# 详情页右下角购买按钮的识别窗口（秒）：超过这个时间没识别到，
# 立刻按 FALLBACK_FINAL_CLICK_RATIO 位置兜底点击
BUY_CLICK_WAIT_SECONDS = 1.0

# 返回列表后等待商品重新出现的最长时间（秒）
BACK_LIST_TIMEOUT = 5

# 商品详情页右下角购买按钮区（屏幕比例 min_x, min_y, max_x, max_y）。
# 开售时间文字与"立即购买"按钮都在这个区域内，识别只扫这里，
# 避免和页面其他位置的时间文字混淆。
BUY_BUTTON_REGION = (0.0, 0.82, 1.0, 1.0)

# 找不到购买按钮时的兜底坐标点击（按屏幕比例，0~1）；
# None 表示不兜底。
# 位置来源：adb getevent 实测手指点击，触摸屏原始坐标
# 4445,11115；getevent -lp 确认面板范围 5399x11999，
# 换算为屏幕比例（1080x2400 下约为 889,2223）。
FALLBACK_FINAL_CLICK_RATIO = (0.823, 0.926)
