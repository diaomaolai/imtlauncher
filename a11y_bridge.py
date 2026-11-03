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
import json

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
        # 服务端是否支持 anyTextExists（旧 APK 没有，首次失败后退回）
        self._any_supported = True
        # 服务端是否支持一次手势连点（旧 APK 没有，首次失败后退回）
        self._multi_supported = True
        # 服务端是否支持整段正则匹配（旧 APK 没有，首次失败后退回）
        self._exact_regex_supported = True
        # 服务端是否支持区域取色（旧 APK/低版本没有，首次失败后退回）
        self._color_supported = True
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

    def current_package(self):
        """
        当前前台窗口的包名；判断是否还在 i茅台。
        手机桌面/其他 APP 会返回各自包名（如 com.huawei.android.launcher）。
        旧 APK 没有该方法时返回 None（调用方退回纯文字判断）。
        """
        service = self._service_or_none()
        if service is None:
            return None
        try:
            return str(service.currentPackageName())
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

    def any_text_exists(self, texts):
        """
        一次遍历判断页面上是否存在给定文字中的任意一个。
        连点流程每个节拍都要判弹窗，逐个 textExists 会做 N 次全树
        遍历，必须合并成一次（Java anyTextExists）。
        老版本 APK 没有该方法时自动退回逐个 textExists。
        """
        service = self._service_or_none()
        if service is None:
            return False
        wanted = [u"%s" % text for text in texts]
        if self._any_supported:
            try:
                return bool(service.anyTextExists(wanted))
            except Exception:
                # 方法不存在（旧 APK）：本次起退回逐个判断
                self._any_supported = False
        for text in wanted:
            try:
                if service.textExists(text):
                    return True
            except Exception:
                pass
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

    def find_exact_regex_texts(self, regex):
        """
        全页扫描"整段文本"匹配正则的控件（matcher.matches），返回捕获
        分组（如 09:00），按控件底边由下往上排序。

        按钮时间必须用这个方法：按钮文字是整段 "09:00投放"，而按钮
        上方的说明文字「每日09:00、20:00投放」只是"包含"，整段匹配
        不会命中说明文字。

        返回 None 表示旧 APK 没有该方法（调用方退回区域扫描）；
        返回 [] 表示有该方法但当前页面没有匹配。
        """
        service = self._service_or_none()
        if service is None or not self._exact_regex_supported:
            return None
        try:
            result = service.findExactRegexTexts(regex)
            return [str(item) for item in result]
        except Exception:
            # 方法不存在（旧 APK）：本次起退回区域扫描
            self._exact_regex_supported = False
            return None

    # ---------------- 全量节点 dump（校准用） ----------------
    def dump_nodes(self):
        """
        全量节点树 dump，返回扁平节点列表，每个节点含：
        window/i/p/c/id/t/d/ck/sc/b（b 为 [l,t,r,b] 绝对像素）。
        取不到节点时返回空列表。
        """
        service = self._service_or_none()
        if service is None:
            return []
        try:
            raw = service.dumpNodesJson()
            data = json.loads(str(raw))
        except Exception:
            return []
        nodes = []
        try:
            for window in data:
                win_index = int(window.get(u"window", 0))
                for node in window.get(u"nodes", []):
                    node[u"window"] = win_index
                    nodes.append(node)
        except Exception:
            return nodes
        return nodes

    def save_screenshot(self, path):
        """
        截取当前屏幕以 PNG 写入指定路径（API 30+），
        成功返回 True；低版本或失败返回 False。
        """
        service = self._service_or_none()
        if service is None:
            return False
        try:
            return bool(service.takeScreenshotToFile(path))
        except Exception:
            return False

    def average_color_in_px_region(self, region_px):
        """
        取指定像素区域的平均颜色，返回 (r, g, b)；取不到返回 None。
        用于按按钮填充色判断状态（灰=不可点 / 黄橙=立即抢购），
        与按钮在说明文字上方还是下方无关。旧 APK 没有该方法时返回 None。
        """
        service = self._service_or_none()
        if service is None or not self._color_supported:
            return None
        try:
            min_x, min_y, max_x, max_y = region_px
            rgb = service.averageColorInPxRegion(
                int(min_x), int(min_y), int(max_x), int(max_y)
            )
            if rgb is None:
                return None
            return (int(rgb[0]), int(rgb[1]), int(rgb[2]))
        except Exception:
            # 方法不存在（旧 APK）或低版本：本次起不再尝试
            self._color_supported = False
            return None

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

    def tap_multi_px(self, x, y, count, jitter_px=6, gap_ms=130):
        """
        同一位置连续点击 count 次，一次手势派发（数量加号用）。
        老版本 APK 没有该方法时退回逐个 tap_px。
        """
        count = int(count)
        if count <= 0:
            return True
        service = self._service_or_none()
        if service is None:
            return False
        if self._multi_supported:
            try:
                return bool(service.tapMultiPxHuman(
                    int(x), int(y), count, int(jitter_px), int(gap_ms)
                ))
            except Exception:
                self._multi_supported = False
        for _ in range(count):
            if not self.tap_px(x, y, jitter_px):
                return False
        return True

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
