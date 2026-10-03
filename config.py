# -*- coding: utf-8 -*-
"""
全局配置模块
"""

# APP 基本信息
APP_TITLE = u"i茅台启动器"
APP_VERSION = "0.3.4"

# i茅台 安卓包名（官方包名，应用宝等各渠道一致）
TARGET_PACKAGE = "com.moutai.mall"
TARGET_APP_NAME = u"i茅台"

# 兜底扫描已安装应用时使用的关键字（包名或应用名命中任一即可）
SCAN_KEYWORDS = ("moutai", "maotai", u"茅台")

# UI 中定时时间输入框的默认值：该时间 = 启动 i茅台 的时刻
DEFAULT_TIME_TEXT = u"08:00:01"

# ---------------- 无障碍自动化流程配置 ----------------

# i购 入口按钮（首页右下角的 i购 快捷入口，不是底部标签栏的"购"标签！
# 底部标签栏的"购"是自绘控件，点它会在标签栏区域误触 π社区/小茅运/我的）。
# 坐标来源：用户在 i茅台首页实测手指点击两次——
#   第1次 (1000, 2223)，第2次 (1036, 2218)；
# 物理屏 1080x2400，取两次平均换算为屏幕比例。
I_GOU_TAB_TEXTS = (u"i购", u"购")  # 仅作文字记录，点击一律走坐标
I_GOU_TAB_RATIO = (0.943, 0.925)

# 启动 i茅台后给启动 Intent 的短暂缓冲（秒），之后进入"等待首页"阶段。
# 注意：i茅台冷启动实测需 10~15 秒（开屏广告/加固解压），
# 不能固定等待后盲点，改为识别首页特征后才点击。
LAUNCH_SETTLE_SECONDS = 1

# i茅台首页加载完成的可见特征（首页卡片标题，控件需有真实可见尺寸；
# 底部标签文字节点是 0x0 不可见节点，不能作为依据）。
# 命中至少 HOME_MARKER_MIN_HITS 个才判定首页就绪，此时才允许点击购。
HOME_READY_MARKERS = (u"我的i茅台", u"小茅运")
HOME_MARKER_MIN_HITS = 1
# 等待首页出现的最长时间（秒）
HOME_READY_TIMEOUT = 20.0

# 购页面顶部的分类特征词（筛选标签，必须有真实可见尺寸）。
# 点击购后必须识别到其中至少 I_GOU_MARKER_MIN_HITS 个，才确认
# 已进入购页面、开始滑动；避免在首页/开屏页上盲目重复点击。
I_GOU_PAGE_MARKERS = (u"全部", u"经典", u"精品")
I_GOU_MARKER_MIN_HITS = 2
# 购标签最多点击次数、每次重试间隔，以及进入购阶段的总超时
I_GOU_CLICK_MAX = 3
I_GOU_CLICK_RETRY_INTERVAL = 2.0
ENTER_I_GOU_TIMEOUT = 25.0

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
