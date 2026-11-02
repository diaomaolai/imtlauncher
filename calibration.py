# -*- coding: utf-8 -*-
"""
自动校准器（首次武装时自动建档）。

触发条件：卡密登录后武装，且本地无匹配设备档案。
行为：自动走现有导航链 首页 → i购 → 经典 → 列表 → 详情，
每到一个页面先全量节点 dump + 截图存证，再提取目标控件 bounds，
详情页只记录、绝不点击抢购按钮，记录完返回列表。

节拍：0.3 秒动态轮询，页面多快出现就多快通过；
点击后未进入下一页面则有限补点，阶段超时仍失败才返回错误。
"""

import os
import re
import time

from config import (
    PRODUCT_KEYWORDS,
    PRODUCT_FULL_TEXTS,
    BUY_NOW_TEXTS,
    SOLD_OUT_TEXTS,
    SALE_TIME_REGEX,
    YEAR_CHOICES,
    IGOU_TAB_TEXT,
    IGOU_CATEGORY_TEXTS,
    JINGDIAN_TAB_TEXT,
    CALIBRATION_SPLASH_WAIT,
    CALIBRATION_STAGE_TIMEOUT,
    CALIBRATION_POLL_INTERVAL,
    CALIBRATION_MAX_CLICK_RETRIES,
    CALIBRATION_SHOT_DIR_NAME,
)
from android_launcher import launch_moutai
from device_profile import DeviceProfile


# ------------------------------------------------------------------
# dump 节点树工具
# ------------------------------------------------------------------

class NodeTree(object):
    """把扁平 dump 组织成带父链/子表的树，供 bounds 提取"""

    def __init__(self, raw_nodes):
        self.nodes = {}
        self.children = {}
        for node in raw_nodes:
            window = int(node.get(u"window", 0))
            index = int(node.get(u"i", -1))
            self.nodes[(window, index)] = node
            parent = int(node.get(u"p", -1))
            self.children.setdefault(
                (window, parent), []
            ).append(node)

    def parent(self, node):
        p_index = int(node.get(u"p", -1))
        if p_index < 0:
            return None
        return self.nodes.get(
            (int(node.get(u"window", 0)), p_index)
        )

    def ancestors(self, node):
        cur = self.parent(node)
        while cur is not None:
            yield cur
            cur = self.parent(cur)

    def siblings(self, node):
        p_index = int(node.get(u"p", -1))
        return self.children.get(
            (int(node.get(u"window", 0)), p_index), []
        )

    @staticmethod
    def bounds(node):
        return [int(v) for v in node.get(u"b", [0, 0, 0, 0])]

    @classmethod
    def has_real_bounds(cls, node):
        left, top, right, bottom = cls.bounds(node)
        return right - left > 1 and bottom - top > 1

    def first_real_ancestor(self, node):
        if self.has_real_bounds(node):
            return node
        for ancestor in self.ancestors(node):
            if self.has_real_bounds(ancestor):
                return ancestor
        return None

    def find_exact(self, text):
        """文字或 contentDescription 精确匹配的第一个节点"""
        for node in self.nodes.values():
            if node.get(u"t") == text or node.get(u"d") == text:
                return node
        return None


# ------------------------------------------------------------------
# 自动校准器
# ------------------------------------------------------------------

