# -*- coding: utf-8 -*-
"""
无障碍桥接模块

通过 pyjnius 调用工程内 Java 类 MtA11yService（见 src/ 目录），
为自动化流程提供：连接状态、文字存在判断、按文字点击、
列表前滚、手势上滑、比例坐标点击、返回。

非安卓环境（电脑端调试）安全降级，可注入模拟实现做流程测试。
"""

# pyjnius 只存在于 python-for-android 打包后的安卓环境
try:
    from jnius import autoclass
    _ANDROID = True
except Exception:
    autoclass = None
    _ANDROID = False


class A11yBridge(object):
    """无障碍服务的 Python 封装"""

    def __init__(self):
        self._service_class = None
        self._service = None
        if _ANDROID:
            self._init_native()

    def _init_native(self):
        """加载 Java 服务类；此时服务未必已授权，方法内动态取实例"""
        self._service_class = autoclass(
            "org.personal.imtlauncher.MtA11yService"
        )

    @property
    def is_android(self):
        return _ANDROID

    def is_connected(self):
        """无障碍开关是否已打开、服务已连接"""
        if not _ANDROID or self._service_class is None:
            return False
        try:
            return bool(self._service_class.isReady())
        except Exception:
            return False

    def _service_or_none(self):
        """取当前在线的服务实例；未连接返回 None"""
        if not self.is_connected():
            return None
        try:
            return self._service_class.getInstance()
        except Exception:
            return None

    # ---------------- 能力方法 ----------------
    def text_exists(self, text):
        """页面上是否存在包含该文字的控件"""
        service = self._service_or_none()
        if service is None:
            return False
        try:
            return bool(service.textExists(text))
        except Exception:
            return False

    def node_contains_all(self, keywords):
        """是否存在文字同时包含全部关键字的控件"""
        service = self._service_or_none()
        if service is None:
            return False
        try:
            # pyjnius 可接受 Python 序列转 Java String[]
            return bool(service.nodeContainsAll(list(keywords)))
        except Exception:
            return False

    def click_text(self, text, region=None):
        """
        按文字查找并点击，成功返回 True。
        region 为 (min_x, min_y, max_x, max_y) 屏幕比例元组时，
        只在该区域内查找（如只在右下角按钮区找"立即购买"）。
        """
        service = self._service_or_none()
        if service is None:
            return False
        try:
            if region is None:
                return bool(service.clickByText(text))
            min_x, min_y, max_x, max_y = region
            return bool(
                service.clickByTextInRegion(
                    text, float(min_x), float(min_y),
                    float(max_x), float(max_y)
                )
            )
        except Exception:
            return False

    def find_regex_texts(self, regex, region=None):
        """
        扫描页面，返回匹配正则的文字列表（屏幕靠下的优先）。
        region 为 (min_x, min_y, max_x, max_y) 屏幕比例元组时，
        只在该区域内扫描（如只读取右下角按钮区的开售时间）。
        """
        service = self._service_or_none()
        if service is None:
            return []
        try:
            if region is None:
                result = service.findRegexTexts(regex)
            else:
                min_x, min_y, max_x, max_y = region
                result = service.findRegexTextsInRegion(
                    regex, float(min_x), float(min_y),
                    float(max_x), float(max_y)
                )
            return [str(item) for item in result]
        except Exception:
            return []

    def click_all_parts(self, keywords):
        """点击文字同时包含全部关键字的控件"""
        service = self._service_or_none()
        if service is None:
            return False
        try:
            return bool(service.clickByAllParts(list(keywords)))
        except Exception:
            return False

    def scroll_forward(self):
        """可滚动列表前滚一次"""
        service = self._service_or_none()
        if service is None:
            return False
        try:
            return bool(service.scrollForwardOnce())
        except Exception:
            return False

    def swipe_up(self, cx_ratio=0.5, top_ratio=0.30, bottom_ratio=0.80,
                 duration_ms=380):
        """手势从下往上滑动（坐标为屏幕比例）"""
        service = self._service_or_none()
        if service is None:
            return False
        try:
            return bool(
                service.swipeUpRatios(
                    float(cx_ratio), float(top_ratio),
                    float(bottom_ratio), int(duration_ms)
                )
            )
        except Exception:
            return False

    def tap_ratio(self, x_ratio, y_ratio):
        """按屏幕比例点击坐标（兜底）"""
        service = self._service_or_none()
        if service is None:
            return False
        try:
            return bool(service.tapRatio(float(x_ratio), float(y_ratio)))
        except Exception:
            return False

    def back(self):
        """全局返回"""
        service = self._service_or_none()
        if service is None:
            return False
        try:
            return bool(service.globalBack())
        except Exception:
            return False
