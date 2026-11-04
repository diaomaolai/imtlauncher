# -*- coding: utf-8 -*-
"""
核心流程模块（循环作战版）

首次触发时先自动导航：首页底部区域识别点「i购」→ i购页
子标签区域识别点「经典」→ 经典列表出现「飞天」+「%vol」后才进入商品
（i购默认「全部」视图有「鼓乐飞天」，不点经典会误点）。

总原则：
- 已售罄：需二次确认（返回列表重新进入仍为售罄）才结束启动器，
  这是唯一正常结束；
- 其余所有情况（立即抢购 / 未来时间 / 已过时间 / 弹窗 / 无响应）
  一律循环，一场接一场，不主动结束。

列表确认（防误判）：
  必须同时看到「飞天」+「%vol」商品节点和列表独有标签
  （全部/经典/精品）才认定在列表；详情页标题也含"飞天"，
  靠标签排除，防止误点标题导致连点。

循环逻辑：
1. 定时到点 → 列表双确认 → 点击飞天文字节点（记录位置）→ 进详情；
2. 进详情第一步先选年份（规格区域内识别并点击目标年份，默认当前
   年份，如 2026），区域限定识别，动态轮询无固定等待；
   年份区域缺失但抢购按钮已渲染时直接放行（防页面改版卡死）；
2b. 年份确认后改数量：识别数量数字框（默认 2 瓶），点加号改为
   目标数量（6 瓶），同一拍内连续点完并下一拍复核，未到目标
   继续补点；数量控件缺失但按钮已渲染时放行（防改版卡死）；
3. 详情页（动态识别，无固定等待）：
   - 立即抢购/立即购买：识别到立刻点，随后进入连点模式：
     点一次 → 独立随机等 0.00~0.99 秒 → 再点一次 → 再随机等 …；
   - 开售时间（按钮"HH:MM投放"，右下角区域）：连续 2 次读数一致
     才采信；未来时间返回列表等整点（不加秒）；若读到本场时间
     但已过且仍在宽限内，说明重新加载没刷新到按钮，退出重进；
   - 已售罄：首次返回列表重新进入复核，第二次仍售罄才结束；
   - 未识别到：不中止、不返回，无限等待（应对弹窗/未刷新）；
4. 连点模式（点击购买后）：
   - 每点一次后独立随机 0.00~0.99 秒（两位数字各自 0-9 随机）再点；
   - 节点级 ACTION_CLICK，不会误点到弹窗上的按钮；
   - 每次点完立刻判两类界面变化（各一次合并遍历）：
     a) 出现安全组件（填字/点选）验证弹窗 → 立即停止点击，转入
        WAIT_VERIFY 等待人工验证，等待期间绝不再点任何按钮；
     b) 界面刷新成订单/支付页 → 抢购成功，上报并结束（只上报）；
   - 切换界面前按钮变为开售时间 → 交回详情识别；
   - 只有识别到「已售罄」才停止：返回列表重新进入复核，
     二次仍为售罄才结束；
5. 整点等待：到点点击记录位置进入，先选年份、改数量再交由详情页；
6. 弹窗（含风控倒计时）：任何环节只等待，不点任何按钮。

全程通过 AppLogger 打印并写入 txt 日志。
"""

import threading
import time
from datetime import timedelta

from config import (
    PRODUCT_FULL_TEXTS,
    BUTTON_REGION_PX,
    BUY_NOW_TEXTS,
    LIST_MARKER_TEXTS,
    VERIFY_POPUP_TEXTS,
    ORDER_PAGE_TEXTS,
    SOFT_HINT_TEXTS,
    SOFT_HINT_LOG_INTERVAL,
    SOFT_HINT_CHECK_EVERY,
    VERIFY_POLL_INTERVAL,
    rapid_click_delay,
    rapid_reenter_count,
    ENTRY_CONTROL_GRACE_SECONDS,
    ENTRY_CONTROL_GRACE_TICKS,
    VERIFY_TIMEOUT_SECONDS,
    RAPID_REENTER_MAX_ROUNDS,
    SOLD_OUT_TEXTS,
    SALE_TIME_REGEX,
    BUTTON_TIME_EXACT_REGEX,
    BUTTON_COLOR_BUY_R_MIN,
    BUTTON_COLOR_BUY_G_MIN,
    BUTTON_COLOR_BUY_B_MAX,
    BUTTON_COLOR_BUY_RB_MIN,
    BUTTON_COLOR_GRAY_SPREAD_MAX,
    BUTTON_COLOR_GRAY_MIN,
    BUTTON_COLOR_GRAY_MAX,
    BUTTON_COLOR_CACHE_SECONDS,
    BUTTON_GRAY_REENTER_SECONDS,
    REENTER_GRACE_SECONDS,
    REENTER_MIN_INTERVAL,
    DETAIL_ENTER_TIMEOUT,
    DETAIL_ENTER_POLL,
    STABLE_READ_COUNT,
    STUCK_RECOVER_SECONDS,
    WAIT_HEARTBEAT,
    TAP_JITTER_PX,
    IGOU_TAB_TEXT,
    IGOU_TAB_REGION_PX,
    JINGDIAN_TAB_TEXT,
    JINGDIAN_TAB_REGION_PX,
    YEAR_TARGET_TEXT,
    DETAIL_DEFAULT_YEAR,
    YEAR_CELL_REGION_PX,
    QTY_TARGET,
    QTY_VALUE_REGION_PX,
    QTY_PLUS_CENTER_PX,
    QTY_REGEX,
    QTY_MAX_TAPS,
    RUNTIME_STALL_RECAL_SECONDS,
    STALL_RECAL_AFTER,
    FREEZE_JUMP_SECONDS,
    FREEZE_JUMP_TRIGGERS_RECAL,
    IGNORED_FOREGROUND_PACKAGES,
    NAV_CLICK_COOLDOWN_SECONDS,
    MANUAL_LAUNCH_LEAD_SECONDS,
)

from android_launcher import MOUTAI_PACKAGE

# 状态
IDLE = u"IDLE"                # 等待首次倒计时
NAVIGATE_IGOU = u"NAV"        # 启动后导航：点 i购 → 点经典
ENTER_PRODUCT = u"ENTER"      # 列表查找商品并点击进入
WAIT_DETAIL = u"DETAIL"       # 已点商品，等详情页渲染（「数量」出现）
SELECT_YEAR = u"YEAR"         # 详情页先识别并点击年份（规格）
SELECT_QTY = u"QTY"           # 再把数量改为目标瓶数（6）
READ_DETAIL = u"READ"         # 数量确认后识别抢购按钮
RAPID_BUY = u"RAPID"          # 立即抢购后按 0.00~0.99 秒间隔连点
WAIT_VERIFY = u"VERIFY"       # 安全组件验证弹窗：只等待，不点击
WAIT_TIME = u"WAIT"           # 列表等待开售整点
DONE = u"DONE"                # 结束（售罄）或中止（异常）