class DeviceCalibrator(object):
    """
    自动校准状态机。用法：
        ok, result = DeviceCalibrator(bridge, store, logger).run(stop_event)
    成功 result 为 DeviceProfile；失败 result 为错误说明字符串。
    """

    def __init__(self, bridge, store, logger, stop_event=None):
        self.bridge = bridge
        self.store = store
        self.logger = logger
        self.stop_event = stop_event
        self.shot_dir = os.path.join(store.dir, CALIBRATION_SHOT_DIR_NAME)
        if not os.path.isdir(self.shot_dir):
            os.makedirs(self.shot_dir)
        self.controls = {}
        self.screenshots = []

    def _log(self, line):
        if self.logger is not None:
            self.logger.log(line)
        else:
            print(line)

    def _stopped(self):
        return self.stop_event is not None and self.stop_event.is_set()

    def _wait(self, seconds):
        if self.stop_event is not None:
            self.stop_event.wait(seconds)
        else:
            time.sleep(seconds)

    # ---------------- 动态等待 ----------------

    def _wait_until(self, predicate, what, timeout=None):
        """
        动态轮询直到 predicate 为真；超时返回 False。
        等待期间每 2 秒打一条探针日志（i购/经典/全部/数量 是否存在），
        卡在开屏广告/协议页/加载中时能直接从日志看出是哪一种。
        """
        if timeout is None:
            timeout = CALIBRATION_STAGE_TIMEOUT
        deadline = time.monotonic() + timeout
        last_probe = 0.0
        while time.monotonic() < deadline:
            if self._stopped():
                return False
            try:
                if predicate():
                    return True
            except Exception:
                pass
            now = time.monotonic()
            if now - last_probe >= 2.0:
                last_probe = now
                self._log(u"等待%s… i购=%s 经典=%s 全部=%s 数量=%s"
                          % (what,
                             self.bridge.text_exists(IGOU_TAB_TEXT),
                             self.bridge.text_exists(JINGDIAN_TAB_TEXT),
                             self.bridge.text_exists(u"全部"),
                             self.bridge.text_exists(u"数量")))
            self._wait(CALIBRATION_POLL_INTERVAL)
        self._log(u"校准等待超时：%s（%.0f 秒）" % (what, timeout))
        return False

    def _click_until(self, click_fn, predicate, what):
        """
        先点击，再动态等待下一页面；未到达则补点，
        最多 CALIBRATION_MAX_CLICK_RETRIES 次。
        """
        for attempt in range(CALIBRATION_MAX_CLICK_RETRIES + 1):
            if self._stopped():
                return False
            try:
                click_fn()
            except Exception:
                pass
            if self._wait_until(predicate, what):
                return True
            self._log(u"未进入%s，补点（%d/%d）" % (
                what, attempt + 1, CALIBRATION_MAX_CLICK_RETRIES
            ))
        return False

    # ---------------- 页面判定（全机型通用，不依赖 px） ----------------

    def _is_detail(self):
        """详情页：有「数量」这一行即可（不强制年份是 2026）"""
        return self.bridge.text_exists(u"数量")

    def _is_igou(self):
        """i购分类页：必须同时看到「经典」和「全部」两个分类标签"""
        return self.bridge.text_exists(JINGDIAN_TAB_TEXT) \
            and self.bridge.text_exists(u"全部") \
            and not self.bridge.text_exists(u"数量")

    def _is_home(self):
        """首页：有底部「i购」tab，且不是 i购 分类页、不是详情页"""
        return self.bridge.text_exists(IGOU_TAB_TEXT) \
            and not self.bridge.text_exists(u"数量") \
            and not self._is_igou()

    def _product_center(self):
        """按完整商品名取中心（兼容全角/半角括号），找不到再退回关键词"""
        for name in PRODUCT_FULL_TEXTS:
            center = self.bridge.node_center((name,))
            if center is not None:
                return center
        return self.bridge.node_center(PRODUCT_KEYWORDS)

    def _is_list(self):
        """经典列表页：i购分类页 + 能看到目标商品（完整名称优先）"""
        return self._is_igou() and self._product_center() is not None

    def _click_product(self):
        """点目标商品：完整名称优先，失败再退回「飞天」+「%vol」"""
        for name in PRODUCT_FULL_TEXTS:
            try:
                if self.bridge.click_text(name):
                    return True
            except Exception:
                pass
        return self.bridge.click_node_by_parts(PRODUCT_KEYWORDS)

    # ---------------- 截图与 dump ----------------

    def _capture(self, stage, filename):
        path = os.path.join(self.shot_dir, filename)
        if self.bridge.save_screenshot(path):
            self.screenshots.append({u"stage": stage, u"path": path})
            self._log(u"已截图存证：%s" % path)
        else:
            self._log(u"截图不可用（低版本或失败），节点数据不受影响：%s"
                      % stage)

    def _dump_tree(self):
        return NodeTree(self.bridge.dump_nodes())

    # ---------------- bounds 提取 ----------------

    @staticmethod
    def _record(tree, node):
        bounds = tree.bounds(node)
        return {
            u"bounds": bounds,
            u"center": [
                (bounds[0] + bounds[2]) // 2,
                (bounds[1] + bounds[3]) // 2,
            ],
        }

    def _tab_record(self, tree, text):
        node = tree.find_exact(text)
        if node is None:
            return {}
        target = tree.first_real_ancestor(node)
        if target is None:
            return {}
        return self._record(tree, target)

    def _product_record(self, tree):
        """优先按完整商品名定位卡位；找不到再退回「飞天」+「%vol」"""
        for name in PRODUCT_FULL_TEXTS:
            node = tree.find_exact(name)
            if node is None:
                continue
            target = tree.first_real_ancestor(node) if \
                not tree.has_real_bounds(node) else node
            if target is not None:
                return self._record(tree, target)
        fallback = None
        for node in tree.nodes.values():
            text = u"%s %s" % (
                node.get(u"t") or u"", node.get(u"d") or u""
            )
            if not all(part in text for part in PRODUCT_KEYWORDS):
                continue
            if tree.has_real_bounds(node):
                return self._record(tree, node)
            if fallback is None:
                fallback = node
        if fallback is not None:
            target = tree.first_real_ancestor(fallback)
            if target is not None:
                return self._record(tree, target)
        return {}

    def _category_records(self, tree):
        """采集 i购 顶部分类标签（全部/经典/精品/生肖/陈年/文化/低度）"""
        records = {}
        for name in IGOU_CATEGORY_TEXTS:
            record = self._tab_record(tree, name)
            if record:
                records[name] = record
        return records

    def _button_state_text(self, tree):
        """当前按钮处于哪种状态：投放时间 / 立即抢购 / 已售罄"""
        pattern = re.compile(SALE_TIME_REGEX)
        for node in tree.nodes.values():
            text = node.get(u"t") or u""
            if not text or not tree.has_real_bounds(node):
                continue
            matched = pattern.search(text)
            if matched:
                return u"投放时间 %s" % matched.group()
            if any(mark in text for mark in BUY_NOW_TEXTS):
                return u"立即抢购"
            if any(mark in text for mark in SOLD_OUT_TEXTS):
                return u"已售罄"
        return u"未识别"

    def _year_records(self, tree):
        records = {}
        for node in tree.nodes.values():
            year = (node.get(u"t") or u"").strip()
            if year in YEAR_CHOICES and tree.has_real_bounds(node):
                records[year] = self._record(tree, node)
        return records

    def _qty_records(self, tree):
        """返回 (数字框, 减号, 加号) 三个记录；取不到为空字典"""
        empty = {}, {}, {}
        label = tree.find_exact(u"数量")
        if label is None:
            return empty
        value = None
        for ancestor in tree.ancestors(label):
            window = int(ancestor.get(u"window", 0))
            for child in tree.children.get(
                (window, int(ancestor.get(u"i", -1))), []
            ):
                class_name = child.get(u"c", u"")
                text = (child.get(u"t") or u"").strip()
                if u"EditText" in class_name \
                        and re.fullmatch(r"\d+", text):
                    value = child
                    break
            if value is not None:
                break
        if value is None:
            return empty
        all_siblings = [
            node for node in tree.siblings(value)
            if node is not value and tree.has_real_bounds(node)
        ]
        # 加减号无文字（ImageView/Button），先排除带文字的数量标签；
        # 找不到无文字按钮时再退回全部同级节点
        siblings = [
            node for node in all_siblings
            if not (node.get(u"t") or node.get(u"d"))
        ] or all_siblings
        if not siblings:
            return self._record(tree, value), {}, {}
        minus = min(siblings, key=lambda n: tree.bounds(n)[0])
        plus = max(siblings, key=lambda n: tree.bounds(n)[0])
        return (
            self._record(tree, value),
            self._record(tree, minus),
            self._record(tree, plus),
        )

    def _button_record(self, tree):
        pattern = re.compile(SALE_TIME_REGEX)
        best = None
        for node in tree.nodes.values():
            text = node.get(u"t") or u""
            if not text or not tree.has_real_bounds(node):
                continue
            matched = bool(pattern.search(text)) \
                or any(mark in text for mark in BUY_NOW_TEXTS) \
                or any(mark in text for mark in SOLD_OUT_TEXTS)
            if not matched:
                continue
            if best is None \
                    or tree.bounds(node)[3] > tree.bounds(best)[3]:
                best = node
        if best is None:
            return {}
        return self._record(tree, best)

    # ---------------- 主流程 ----------------

    def run(self):
        if not self.bridge.is_connected():
            return False, u"无障碍服务未开启，无法校准"

        fingerprint, native, _pkg = self._build_fingerprint()
        if not fingerprint.get(u"installed"):
            return False, u"未检测到 i茅台（%s），无法校准" \
                % fingerprint.get(u"moutai_package")

        self._log(u"首次武装，开始自动校准设备（不抢购）")
        launch_moutai(self.logger)

        # 0) 等开屏广告结束：先按 10 秒等，没等到再按阶段超时继续等
        ready = lambda: (
            self._is_home() or self._is_igou() or self._is_detail()
        )
        self._log(u"等待开屏广告结束（约 %.0f 秒）…"
                  % CALIBRATION_SPLASH_WAIT)
        if not self._wait_until(ready, u"i茅台首屏",
                                CALIBRATION_SPLASH_WAIT):
            self._log(u"首屏仍未出现（可能在广告/协议/登录页），"
                      u"继续等到 %.0f 秒…" % CALIBRATION_STAGE_TIMEOUT)
            if not self._wait_until(ready, u"i茅台首屏"):
                return False, (u"校准失败：未进入 i茅台页面"
                               u"（开屏广告/隐私协议/未登录？）")

        # 0b) 起点若在详情页，先退回列表（这次修掉了旧逻辑的死分支）
        if self._is_detail():
            self._log(u"当前在详情页，先退回商品列表")
            self.bridge.back()
            if not self._wait_until(
                lambda: self._is_home() or self._is_igou(),
                u"退回商品列表"
            ):
                return False, u"校准失败：详情页无法退回"

        # 1) 首页：截图 → 识别 i购 → 点击
        if self._is_home():
            if not self._wait_until(self._is_home, u"首页渲染"):
                return False, u"校准失败：首页未渲染完成"
            tree = self._dump_tree()
            self._capture(u"home", u"01_home.png")
            self.controls[u"igou_tab"] = self._tab_record(
                tree, IGOU_TAB_TEXT
            )
            self._log(u"已采集 i购标签 bounds：%s"
                      % self.controls[u"igou_tab"].get(u"bounds"))
            if not self._click_until(
                lambda: self.bridge.click_text(IGOU_TAB_TEXT),
                self._is_igou, u"i购页面"
            ):
                return False, u"校准失败：点击 i购 后未进入 i购页"
        else:
            self._log(u"当前已在 i购 分类页，跳过首页阶段")

        # 2) i购页：截图 → 识别全部分类（全部/经典/精品/生肖/陈年/
        #    文化/低度）→ 点击 经典
        if not self._wait_until(self._is_igou, u"i购分类页渲染"):
            return False, u"校准失败：i购页未渲染完成"
        tree = self._dump_tree()
        self._capture(u"igou", u"02_igou.png")
        categories = self._category_records(tree)
        self.controls[u"category_tabs"] = categories
        self.controls[u"jingdian_tab"] = categories.get(
            JINGDIAN_TAB_TEXT
        ) or self._tab_record(tree, JINGDIAN_TAB_TEXT)
        self._log(u"已采集分类标签 %d 个：%s"
                  % (len(categories), u"、".join(categories.keys())))
        if not self._click_until(
            lambda: self.bridge.click_text(JINGDIAN_TAB_TEXT),
            self._is_list, u"经典商品列表"
        ):
            return False, u"校准失败：点击 经典 后未进入列表"

        # 3) 列表页：截图 → 识别目标商品 → 点击进详情
        if not self._wait_until(self._is_list, u"商品列表渲染"):
            return False, u"校准失败：列表未出现目标商品"
        tree = self._dump_tree()
        self._capture(u"list", u"03_list.png")
        self.controls[u"product_card"] = self._product_record(tree)
        self._log(u"已采集商品卡位 bounds：%s"
                  % self.controls[u"product_card"].get(u"bounds"))
        if not self._click_until(
            self._click_product, self._is_detail, u"商品详情页"
        ):
            return False, u"校准失败：点击商品后未进入详情页"

        # 4) 详情页：截图 → 年份规格 → 数量/加减 → 按钮三种状态
        if not self._wait_until(self._is_detail, u"详情页渲染"):
            return False, u"校准失败：详情页未渲染完成"
        tree = self._dump_tree()
        self._capture(u"detail", u"04_detail.png")
        self.controls[u"year_cells"] = self._year_records(tree)
        value, minus, plus = self._qty_records(tree)
        self.controls[u"qty_value"] = value
        self.controls[u"qty_minus"] = minus
        self.controls[u"qty_plus"] = plus
        self.controls[u"action_button"] = self._button_record(tree)
        self._log(
            u"已采集年份格 %d 个、数量控件（数字/减/加=%s/%s/%s）、"
            u"按钮状态=%s，未点击任何购买按钮"
            % (len(self.controls[u"year_cells"]),
               u"有" if value else u"无",
               u"有" if minus else u"无",
               u"有" if plus else u"无",
               self._button_state_text(tree))
        )

        # 5) 返回列表，结束校准
        self.bridge.back()
        if not self._wait_until(self._is_list, u"返回商品列表"):
            self._log(u"详情页返回列表超时，档案仍保留")
        else:
            self._log(u"已返回商品列表，校准导航结束")

        profile = DeviceProfile(
            fingerprint=fingerprint,
            controls=self.controls,
            metrics=self._derive_metrics(native),
            screenshots=self.screenshots,
        )
        self.store.save(profile)
        self._log(u"自动校准完成，后续武装直接加载档案，不再重复截图")
        return True, profile

    def _build_fingerprint(self):
        from device_profile import build_fingerprint
        return build_fingerprint()

    @staticmethod
    def _derive_metrics(native):
        width = native.get(u"screen_w", 0)
        height = native.get(u"screen_h", 0)
        density = native.get(u"density", 0.0)
        metrics = {
            u"dp_w": round(width / density, 1) if density else 0,
            u"dp_h": round(height / density, 1) if density else 0,
            u"aspect": round(height / width, 3) if width else 0,
        }
        metrics.update(native)
        return metrics
