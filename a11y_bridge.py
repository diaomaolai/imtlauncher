# -*- coding: utf-8 -*-
"""
无障碍桥接模块（重构版）

通过 pyjnius 调用工程内 Java 类 MtA11yService（见 src/ 目录）。
所有坐标均为绝对像素，不做比例换算。

提供能力：
- 连接状态判断
- 按关键字查找控件中心坐标（绝对像素）
- 按关键字 / 文字直接点击控件节点
- 在指定像素区域内正则读取文字
- 绝对像素拟人化点击
- 全局返回

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

    # ---------------- 节点查找 ----------------
    def node_center(self, keywords):
        """
        返回文字同时包含全部关键字的控件中心坐标 (x, y)（绝对像素）；
        找不到返回 None。
        """
        service = self._service_or_none()
        if service is None:
            return None
        try:
            center = service.nodeCenterByAllParts(list(keywords))
            if center is None:
                return None
            return int(center[0]), int(center[1])
        except Exception:
            return None

    # ---------------- 节点点击 ----------------
    def text_exists(self, text):
        """页面上是否存在包含该文字的控件（只判断、不点击）"""
        service = self._service_or_none()
        if service is None:
            return False
        try:
            return bool(service.textExists(text))
        except Exception:
            return False

    def click_node_by_parts(self, keywords):
        """点击文字同时包含全部关键字的控件节点，成功返回 True"""
        service = self._service_or_none()
        if service is None:
            return False
        try:
            return bool(service.clickByAllParts(list(keywords)))
        except Exception:
            return False

    def click_text(self, text):
        """点击包含指定文字的控件节点，成功返回 True"""
        service = self._service_or_none()
        if service is None:
            return False
        try:
            return bool(service.clickByText(text))
        except Exception:
            return False

    def click_text_in_px_region(self, text, region_px):
        """
        在指定绝对像素区域 (min_x, min_y, max_x, max_y) 内查找并点击
        包含指定文字的控件，成功返回 True。
        底部标签等文字节点是 0x0 占位节点时，会自动沿父链向上找
        落在区域内、可点击的父布局。
        """
        service = self._service_or_none()
        if service is None:
            return False
        try:
            min_x, min_y, max_x, max_y = region_px
            return bool(service.clickByTextInPxRegion(
                text, int(min_x), int(min_y), int(max_x), int(max_y)
            ))
        except Exception:
            return False

    def text_exists_in_px_region(self, text, region_px):
        """
        区域内是否存在可见的指定文字（0x0 占位节点会向上找有真实
        尺寸的祖先），用于判断页面是否到达。
        """
        service = self._service_or_none()
        if service is None:
            return False
        try:
            min_x, min_y, max_x, max_y = region_px
            return bool(service.textVisibleInPxRegion(
                text, int(min_x), int(min_y), int(max_x), int(max_y)
            ))
        except Exception:
            return False

    # ---------------- 文字读取 ----------------
    def find_regex_in_px_region(self, regex, region_px):
        """
        在指定绝对像素区域 (min_x, min_y, max_x, max_y) 内扫描
        匹配正则的文字，返回列表（靠下的优先）。
        """
        service = self._service_or_none()
        if service is None:
            return []
        try:
            min_x, min_y, max_x, max_y = region_px
            result = service.findRegexTextsInPxRegion(
                regex, int(min_x), int(min_y), int(max_x), int(max_y)
            )
            return [str(item) for item in result]
        except Exception:
            return []

    # ---------------- 手势点击 ----------------
    def tap_px(self, x, y, jitter_px=6):
        """按绝对像素拟人化点击，成功返回 True"""
        service = self._service_or_none()
        if service is None:
            return False
        try:
            return bool(service.tapPxHuman(int(x), int(y), int(jitter_px)))
        except Exception:
            return False

    # ---------------- 返回 ----------------
    def back(self):
        """全局返回，成功返回 True"""
        service = self._service_or_none()
        if service is None:
            return False
        try:
            return bool(service.globalBack())
        except Exception:
            return False