class FlowCore(object):
    """循环申购状态机"""

    def __init__(self, bridge, logger=None):
        """初始化 FlowCore 实例。"""
        self.bridge = bridge
        self.logger = logger
        # 设备档案（自动校准生成）：运行时以实时节点树为主，
        # 档案 bounds 作为兜底；由主程序武装前注入。
        self.profile = None
        self.first_target = None
        self.session_target = None
        self.display_target = None
        self.recorded_pos = None
        self.state = DONE
        self.status = u""
        self.success = False
        self._heartbeat = 0.0
        self._last_time_hit = None
        self._stable_count = 0
        self._buy_verified = False
        self._soldout_pending = False
        # 节点对不上停滞检测：同一状态累计找不到控件的秒数/次数
        self._stall_seconds = 0.0
        self._stall_count = 0
        self.needs_recalibration = False
        # 连点模式：累计点击次数 + 距离下一次点击还剩的随机间隔
        self._rapid_click_count = 0
        self._rapid_wait_left = 0.0
        # 连点连续点不中按钮的次数（页面已变则回详情重识别）
        self._rapid_misses = 0
        # 安全验证弹窗等待态的轮询计时
        self._verify_elapsed = 0.0
        # 并发提示（人数过多 Toast）：出现次数 + 上次记日志时刻
        self._soft_hint_count = 0
        self._soft_hint_logged = None
        # 整点重进计数 / 详情页退回次数（日志与防死循环用）
        self._reenter_count = 0
        self._detail_backs = 0
        # 数量修改：本拍/累计加号点击
        self._qty_taps = 0
        # 数字读不到时是否已盲点过一次加号
        self._qty_blind_done = False
        # 本次要选择的年份（UI 下拉菜单武装时写入；默认当前年份）
        self.year_target = YEAR_TARGET_TEXT
        # 弹窗确认成功回调（由 main 注入，用于状态上报置 1）
        self.on_popup_success = None
        # 拉起 i茅台 回调（由 main 注入 launch_moutai），
        # 状态机不直接依赖 android_launcher，便于单测
        self.on_launch_app = None
        # 计划拉起时刻（手动=目标-提前量；自启动=立即）
        self.launch_target = None
        # 详情页年份/数量控件等待宽限累计（跨 YEAR/QTY，不被 _goto 清）
        self._entry_wait = 0.0
        # 本轮自动重进的点击阈值 + 已重进轮次（防死循环）
        self._rapid_reenter_limit = 0
        self._rapid_reenter_rounds = 0
        # 整点快速入页：是否已尝试直接点商品、等详情页的计时
        self._slot_fast_done = False
        self._detail_enter_elapsed = 0.0
        self._detail_enter_next = 0.0
        # 重进刷新的最小间隔：下一次允许重进的最早时刻
        self._reenter_next_at = None
        # 按钮取色缓存：颜色状态（buy/gray/None）+ 采样时刻
        self._color_cache = None
        self._color_cache_at = 0.0
        self._color_pending = False
        self._color_state_last = None
        # 灰色按钮已持续秒数（超过阈值退回列表重新进入）
        self._gray_elapsed = 0.0
        # 验证弹窗累计等待（超时后退回列表重新进入）
        self._verify_total = 0.0
        # YEAR/QTY 宽限按实际执行拍数累计（冻结跳时不会一次吃光）
        self._entry_ticks = 0
        # 前台包名缓存（判断"是否还在 i茅台"）与上次拉起时刻
        self._pkg_cache = None
        self._pkg_cache_at = 0.0
        self._last_launch_at = None
        # NAV 点击冷却：上一次点 i购/经典 的时刻
        self._nav_click_at = None
        # 当前状态已持续秒数（3 秒无进展触发本地恢复）
        self._state_elapsed = 0.0

    # ---------------- 日志 ----------------
    def _log(self, message):
        """写一行日志。"""
        if self.logger is not None:
            self.logger.log(message)
        else:
            print(message)

    # ---------------- 档案 bounds 兜底 ----------------
    def _profile_controls(self):
        """当前档案的 controls 字典。"""
        if self.profile is None:
            return {}
        return self.profile.controls or {}

    def _profile_record(self, control_key, sub_key=None):
        """取某控件的档案记录。"""
        controls = self._profile_controls()
        if sub_key is None:
            record = controls.get(control_key)
        else:
            group = controls.get(control_key)
            record = group.get(sub_key) if isinstance(group, dict) else None
        return record if isinstance(record, dict) else None

    def _profile_bounds(self, control_key, sub_key=None):
        """取某控件的档案 bounds。"""
        record = self._profile_record(control_key, sub_key)
        if record is None:
            return None
        bounds = record.get(u"bounds")
        if not bounds or len(bounds) != 4:
            return None
        return tuple(int(v) for v in bounds)

    def _profile_center(self, control_key, sub_key=None):
        """取某控件的档案中心坐标。"""
        record = self._profile_record(control_key, sub_key)
        if record is None:
            return None
        center = record.get(u"center")
        if not center or len(center) != 2:
            return None
        return int(center[0]), int(center[1])

    def _region(self, control_key, legacy_region, sub_key=None):
        """
        实时节点树查询区域：档案 bounds 优先（非 OPPO 机型），
        无档案或字段缺失时退回固定 px 区域。
        区域内扫描的仍是实时节点，不是静态截图。
        """
        return self._profile_bounds(control_key, sub_key) or legacy_region

    def _button_region(self):
        """按钮识别区（档案优先，无档案用固定 px）。"""
        return self._region(u"action_button", BUTTON_REGION_PX)

    def _button_time_hits(self):
        """
        读按钮上的投放时间，返回 ["09:00"] 这样的列表。

        干扰（实拍确认）：按钮上方有一段整段说明文字
        「每日09:00、20:00投放」，其中 "20:00投放" 会被前瞻正则
        SALE_TIME_REGEX 命中，若按"区域包含"扫描就会把 20:00 误当成
        按钮时间，导致后续等错场次。

        处理：
        1) 优先整段精确匹配（Java findExactRegexTexts + 捕获分组）：
           只有按钮那种整段 "09:00投放" 会命中，说明段落不会；
        2) 旧 APK 没有该方法（返回 None）才退回按钮区域扫描
           （区域本身已收窄，且不再做兜底拼接）。
        """
        exact = getattr(self.bridge, "find_exact_regex_texts", None)
        if callable(exact):
            try:
                hits = exact(BUTTON_TIME_EXACT_REGEX)
            except Exception:
                hits = None
            if hits is not None:
                # [] 表示"页面确实没有按钮时间"，不能再退回区域扫描，
                # 否则会读到说明文字里的 20:00
                return [h for h in hits if h]
        return self.bridge.find_regex_in_px_region(
            SALE_TIME_REGEX, self._button_region()
        )

    # ---------------- 按钮颜色状态（不看上下位置） ----------------
    def _button_center(self):
        """按钮中心（档案优先，无档案用 OPPO 固定按钮区中心）"""
        center = self._profile_center(u"action_button")
        if center is not None:
            return center
        left, top, right, bottom = BUTTON_REGION_PX
        return (left + right) // 2, (top + bottom) // 2

    def _button_sample_region(self):
        """
        取色区域：按钮内部左侧竖带（避开中间文字笔画与圆角边框）。
        不同品牌宽高不同，但都来自档案里这颗按钮的 bounds，
        因此与"按钮在说明文字上方还是下方"无关。
        """
        bounds = self._profile_bounds(u"action_button") or BUTTON_REGION_PX
        left, top, right, bottom = [int(v) for v in bounds]
        width = max(1, right - left)
        height = max(1, bottom - top)
        x1 = left + max(6, int(width * 0.06))
        x2 = left + max(12, int(width * 0.20))
        y1 = top + int(height * 0.25)
        y2 = top + int(height * 0.75)
        if x2 <= x1 or y2 <= y1:
            return None
        return (x1, y1, x2, y2)

    def _sample_button_rgb(self):
        """
        非阻塞取色（H4）：缓存命中直接返回；缓存过期则起后台线程采样，
        本拍返回 None——第一击按文字立即点，不被截图拖慢。
        截图只发生在后台线程里，最多等 800ms。
        """
        now = time.monotonic()
        if self._color_cache_at \
                and now - self._color_cache_at < BUTTON_COLOR_CACHE_SECONDS:
            return self._color_cache
        if not self._color_pending:
            self._color_pending = True
            threading.Thread(
                target=self._sample_button_rgb_bg, daemon=True
            ).start()
        return None

    def _sample_button_rgb_bg(self):
        """后台取色线程：采样完写入缓存，不阻塞点击路径。"""
        try:
            sampler = getattr(
                self.bridge, "average_color_in_px_region", None
            )
            region = self._button_sample_region()
            if callable(sampler) and region is not None:
                self._color_cache = sampler(region)
                self._color_cache_at = time.monotonic()
        except Exception:
            pass
        finally:
            self._color_pending = False

    @staticmethod
    def _classify_button_color(rgb):
        """
        按钮填充色 → buy / gray / None（未知）。
        灰：已售罄 / xx:xx投放 / xx:xx备货中 —— 不可点；
        黄橙：立即抢购 —— 可点。
        """
        if rgb is None:
            return None
        red, green, blue = rgb
        if red >= BUTTON_COLOR_BUY_R_MIN \
                and green >= BUTTON_COLOR_BUY_G_MIN \
                and blue <= BUTTON_COLOR_BUY_B_MAX \
                and (red - blue) >= BUTTON_COLOR_BUY_RB_MIN:
            return u"buy"
        if max(rgb) - min(rgb) <= BUTTON_COLOR_GRAY_SPREAD_MAX \
                and BUTTON_COLOR_GRAY_MIN <= red <= BUTTON_COLOR_GRAY_MAX:
            return u"gray"
        return None

    def _button_color_state(self):
        """
        按钮颜色状态（buy/gray/None）；取色是异步的，
        本拍没有缓存时返回 None，调用方按文字立即点击。
        """
        rgb = self._sample_button_rgb()
        state = self._classify_button_color(rgb)
        if state != self._color_state_last:
            self._color_state_last = state
            if rgb is not None:
                self._log(
                    u"按钮取色 RGB=(%d,%d,%d) → %s"
                    % (rgb[0], rgb[1], rgb[2],
                       {u"buy": u"黄/橙，可点",
                        u"gray": u"灰，不可点",
                        None: u"未知，按文字判断"}[state])
                )
        return state

    def _tick_stall(self, dt):
        """
        停滞计数（当前所有调用点已停用，函数保留可单测）。

        多轮次实拍：i茅台 从后台拉回要 10~18 秒加载，这期间页面认不出，
        停滞计数会在"加载中"误判"节点对不上"触发重校，重校又冷启动，
        恶性循环。结论：加载中一律动态等待（等同首轮行为），不再重校；
        各状态的本地恢复（_stuck_recover/限频拉起）继续兜底。
        """
        if dt > FREEZE_JUMP_SECONDS:
            if FREEZE_JUMP_TRIGGERS_RECAL:
                jumps = int(dt / RUNTIME_STALL_RECAL_SECONDS)
                jumps = min(max(1, jumps), STALL_RECAL_AFTER)
                self._stall_count += jumps
                self._log(
                    u"检测到 %.1f 秒跳时，按 %d 次停滞计"
                    % (dt, jumps)
                )
                if self._stall_count >= STALL_RECAL_AFTER:
                    self.needs_recalibration = True
                    self._log(
                        u"跳时后立即重新校准（累计 %d 次）"
                        % self._stall_count
                    )
            else:
                self._stall_seconds = 0.0
                self._stall_count = 0
                self._log(
                    u"检测到 %.1f 秒跳时（疑似冻结），"
                    u"不计入停滞，恢复后重新判定" % dt
                )
            return
        self._stall_seconds += dt
        if self._stall_seconds < RUNTIME_STALL_RECAL_SECONDS:
            return
        self._stall_count += 1
        self._stall_seconds = 0.0
        if self._stall_count < STALL_RECAL_AFTER:
            return
        self.needs_recalibration = True
        self._log(
            u"连续 %d 次 1 秒未推进，判定节点对不上，请求重新校准"
            % self._stall_count
        )

    def _stuck_recover(self, next_state, do_back=True):
        """
        当前状态 3 秒没有推进 → 本地恢复（不等重校）。
        默认 back 回列表再重进；next_state 由调用方指定。
        """
        if self._state_elapsed < STUCK_RECOVER_SECONDS:
            return False
        self._log(
            u"%.1f 秒没有进展（state=%s），执行本地恢复"
            % (self._state_elapsed, self.state)
        )
        if do_back:
            self.bridge.back()
        self._goto(next_state, u"超时无进展，重新进入…")
        return True

    # ---------------- 前台应用判定（桌面/其他 APP 恢复） ----------------
    def _foreground_package(self):
        """前台包名（缓存 0.5 秒，避免每拍都调 JNI）"""
        now = time.monotonic()
        if self._pkg_cache_at and now - self._pkg_cache_at < 0.5:
            return self._pkg_cache
        getter = getattr(self.bridge, "current_package", None)
        if not callable(getter):
            return None
        try:
            package = getter()
        except Exception:
            package = None
        self._pkg_cache = package
        self._pkg_cache_at = now
        return package

    def _ensure_moutai(self, now):
        """
        当前在手机桌面（如误触 Home）或其它 APP 时，把 i茅台 拉回前台。

        防误判（H1）：
        - 白名单包名（自己的进程/systemui/android）一律视为还在 i茅台；
        - RAPID 已点中过按钮（点击落在 i茅台）时不再拉回，防止把
          购买中的页面切走。
        1.5 秒内只拉一次；取不到包名（旧 APK）返回 False，交回文字判断。
        """
        package = self._foreground_package()
        if not package or package == MOUTAI_PACKAGE:
            return False
        if package in IGNORED_FOREGROUND_PACKAGES:
            return False
        if self.state == RAPID_BUY and self._rapid_click_count > 0:
            return False
        last = self._last_launch_at
        if last is not None and (now - last).total_seconds() < 1.5:
            return False
        self._last_launch_at = now
        self._log(u"当前不在 i茅台（前台 %s），拉起 i茅台" % package)
        if callable(self.on_launch_app):
            self.on_launch_app()
        self.status = u"等待 i茅台 回到前台…"
        return True

    # ---------------- 生命周期 ----------------
    def reset(self, first_target, launch_target=None):
        """武装流程。

        first_target：开售整点（倒计时与抢购以此为准）；
        launch_target：拉起 i茅台 的时刻；不传则按
        MANUAL_LAUNCH_LEAD_SECONDS 在开售前提前拉起（手动定时），
        自启动可显式传入立即拉起的时刻。
        """
        self.first_target = first_target
        if launch_target is None:
            launch_target = first_target - timedelta(
                seconds=MANUAL_LAUNCH_LEAD_SECONDS
            )
        self.launch_target = launch_target
        self.session_target = None
        # 倒计时始终指向开售整点，IDLE 等待期即显示正确剩余时间
        self.display_target = first_target
        self.recorded_pos = None
        self.state = IDLE
        self.status = u"等待启动时刻…"
        self.success = False
        self._heartbeat = 0.0
        self._last_time_hit = None
        self._stable_count = 0
        self._buy_verified = False
        self._soldout_pending = False
        self._stall_seconds = 0.0
        self._stall_count = 0
        self.needs_recalibration = False
        self._rapid_click_count = 0
        self._rapid_wait_left = 0.0
        self._rapid_misses = 0
        self._verify_elapsed = 0.0
        self._soft_hint_count = 0
        self._soft_hint_logged = None
        self._reenter_count = 0
        self._detail_backs = 0
        self._qty_taps = 0
        self._qty_blind_done = False
        self._entry_wait = 0.0
        self._rapid_reenter_limit = 0
        self._rapid_reenter_rounds = 0
        self._slot_fast_done = False
        self._detail_enter_elapsed = 0.0
        self._detail_enter_next = 0.0
        self._reenter_next_at = None
        self._color_cache = None
        self._color_cache_at = 0.0
        self._color_pending = False
        self._color_state_last = None
        self._gray_elapsed = 0.0
        self._verify_total = 0.0
        self._entry_ticks = 0
        self._pkg_cache = None
        self._pkg_cache_at = 0.0
        self._last_launch_at = None
        self._nav_click_at = None
        self._state_elapsed = 0.0
        self._log(
            u"已设置定时，开售时刻 %s，计划拉起时刻 %s"
            % (
                first_target.strftime(u"%Y-%m-%d %H:%M:%S"),
                launch_target.strftime(u"%H:%M:%S"),
            )
        )

    @property
    def is_done(self):
        """流程是否已结束。"""
        return self.state == DONE

    def _finish(self, success, message):
        """结束流程（成功/售罄/异常统一入口）。"""
        self.success = success
        self.state = DONE
        # 复盘用：本场被并发提示挡了多少次
        if self._soft_hint_count:
            message = u"%s（本场出现人数过多提示 %d 次）" % (
                message, self._soft_hint_count
            )
        self.status = message
        self._log(u"流程结束：%s" % message)

    # ---------------- 主循环 ----------------
    def update(self, dt, now):
        """
        推进状态机一帧。

        计时体系（L1 说明，按"谁先到谁先动"分层）：
        1. _state_elapsed（3 秒）→ _stuck_recover 本地恢复（back/回 NAV）；
        2. _entry_ticks（150 拍 ≈ 3 秒）→ YEAR/QTY 宽限跳过；
        3. _stall_seconds/_stall_count（1 秒 × STALL_RECAL_AFTER 次）
           → 最后兜底：重新校准。
        三层互不重置对方的计数，跳时（dt>2s）只清零停滞计数。
        """
        self._state_elapsed += dt
        # 手机桌面/其他 APP（如误触 Home、切到微信）→ 先把 i茅台 拉回前台。
        # 用前台包名判断，比在桌面图标里找 i购/经典 可靠；
        # IDLE 未到点、VERIFY 人工处理时不打扰用户。
        # 注意：这里只"顺手拉起"，不 return——前台包名在部分 ROM 上
        # 可能取到别的窗口（自己的进程/桌面），一旦误判就会把流程
        # 卡在"反复拉起"里。拉完之后继续跑当前状态，页面节点能认
        # 就正常走，认不出再靠 3 秒本地恢复。
        if self.state in (
            NAVIGATE_IGOU, ENTER_PRODUCT, WAIT_DETAIL,
            SELECT_YEAR, SELECT_QTY, READ_DETAIL, RAPID_BUY,
        ) or (self.state == WAIT_TIME and now >= self.session_target):
            self._ensure_moutai(now)

        if self.state == IDLE:
            self._update_idle(now)
        elif self.state == NAVIGATE_IGOU:
            self._update_navigate(dt, now)
        elif self.state == ENTER_PRODUCT:
            self._update_enter_product(dt, now)
        elif self.state == WAIT_DETAIL:
            self._update_wait_detail(dt, now)
        elif self.state == SELECT_YEAR:
            self._update_select_year(dt, now)
        elif self.state == SELECT_QTY:
            self._update_select_qty(dt, now)
        elif self.state == READ_DETAIL:
            self._update_read_detail(dt, now)
        elif self.state == RAPID_BUY:
            self._update_rapid_buy(dt, now)
        elif self.state == WAIT_VERIFY:
            self._update_wait_verify(dt, now)
        elif self.state == WAIT_TIME:
            self._update_wait_time(dt, now)

    def _goto(self, state, status):
        """切换状态并重置计时器"""
        self.state = state
        self.status = status
        self._state_elapsed = 0.0
        self._heartbeat = 0.0
        self._last_time_hit = None
        self._stable_count = 0
        # 注意：_buy_verified 表示"这一场已上报成功"，只在 reset()
        # 里清；READ↔RAPID 往返不能清，否则会重复上报扣次。
        self._rapid_click_count = 0
        self._rapid_wait_left = 0.0
        self._rapid_misses = 0
        self._verify_elapsed = 0.0
        self._qty_taps = 0
        if state == SELECT_QTY:
            self._qty_blind_done = False
        self._stall_seconds = 0.0
        self._stall_count = 0
        # 年份、数量各自独立计时 3 秒宽限：年份加载慢不能把数量的
        # 宽限一起吃掉，否则会跳过"改 6 瓶"。
        if state in (SELECT_YEAR, SELECT_QTY, READ_DETAIL):
            self._entry_wait = 0.0
            self._entry_ticks = 0
        if state == WAIT_VERIFY:
            self._verify_total = 0.0
        # 整点快速入页/等详情页：进入新状态时重新计时
        self._slot_fast_done = False
        self._detail_enter_elapsed = 0.0
        self._detail_enter_next = 0.0
        # 注意：_reenter_next_at 不在此重置——重进间隔由 _handle_sale_time
        # 在 _goto 之后设置，跨 WAIT 保留才有意义。
        # 注意：_soldout_pending 不在此重置，售罄复核要跨 ENTER→READ 保留

    def _heartbeat_log(self, dt, message):
        """等待期间按 WAIT_HEARTBEAT 周期记录心跳（附当前页面判定）"""
        self._heartbeat += dt
        if self._heartbeat >= WAIT_HEARTBEAT:
            try:
                page = self._current_page()
            except Exception:
                page = u"?"
            self._log(u"%s（当前页面判定：%s）" % (message, page))
            self._heartbeat = 0.0

    def _product_center(self):
        """整页按完整商品名取中心（兼容全角/半角括号），取不到返回 None"""
        for name in PRODUCT_FULL_TEXTS:
            center = self.bridge.node_center((name,))
            if center is not None:
                return center
        return None

    def _list_ready(self):
        """
        确认当前确实在目标商品列表页，返回商品节点中心，否则 None。
        识别顺序（越靠前越精准）：
        1) 档案 product_card 区域 + 完整商品名：只认校准过的卡位和
           全称，页面别处的「飞天」文字不会干扰；
        2) 整页完整商品名 + 列表标签（全部/经典/精品）：无档案时兜底；
        3) 都没有 → None（不点，等待）。
        「鼓乐飞天」等其它商品同样含「飞天」「%vol」，所以不再用
        两个关键词做商品判定。
        """
        region = self._profile_bounds(u"product_card")
        if region is not None:
            for name in PRODUCT_FULL_TEXTS:
                if self.bridge.text_exists_in_px_region(name, region):
                    center = self._profile_center(u"product_card")
                    if center is not None:
                        return center
        center = self._product_center()
        if center is None:
            return None
        for marker in LIST_MARKER_TEXTS:
            if self.bridge.text_exists(marker):
                return center
        return None

    def _click_product(self):
        """
        点目标商品进详情：档案卡位区域 + 完整名称优先，失败再按全称
        节点点击。
        这里**不做**「飞天」+「%vol」关键词兜底——那会点中
        「鼓乐飞天」等同样含这两个词的其它商品。点不到就返回 False，
        由调用方留在列表页重试。
        """
        region = self._profile_bounds(u"product_card")
        if region is not None:
            for name in PRODUCT_FULL_TEXTS:
                try:
                    if self.bridge.click_text_in_px_region(name, region):
                        return True
                except Exception:
                    pass
        for name in PRODUCT_FULL_TEXTS:
            try:
                if self.bridge.click_text(name):
                    return True
            except Exception:
                pass
        return False

    def _tap_buy(self):
        """
        点「立即抢购/立即购买」：按钮区（档案 action_button）内优先，
        失败退回全页节点点击。返回点中的文字，未点中返回 None。
        """
        region = self._button_region()
        for text in BUY_NOW_TEXTS:
            try:
                if self.bridge.click_text_in_px_region(text, region):
                    return text
            except Exception:
                pass
        for text in BUY_NOW_TEXTS:
            try:
                if self.bridge.click_text(text):
                    return text
            except Exception:
                pass
        return None

    def _tap_plus(self, px, py, count):
        """
        点数量加号 count 次：新 APK 用一次手势派发多点（少 count-1 次
        跨语言往返）；旧 APK/测试桩没有该方法时退回逐个 tap_px。
        单次手势最多 8 个 stroke（Android 上限 10），多出的分批发。
        返回实际点击次数。
        """
        count = int(count)
        if count <= 0:
            return 0
        multi = getattr(self.bridge, "tap_multi_px", None)
        done = 0
        remaining = count
        while remaining > 0:
            chunk = min(remaining, 8)
            used_multi = False
            if callable(multi):
                try:
                    if multi(px, py, chunk, TAP_JITTER_PX):
                        done += chunk
                        remaining -= chunk
                        used_multi = True
                except Exception:
                    multi = None
            if used_multi:
                continue
            for _ in range(chunk):
                try:
                    self.bridge.tap_px(px, py, TAP_JITTER_PX)
                    done += 1
                except Exception:
                    return done
            remaining -= chunk
        return done

    def _any_text(self, texts):
        """
        页面上是否存在给定文字中的任意一个。
        优先用桥接的合并遍历（anyTextExists，一次全树扫描）；
        电脑端/旧 APK 没有该能力时退回逐个 text_exists。
        """
        merged = getattr(self.bridge, "any_text_exists", None)
        if callable(merged):
            try:
                return bool(merged(texts))
            except Exception:
                pass
        for text in texts:
            try:
                if self.bridge.text_exists(text):
                    return True
            except Exception:
                pass
        return False

    def _verify_popup_visible(self):
        """安全组件（填字/点选）验证弹窗是否出现"""
        return self._any_text(VERIFY_POPUP_TEXTS)

    def _order_page_visible(self):
        """界面是否已刷新成订单/支付页（点击被受理的成功证据）"""
        return self._any_text(ORDER_PAGE_TEXTS)

    def _soft_hint_visible(self):
        """是否出现「人数过多」这类并发 Toast（不停止点击，只统计）"""
        return self._any_text(SOFT_HINT_TEXTS)

    def _back_to_list(self, rounds=3):
        """
        用系统 back 退回「经典列表」，并处理 back 退多了的情况：
          detail → 系统 back；
          home   → 点 i购，再点经典；
          igou   → 点经典；
          unknown（桌面/加载中）→ 拉起 i茅台 后再判。
        每一轮都用 _current_page 重新判定，不假设退到了哪。
        返回 True 表示当前确实在列表。
        """
        for _ in range(rounds):
            page = self._current_page()
            if page == u"list":
                return True
            if page == u"detail":
                self.bridge.back()
                time.sleep(0.15)
                continue
            if page == u"igou":
                region = self._region(
                    u"jingdian_tab", JINGDIAN_TAB_REGION_PX
                )
                if not self.bridge.click_text_in_px_region(
                        JINGDIAN_TAB_TEXT, region):
                    self.bridge.click_text(JINGDIAN_TAB_TEXT)
                time.sleep(0.2)
                continue
            if page == u"home":
                region = self._region(u"igou_tab", IGOU_TAB_REGION_PX)
                if not self.bridge.click_text_in_px_region(
                        IGOU_TAB_TEXT, region):
                    self.bridge.click_text(IGOU_TAB_TEXT)
                time.sleep(0.2)
                continue
            # unknown：桌面/其他 APP/加载中，拉起 i茅台 后再判
            if callable(self.on_launch_app):
                self.on_launch_app()
            time.sleep(0.2)
        page = self._current_page()
        if page != u"list":
            self._log(
                u"未能回到列表（当前 %s），到点重进时再接入" % page
            )
        return page == u"list"

    def _handle_sale_time(self, hhmm, now):
        """
        读到按钮区开售时间后的统一处理（READ 和 YEAR 预检共用）：
        - 未来时间：替换当前目标，回列表等到点再精确重进；
        - 已过但仍在宽限内（默认同一小时）：退回列表立即重进刷新，
          不把本场判成"已过"；
        - 已过且超出宽限：顺延到次日同刻。
        返回 True 表示已处理（调用方直接 return）。
        """
        try:
            hour, minute = (int(v) for v in hhmm.split(u":"))
        except ValueError:
            return False
        target = now.replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if target <= now:
            late = (now - target).total_seconds()
            if late <= REENTER_GRACE_SECONDS:
                self._reenter_count += 1
                if self._reenter_count % 5 == 1:
                    self._log(
                        u"读到开售时间 %s（已过 %.1f 秒），按钮未刷新，"
                        u"退出重进第 %d 次"
                        % (hhmm, late, self._reenter_count)
                    )
                if not self._back_to_list():
                    self._log(u"未能回到列表，仍按重进刷新处理")
                # 目标仍是本场整点（已过），WAIT 下一拍立即重进
                self.session_target = target
                self.display_target = target
                self._goto(
                    WAIT_TIME,
                    u"重新进入详情刷新按钮（第 %d 次）…"
                    % self._reenter_count,
                )
                self._reenter_next_at = now + timedelta(
                    seconds=REENTER_MIN_INTERVAL
                )
                return True
            target = target + timedelta(days=1)
            self._log(
                u"读取到开售时间 %s（已过 %.0f 秒），顺延至次日 %s"
                % (hhmm, late, target.strftime(u"%Y-%m-%d %H:%M"))
            )
        else:
            self._reenter_count = 0
            self._log(
                u"读取到开售时间 %s（未来），返回列表，等待整点" % hhmm
            )
        if not self._back_to_list():
            self._log(u"未能回到列表，仍按等待处理（到点重进）")
        self.session_target = target
        self.display_target = target
        self._goto(
            WAIT_TIME,
            u"等待开售 %s" % target.strftime(u"%m-%d %H:%M"),
        )
        return True

    def _text_in_profile_region(self, control_key, text):
        """
        档案里有该控件的独立识别区时，优先在该区域内找文字（读取即可）；
        没有档案/字段缺失/区域没命中都返回 None 或 False，调用方
        一律再全页确认一次——区域只做加速，绝不能因为档案旧了
        就把明明在眼前的页面判成 unknown。
        """
        region = self._profile_bounds(control_key)
        if not region:
            return None
        try:
            return self.bridge.text_exists_in_px_region(text, region)
        except Exception:
            return None

    def _detail_visible(self):
        """详情页判定：优先读档案的「数量」标签区，其次全页找「数量」"""
        if self._text_in_profile_region(u"qty_label", u"数量"):
            return True
        return self.bridge.text_exists(u"数量")

    def _current_page(self):
        """
        任意页面接入：靠通用文字特征判定当前停在 i茅台 的哪个页面，
        全机型通用、不依赖 px。返回 detail/list/igou/home/unknown。
        有档案时优先在各自独立识别区内判断（读取档案参数），
        但区域未命中时一定退回全页文字确认（兜底）。
        列表页必须认到完整商品名：只认「飞天」+「%vol」会把 i购
        「全部」视图里的「鼓乐飞天」也当成目标商品。
        """
        if self._detail_visible():
            return u"detail"
        has_jd = self._text_in_profile_region(
            u"jingdian_tab", JINGDIAN_TAB_TEXT
        )
        if not has_jd:
            has_jd = self.bridge.text_exists(JINGDIAN_TAB_TEXT)
        if has_jd and self._product_center() is not None:
            return u"list"
        if has_jd:
            return u"igou"
        on_igou_tab = self._text_in_profile_region(
            u"igou_tab", IGOU_TAB_TEXT
        )
        if not on_igou_tab:
            on_igou_tab = self.bridge.text_exists(IGOU_TAB_TEXT)
        if on_igou_tab:
            return u"home"
        return u"unknown"

    def _recover_if_left_detail(self):
        """
        误触离开详情页（首页/π社区/小茅运/我的 任意 tab，或 i购页）时，
        立刻回 NAV 按 点 i购 → 点经典 → 点商品 的顺序重新进入。
        返回 True 表示已切换状态。
        """
        page = self._current_page()
        if page in (u"home", u"igou"):
            self._log(
                u"已离开详情页（当前在 %s），重新点击 i购/经典 进入"
                % page
            )
            self._goto(NAVIGATE_IGOU, u"误触离开详情，重新导航…")
            return True
        if page == u"list":
            self._log(u"已回到商品列表（可能是误触返回），重新点击商品")
            self._goto(ENTER_PRODUCT, u"回到列表，重新点击商品…")
            return True
        return False

    # ---------------- IDLE ----------------
    def _update_idle(self, now):
        """后台静默等待；到计划拉起时刻才拉起 i茅台并进入页面接入。"""
        if now < self.launch_target:
            self.status = u"等待拉起时刻 %s…" \
                % self.launch_target.strftime(u"%H:%M:%S")
            return
        # 到点：保证 i茅台 在前台（幂等，已在前台无副作用）
        self._log(u"到达拉起时刻，自行启动 i茅台，识别当前页面")
        if callable(self.on_launch_app):
            self.on_launch_app()
        self._goto(NAVIGATE_IGOU, u"已拉起，识别当前页面…")

    # ---------------- NAVIGATE_IGOU ----------------
    def _update_navigate(self, dt, now):
        """
        任意页面接入：先识别当前停在 i茅台 的哪个页面，再从该页面继续，
        不强制回到起点。每步用节点+区域识别点击，固定坐标仅兜底。
          detail → 直接进年份流程；
          list   → 点飞天进详情；
          igou   → 区域内点经典，等列表；
          home   → 区域内点 i购，等 i购；
          unknown→ 加载中，动态等待，限频拉起重试（不再重校）。
        """
        if not self.bridge.is_connected():
            self._finish(
                False,
                u"无障碍服务未开启，请先到设置中开启后重新定时",
            )
            return

        page = self._current_page()

        if page == u"detail":
            self._log(u"识别到当前已在详情页，直接进入年份/数量流程")
            self._goto(SELECT_YEAR, u"已在详情，识别年份规格…")
            return

        if page == u"list":
            center = self._list_ready()
            if center is not None:
                self.recorded_pos = center
                self._log(
                    u"识别到当前在经典列表，点击目标商品进入，位置 (%d, %d)"
                    % center
                )
                if self._click_product():
                    # 点完必须确认真的到了详情页（「数量」出现）：
                    # 没到就 2 秒内回 NAV 重判，而不是直接进年份、
                    # 然后在列表页上空等触发重校。
                    self._goto(WAIT_DETAIL, u"已点商品，等待详情页…")
                    return
                self.status = u"点击目标商品失败，重试…"
                return
            # 判定在列表但未取到中心，下轮重试（加载中不重校）
            self.status = u"列表确认中…"
            return

        if page == u"igou":
            # 点击冷却（M3）：0.3 秒内不重复点同一个 tab，
            # 防止页面过渡慢时 2~3 次/秒连点
            if self._nav_click_at is not None and (
                    now - self._nav_click_at).total_seconds() \
                    < NAV_CLICK_COOLDOWN_SECONDS:
                self.status = u"已点击经典，等待商品列表…"
                return
            self._nav_click_at = now
            jd_region = self._region(
                u"jingdian_tab", JINGDIAN_TAB_REGION_PX
            )
            self._log(u"识别到当前在 i购，区域内点击「经典」")
            if not self.bridge.click_text_in_px_region(
                JINGDIAN_TAB_TEXT, jd_region
            ):
                # 兜底：区域没命中（档案旧/布局变），全页点一次
                self._log(u"「经典」区域点击失败，改全页文字点击")
                self.bridge.click_text(JINGDIAN_TAB_TEXT)
            # 点完验证：还停在 i购 说明点到了不可点的祖先，补一次全页点击
            time.sleep(0.15)
            if self._current_page() == u"igou":
                self._log(u"点击经典后仍停在 i购，补点一次全页文字")
                self.bridge.click_text(JINGDIAN_TAB_TEXT)
            self.status = u"已点击经典，等待商品列表…"
            return

        if page == u"home":
            # 点击冷却（M3）：同上
            if self._nav_click_at is not None and (
                    now - self._nav_click_at).total_seconds() \
                    < NAV_CLICK_COOLDOWN_SECONDS:
                self.status = u"已点击 i购，等待页面加载…"
                return
            self._nav_click_at = now
            igou_region = self._region(
                u"igou_tab", IGOU_TAB_REGION_PX
            )
            self._log(u"识别到当前在首页，区域内点击「i购」")
            if not self.bridge.click_text_in_px_region(
                IGOU_TAB_TEXT, igou_region
            ):
                # 兜底：区域没命中（档案旧/布局变），全页点一次
                self._log(u"「i购」区域点击失败，改全页文字点击")
                self.bridge.click_text(IGOU_TAB_TEXT)
            # 点完验证：还停在首页说明没点进去，补一次全页点击
            time.sleep(0.15)
            if self._current_page() == u"home":
                self._log(u"点击 i购 后仍停在首页，补点一次全页文字")
                self.bridge.click_text(IGOU_TAB_TEXT)
            self.status = u"已点击 i购，等待页面加载…"
            return

        # unknown：冷启动/加载中，动态等待可识别页面出现；
        # 3 秒还认不出（广告页/登录页/卡住）→ 限频拉起 i茅台 重试
        if self._state_elapsed >= STUCK_RECOVER_SECONDS:
            self._state_elapsed = 0.0
            self._log(u"3 秒未识别到页面，拉起 i茅台 重试")
            if callable(self.on_launch_app):
                self.on_launch_app()
        self._heartbeat_log(
            dt, u"等待 i茅台加载可识别页面（首页/i购/列表/详情）…"
        )
        self.status = u"等待 i茅台页面加载…"


    # ---------------- ENTER_PRODUCT ----------------
    def _update_enter_product(self, dt, now):
        """列表查找商品：商品节点+列表标签双确认才进入（弹窗期有限等待）"""
        if not self.bridge.is_connected():
            self._finish(
                False,
                u"无障碍服务未开启，请先到设置中开启后重新定时",
            )
            return

        # 3 秒还点不进商品（列表未确认/点击失败）→ 回 NAV 重新识别
        if self._stuck_recover(NAVIGATE_IGOU, do_back=False):
            return

        center = self._list_ready()
        if center is not None:
            self.recorded_pos = center
            self._log(
                u"列表确认（完整商品名+列表标签），点击商品进入，"
                u"位置 (%d, %d)" % center
            )
            if self._click_product():
                self._goto(WAIT_DETAIL, u"已点商品，等待详情页…")
                return
            self.status = u"点击目标商品失败，重试…"
            return

        # 未确认在列表：可能弹窗未消失或停在详情页，动态等待（不重校）
        self._heartbeat_log(
            dt, u"未确认在商品列表（弹窗/详情页），继续等待…"
        )
        self.status = u"等待商品列表页…"

    # ---------------- SELECT_YEAR ----------------
    def _update_select_year(self, dt, now):
        """
        进入详情页后第一步：先读按钮区（1 次调用）判断这一页能不能买。
        - 按钮还是「HH:MM投放」→ 不浪费时间选年份/数量，直接退回等待
          （重进刷新按钮，READ 不会再被这些无效页面拖慢）；
        - 按钮是「立即抢购」→ 选年份 → 数量 → 点抢购。
        年份区未渲染就动态等待；页面改版时按钮已渲染且等满宽限才放行。
        """
        if not self.bridge.is_connected():
            self._finish(
                False,
                u"无障碍服务未开启，请先到设置中开启后重新定时",
            )
            return

        # 0) 预检按钮区：仍是投放时间就直接退回，不选年份/数量
        hits = self._button_time_hits()
        if hits:
            self._log(
                u"详情页按钮仍为 %s，不选年份/数量，直接退回等待"
                % hits[0]
            )
            self._handle_sale_time(hits[0], now)
            return

        year = self.year_target or YEAR_TARGET_TEXT
        # 详情页每次进入默认已选 DETAIL_DEFAULT_YEAR（实拍 2024）：
        # UI 选的也是它就不点年份，直接进数量；选其它年份才点对应格。
        if year == DETAIL_DEFAULT_YEAR:
            self._log(
                u"详情页默认已是 %s，无需点击年份" % year
            )
            self._goto(SELECT_QTY, u"年份默认%s，修改数量…" % year)
            return
        # UI 选了未知年份时退回默认年份的识别框；
        # 档案年份格 bounds 优先，无档案退回固定 px
        legacy_region = YEAR_CELL_REGION_PX.get(
            year, YEAR_CELL_REGION_PX[YEAR_TARGET_TEXT]
        )
        region = self._region(u"year_cells", legacy_region, sub_key=year)

        # 1) 直接点该年份格：成功即进入数量修改（省掉一次存在性查询）
        if self.bridge.click_text_in_px_region(year, region):
            self._log(
                u"详情页识别到年份规格「%s」，点击选择年份" % year
            )
            self._goto(SELECT_QTY, u"已选择年份%s，修改数量…" % year)
            return

        # 2) 兜底：年份区域缺失但抢购按钮已渲染，
        #    仍尝试数量修改（数量状态有自己的兜底），再识别按钮
        button_region = self._button_region()
        button_ready = bool(self._button_time_hits())
        for texts in (BUY_NOW_TEXTS, SOLD_OUT_TEXTS):
            for t in texts:
                if self.bridge.text_exists_in_px_region(
                    t, button_region
                ):
                    button_ready = True
                    break
        # 2) 兜底：按钮已渲染且实际执行满宽限拍数（页面确实改版），
        #    才放行；宽限内即使按钮先出现也坚持等年份，防止跳过
        if button_ready and self._entry_ticks >= ENTRY_CONTROL_GRACE_TICKS:
            self._log(
                u"等待 %d 拍（约 %.1f 秒）仍无年份规格区域，按钮已出现，"
                u"跳过年份尝试数量修改"
                % (self._entry_ticks, self._entry_wait)
            )
            self._goto(SELECT_QTY, u"跳过年份，修改数量…")
            return

        # 3) 详情页加载中（含按钮先渲染但宽限未到）：动态等待
        self._entry_wait += dt
        self._entry_ticks += 1
        if self._entry_ticks % 50 == 0 and self._recover_if_left_detail():
            return
        if self._stuck_recover(ENTER_PRODUCT):
            return
        self._heartbeat_log(
            dt,
            u"等待详情页年份规格区域渲染（年份「%s」）…" % year,
        )
        self.status = u"等待详情页年份规格区域…"

    # ---------------- SELECT_QTY ----------------
    def _button_ready(self):
        """抢购按钮区是否已出现可识别内容（时间/立即抢购/售罄）"""
        if self._button_time_hits():
            return True
        region = self._button_region()
        for texts in (BUY_NOW_TEXTS, SOLD_OUT_TEXTS):
            for t in texts:
                if self.bridge.text_exists_in_px_region(t, region):
                    return True
        return False

    def _update_select_qty(self, dt, now):
        """
        年份确认后修改数量：读数量数字框（默认 2 瓶），点加号改为
        目标数量 QTY_TARGET（6 瓶）。
        - 读到 N<6：同一拍内连点 (6-N) 次加号（固定坐标，带抖动），
          下一拍复核数字；仍没到目标继续补点，累计上限 QTY_MAX_TAPS；
        - 读到 N>=6：放行到按钮识别；
        - 读不到数量（页面改版）：按钮已渲染就放行，否则动态等待。
        """
        if not self.bridge.is_connected():
            self._finish(
                False,
                u"无障碍服务未开启，请先到设置中开启后重新定时",
            )
            return

        value_region = self._region(
            u"qty_value", QTY_VALUE_REGION_PX
        )
        hits = self.bridge.find_regex_in_px_region(
            QTY_REGEX, value_region
        )
        # 兜底：档案数量区没读到数字时，用「数量」标签同一行的右侧带
        # 再读一次（防止旧档案的 qty_value 区域偏了）
        if not hits:
            label = self._profile_bounds(u"qty_label")
            if label and len(label) == 4:
                band = (label[2], label[1] - 10, 100000, label[3] + 10)
                hits = self.bridge.find_regex_in_px_region(
                    QTY_REGEX, band
                )
        value = None
        if hits:
            try:
                value = int(hits[0])
            except (ValueError, TypeError):
                value = None

        if value is not None:
            if value >= QTY_TARGET:
                self._log(
                    u"数量已为 %d 瓶，开始识别抢购按钮" % value
                )
                self._goto(READ_DETAIL, u"数量%d瓶，识别抢购按钮…" % value)
                return
            need = QTY_TARGET - value
            if self._qty_taps >= QTY_MAX_TAPS:
                self._log(
                    u"数量加号点击已达 %d 次上限（当前 %d 瓶），"
                    u"跳过数量直接识别按钮"
                    % (QTY_MAX_TAPS, value)
                )
                self._goto(READ_DETAIL, u"数量修改异常，识别抢购按钮…")
                return
            # 同一拍内连续点完需要的次数（加号节点无文字）：
            # 档案加号中心优先；没有档案时按"数字框右侧"推算加号，
            # 最后才退回 OPPO 固定中心（换机型时固定 px 不通用）。
            # 一次手势派发多点（新 APK），旧 APK 自动退回逐个点击。
            plus_center = self._profile_center(u"qty_plus")
            if plus_center is None:
                box = self._profile_bounds(u"qty_value") \
                    or QTY_VALUE_REGION_PX
                plus_center = (
                    int(box[2]) + 30,
                    (int(box[1]) + int(box[3])) // 2,
                )
            px, py = plus_center
            need = min(need, QTY_MAX_TAPS - self._qty_taps)
            done = self._tap_plus(px, py, need)
            self._qty_taps += done
            self._log(
                u"当前数量 %d 瓶，连续点击加号 %d 次（累计 %d 次），"
                u"改为 %d 瓶"
                % (value, done, self._qty_taps, QTY_TARGET)
            )
            self.status = u"修改数量 %d→%d…" % (value, QTY_TARGET)
            return

        # 读不到数字但档案里采到了加号区域：盲点 4 次（默认 2→6）
        # 后下一拍复核；只盲点一次，避免把数量加爆。
        plus_center = self._profile_center(u"qty_plus")
        if plus_center is not None and not self._qty_blind_done:
            self._qty_blind_done = True
            self._log(
                u"数量数字读不到，按档案加号盲点 %d 次（默认 2→%d）"
                % (QTY_TARGET - 2, QTY_TARGET)
            )
            self._tap_plus(plus_center[0], plus_center[1], QTY_TARGET - 2)
            self.status = u"数量盲点后复核…"
            return

        # 读不到数量：按钮已渲染且实际执行满宽限拍数（页面改版）才放行；
        # 宽限内坚持等数量控件，保证正常加载时一定改 6 瓶。
        # 用拍数而不是墙钟：后台被冻结时墙钟会跳几十秒，不能因此跳过改数量。
        if self._button_ready() \
                and self._entry_ticks >= ENTRY_CONTROL_GRACE_TICKS:
            self._log(
                u"等待 %d 拍（约 %.1f 秒）仍无数量控件，按钮已出现，"
                u"直接识别按钮" % (self._entry_ticks, self._entry_wait)
            )
            self._goto(READ_DETAIL, u"跳过数量，识别抢购按钮…")
            return
        self._entry_wait += dt
        self._entry_ticks += 1
        if self._entry_ticks % 50 == 0 and self._recover_if_left_detail():
            return
        if self._stuck_recover(ENTER_PRODUCT):
            return
        self._heartbeat_log(
            dt, u"等待详情页数量区域渲染…"
        )
        self.status = u"等待详情页数量区域…"

    # ---------------- READ_DETAIL ----------------
    def _update_read_detail(self, dt, now):
        """
        详情页按钮判定（按颜色 + 文字，不看上下位置）：
        - 灰色按钮（已售罄 / xx:xx投放 / xx:xx备货中）→ 不点；
        - 黄/橙色按钮（立即抢购）→ 点；
        - 取不到颜色（旧 APK/低版本）→ 退回纯文字判断。
        """
        buy_visible = self._any_text(BUY_NOW_TEXTS)
        color = self._button_color_state() if buy_visible else None

        # 1) 可点：按钮文字是立即抢购，且颜色不是灰
        if buy_visible and color != u"gray":
            hit = self._tap_buy()
            if hit is None and color == u"buy":
                center = self._button_center()
                if center is not None:
                    self._log(
                        u"文字未识别但按钮为黄/橙色，按按钮中心兜底点击"
                    )
                    self.bridge.tap_px(
                        center[0], center[1], TAP_JITTER_PX
                    )
                    hit = u"按钮中心"
            if hit is not None:
                self._gray_elapsed = 0.0
                self._log(u"识别到「%s」，立即点击购买" % hit)
                self._soldout_pending = False
                self._goto(
                    RAPID_BUY,
                    u"已点击购买，进入连点模式…",
                )
                # 第一下已在 READ 点出，下一次点击前先等一个
                # 独立随机的 0.00~0.99 秒
                self._rapid_wait_left = rapid_click_delay()
                # 本轮连点达到该随机次数后自动 back 重进刷新
                self._rapid_reenter_limit = rapid_reenter_count()
                self._log(
                    u"本轮自动重进阈值：连点 %d 次后返回上一层重进"
                    % self._rapid_reenter_limit
                )
                return

        # 1b) 文字是立即抢购但按钮还是灰的（禁用态）：不点，等它变黄。
        #     持续灰色超过阈值说明这次加载没刷新，退回列表重新进入。
        if buy_visible and color == u"gray":
            self._gray_elapsed += dt
            if self._gray_elapsed >= BUTTON_GRAY_REENTER_SECONDS:
                self._gray_elapsed = 0.0
                self._log(
                    u"按钮持续灰色 %.1f 秒仍未变黄，退回列表重新进入刷新"
                    % BUTTON_GRAY_REENTER_SECONDS
                )
                self.bridge.back()
                self._goto(WAIT_TIME, u"按钮未变黄，重新进入刷新…")
                return
            self._heartbeat_log(
                dt, u"按钮为灰色（未开售/未刷新），等待变黄…"
            )
            self.status = u"按钮灰色，等待变黄…"
            return

        self._gray_elapsed = 0.0

        # 2) 已售罄：需二次确认——先返回列表重新进入，
        #    再次读到的按钮仍为售罄才结束（防 H5 缓存旧状态误判）
        #    合并一次遍历（L2），不在每个文案上各扫一遍全树
        sold_out = self._any_text(SOLD_OUT_TEXTS)
        if sold_out:
            if self._soldout_pending:
                self._log(
                    u"二次进入确认仍为「已售罄」，返回列表，结束启动器"
                )
                self.bridge.back()
                self._finish(True, u"商品已售罄（二次确认），启动器结束")
                return
            self._soldout_pending = True
            self._log(
                u"首次识别到「已售罄」，返回列表并重新进入复核"
            )
            self.bridge.back()
            self._goto(ENTER_PRODUCT, u"售罄复核，重新进入确认…")
            return

        # 3) 开售时间（整段精确匹配，排除按钮上方的说明文字）
        hits = self._button_time_hits()
        if hits:
            hhmm = hits[0]
            # 动态稳定判断：不设固定等待，连续 N 次读数一致即采信；
            # 期间数值一旦变化立即重新计数
            if hhmm == self._last_time_hit:
                self._stable_count += 1
            else:
                self._last_time_hit = hhmm
                self._stable_count = 1
            if self._stable_count < STABLE_READ_COUNT:
                self.status = u"等待详情页时间稳定…"
                return
            # 读到有效时间，说明未售罄，撤销售罄复核标记
            self._soldout_pending = False
            self._handle_sale_time(hhmm, now)
            return

        # 4) 按钮尚未刷新/弹窗遮挡：不中止、不返回，无限等待，
        #    每 5 秒记心跳；按钮一出现立即处理（识别在 1 秒内）。
        #    但若用户误触离开了详情页（首页/社区/小茅运/我的 任意 tab），
        #    立即回 NAV 点 i购 → 经典 → 商品，而不是在别的页面空等。
        self._entry_ticks += 1
        if self._entry_ticks % 20 == 0 and self._recover_if_left_detail():
            return
        if self._stuck_recover(ENTER_PRODUCT):
            return
        self._heartbeat_log(
            dt,
            u"详情页等待按钮刷新/弹窗消失（不做任何点击）…",
        )
        self.status = u"详情页等待按钮刷新…"

    # ---------------- RAPID_BUY ----------------
    def _update_rapid_buy(self, dt, now):
        """
        抢购连点（严格 0.00~0.99 秒间隔，无轮次、无连击）：
        - 每点一次「立即抢购/立即购买」，就重新随机 0.00~0.99 秒
          （两位数字各自 0-9）再点下一次；
        - 等待期间只做倒计时，不做任何节点扫描，保证间隔不被 JNI
          耗时吃掉；
        - 每次点完立刻判两类界面变化（各一次合并遍历）：
          a) 安全组件（填字/点选）验证弹窗 → 立即停止点击，
             转 WAIT_VERIFY 等待人工验证，期间绝不再点任何按钮；
          b) 界面刷新成订单/支付页 → 抢购成功，上报后结束；
        - 识别到「已售罄」→ 返回列表重新进入二次复核（唯一正常退出）。
        """
        if not self.bridge.is_connected():
            self._finish(
                False, u"无障碍服务未开启，请先到设置中开启后重新定时"
            )
            return

        # 1) 还没到下一次点击时刻：纯等待，不扫描
        if self._rapid_wait_left > 0.0:
            self._rapid_wait_left -= dt
            if self._rapid_wait_left > 0.0:
                self.status = (
                    u"连点等待中（已点 %d 次，剩 %.2f 秒）…"
                    % (self._rapid_click_count,
                       max(0.0, self._rapid_wait_left))
                )
                return

        # 3) 点一次（按钮区优先，失败退回全页节点点击）
        hit = self._tap_buy()
        clicked = hit is not None

        # 3b) 售罄检查：点不中时必查（按钮文字消失）；点位正常时
        #     每 5 次点击才查一次，且合并一次遍历（L2）。
        if not clicked or self._rapid_click_count % 5 == 0:
            if self._any_text(SOLD_OUT_TEXTS):
                self._soldout_pending = True
                self._log(
                    u"识别到「已售罄」，停止连点，"
                    u"返回列表并重新进入复核"
                )
                self.bridge.back()
                self._goto(ENTER_PRODUCT, u"售罄复核，重新进入确认…")
                return

        if clicked:
            self._rapid_click_count += 1
            if self._rapid_click_count == 1:
                self._log(
                    u"连点模式：每点一次后随机等 0.00~0.99 秒"
                    u"（X 各自 0-9）再点下一次，点击「%s」" % hit
                )
            elif self._rapid_click_count % 20 == 0:
                self._log(
                    u"连点中：已点击「立即抢购」%d 次"
                    % self._rapid_click_count
                )

        # 4) 点完立刻判界面变化：订单/支付页 → 成功（只上报不操作）
        if self._order_page_visible():
            self._on_order_page()
            return

        # 5) 安全组件验证弹窗 → 立即停手等待人工验证
        if self._verify_popup_visible():
            self._log(
                u"出现安全组件验证弹窗，立即停止点击，等待人工验证"
            )
            self._verify_elapsed = 0.0
            self._goto(WAIT_VERIFY, u"安全验证弹窗，等待人工处理…")
            return

        # 6) 并发提示（人数过多 Toast）：页面不变，继续点，只统计+节流日志。
        #    每 SOFT_HINT_CHECK_EVERY 次点击才多付一次全树扫描。
        if clicked and self._rapid_click_count % SOFT_HINT_CHECK_EVERY == 0 \
                and self._soft_hint_visible():
            self._soft_hint_count += 1
            last = self._soft_hint_logged
            if last is None or (now - last).total_seconds() \
                    >= SOFT_HINT_LOG_INTERVAL:
                self._soft_hint_logged = now
                self._log(
                    u"出现「人数过多」类提示（第 %d 次），"
                    u"继续按 0.00~0.99 秒间隔点击" % self._soft_hint_count
                )

        # 7) 没点中：连续多次说明页面已变，回详情重新识别
        if not clicked:
            self._rapid_misses += 1
            if self._rapid_misses >= 3:
                self._log(
                    u"连续 %d 次未点到买入按钮，回详情重新识别"
                    % self._rapid_misses
                )
                self._goto(READ_DETAIL, u"重新识别买入按钮…")
                return
        else:
            self._rapid_misses = 0

        # 7.5) 自动重进：成功点击达到随机阈值，back 返回上一层再
        #      重进详情刷新按钮（替代手动返回）。订单页/验证弹窗/
        #      售罄已在前面优先处理，这里只处理"页面无变化"的情况。
        if clicked and self._rapid_reenter_limit > 0 \
                and self._rapid_click_count >= self._rapid_reenter_limit:
            if self._rapid_reenter_rounds < RAPID_REENTER_MAX_ROUNDS:
                self._rapid_reenter_rounds += 1
                self._log(
                    u"已连点 %d 次（阈值 %d），自动返回上一层再重进"
                    u"详情刷新（第 %d 轮）"
                    % (self._rapid_click_count,
                       self._rapid_reenter_limit,
                       self._rapid_reenter_rounds)
                )
                self.bridge.back()
                # 重进后 ENTER→YEAR→QTY（重新改 6 瓶）→READ→RAPID
                self._goto(
                    ENTER_PRODUCT,
                    u"连点达阈值，自动返回重进刷新…",
                )
                return
            self._log(
                u"自动重进已达 %d 轮上限，停止重进继续连点"
                % RAPID_REENTER_MAX_ROUNDS
            )

        # 8) 安排下一次点击的独立随机间隔
        self._rapid_wait_left = rapid_click_delay()
        self.status = (
            u"已点 %d 次，%.2f 秒后点下一次…"
            % (self._rapid_click_count, self._rapid_wait_left)
        )

    def _on_order_page(self):
        """
        界面已刷新成订单/支付页（A 方案）：只上报记录，不做任何点击。
        同一场只上报一次，避免 READ↔RAPID 往返重复扣次。
        """
        if not self._buy_verified:
            self._buy_verified = True
            self._log(
                u"界面已刷新为订单/支付页，判定抢购成功，仅上报不操作"
            )
            if callable(getattr(self, "on_popup_success", None)):
                try:
                    self.on_popup_success()
                except Exception:
                    pass
        self._finish(True, u"已进入订单/支付页，请手动完成支付")

    # ---------------- WAIT_VERIFY ----------------
    def _update_wait_verify(self, dt, now):
        """
        安全组件（填字/点选）验证弹窗等待态：
        - 只观察，绝不点击（人工去完成验证）；
        - 每 VERIFY_POLL_INTERVAL 秒判一次：
          订单/支付页出现 → 上报成功，结束流程；
          验证弹窗消失且回到详情页 → 人工已关闭/完成，继续连点。
        """
        if not self.bridge.is_connected():
            self._finish(
                False, u"无障碍服务未开启，请先到设置中开启后重新定时"
            )
            return

        self._verify_elapsed += dt
        self._verify_total += dt
        if self._verify_elapsed < VERIFY_POLL_INTERVAL:
            self.status = u"等待人工完成安全验证…"
            return
        self._verify_elapsed = 0.0

        # 弹窗长时间无人处理：不能永远停在这里（会挡住后续场次），
        # 超时后退回列表，按本场时间重新进入刷新。
        if self._verify_total >= VERIFY_TIMEOUT_SECONDS:
            self._log(
                u"安全验证弹窗持续 %.0f 秒未处理，退回列表重新进入"
                % self._verify_total
            )
            self._verify_total = 0.0
            self.bridge.back()
            self._goto(WAIT_TIME, u"验证超时，重新进入刷新…")
            return

        if self._order_page_visible():
            self._on_order_page()
            return

        if not self._verify_popup_visible() \
                and self.bridge.text_exists(u"数量"):
            self._log(u"验证弹窗已关闭，回到详情页，继续连点")
            self._rapid_wait_left = 0.0
            self._goto(RAPID_BUY, u"继续连点抢购…")
            return

        self.status = u"等待人工完成安全验证…"

    # ---------------- WAIT_TIME ----------------
    def _update_wait_time(self, dt, now):
        """列表等待开售整点。

        到点先保证 i茅台 在前台（等待期可能被回收/切走），再识别当前
        页面、节点确认进入：detail 直接走年份；list 节点点飞天（固定
        坐标仅兜底）；igou/home 交 NAV 快速接入；unknown 先拉起。
        每轮重新判定，天然重试，不盲目 goto。
        """
        if now < self.session_target:
            self.status = u"等待开售整点 %s…" \
                % self.session_target.strftime(u"%H:%M:%S")
            return

        # 重进节流：两次刷新重进之间至少间隔 REENTER_MIN_INTERVAL
        if self._reenter_next_at is not None:
            if now < self._reenter_next_at:
                self.status = (
                    u"等待重进刷新（还剩 %.1f 秒）…"
                    % (self._reenter_next_at - now).total_seconds()
                )
                return
            self._reenter_next_at = None

        # 整点快速入页：不在详情页时，直接按完整商品名点一次
        # （1~2 次调用），不再做整页扫描；点中后只等「数量」出现。
        # 每个 WAIT 周期只尝试一次，失败再退回下面的页面判定。
        if not self._slot_fast_done:
            self._slot_fast_done = True
            if not self.bridge.text_exists(u"数量") \
                    and self._click_product():
                self._log(
                    u"开售整点到达，直接点击目标商品进入详情"
                    u"（零扫描，跳过页面判定）"
                )
                self._goto(WAIT_DETAIL, u"整点已到，等待详情页…")
                return

        page = self._current_page()
        if page != u"detail":
            self._detail_backs = 0

        if page == u"unknown":
            # 认不出页面（登录页/开屏广告/加载中）：限频拉起，
            # 每 1.5 秒最多一次；加载中等同首轮行为，不触发重校。
            last = self._last_launch_at
            if last is None or (now - last).total_seconds() >= 1.5:
                self._last_launch_at = now
                self._log(u"开售整点到达但页面不可识别，拉起 i茅台 并等待接入")
                if callable(self.on_launch_app):
                    self.on_launch_app()
            self.status = u"整点已到，等待 i茅台 页面…"
            return

        if page == u"detail":
            # 业务规则：按钮只有在"整点整秒之后重新加载详情页"才会
            # 刷新成「立即抢购」。整点还停在详情页说明是旧页面，
            # 先退回列表，下一拍重进；退回失败才按当前页继续识别。
            if self._detail_backs < 3:
                self._detail_backs += 1
                self._log(
                    u"整点已在详情页（旧页面），退回列表准备重进"
                )
                self.bridge.back()
                self.status = u"退回列表，准备重新进入…"
                return
            self._log(u"详情页退回失败，按当前页继续识别")
            self._goto(SELECT_YEAR, u"整点已在详情，识别年份规格…")
            return

        if page == u"list":
            center = self._list_ready()
            if center is None:
                # 列表未确认，下轮重试，不盲目点击（不重校）
                self.status = u"整点列表确认中…"
                return
            self.recorded_pos = center
            # 目标商品优先（档案卡位+全称），失败再按坐标兜底
            if self._click_product():
                self._log(
                    u"开售整点到达，节点点击目标商品进入，位置 (%d, %d)"
                    % center
                )
            elif self.recorded_pos is not None:
                # 节点失败：固定坐标兜底
                x, y = self.recorded_pos
                self._log(
                    u"节点点击失败，固定坐标兜底 tap (%d, %d)" % (x, y)
                )
                self.bridge.tap_px(x, y, TAP_JITTER_PX)
            self._goto(WAIT_DETAIL, u"整点已点商品，等待详情页…")
            return

        # igou/home：到点仍停在浅层，交 NAV 从当前页快速接入
        self._log(u"开售整点到达，当前在 %s，快速接入" % page)
        self._goto(NAVIGATE_IGOU, u"整点已到，快速接入…")

    # ---------------- WAIT_DETAIL ----------------
    def _update_wait_detail(self, dt, now):
        """
        整点快速入页后：等详情页渲染。
        只查「数量」是否出现（1 次调用），每 DETAIL_ENTER_POLL 秒查一次；
        超时（DETAIL_ENTER_TIMEOUT）退回页面识别，避免点空后卡死。
        """
        if not self.bridge.is_connected():
            self._finish(
                False, u"无障碍服务未开启，请先到设置中开启后重新定时"
            )
            return

        self._detail_enter_elapsed += dt
        if self._detail_enter_next > 0.0:
            self._detail_enter_next -= dt
            self.status = u"等待详情页加载…"
            return
        self._detail_enter_next = DETAIL_ENTER_POLL

        if self.bridge.text_exists(u"数量"):
            self._log(u"已进入详情页，开始识别年份规格")
            self._goto(SELECT_YEAR, u"已进入商品，识别年份规格…")
            return

        if self._detail_enter_elapsed >= DETAIL_ENTER_TIMEOUT:
            self._log(u"等待详情页超时，退回页面识别重进")
            self._goto(NAVIGATE_IGOU, u"详情未打开，重新接入…")
            return

        self.status = u"等待详情页加载…"

