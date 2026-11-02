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
     点一次 → 独立随机等 0.[X][X] 秒 → 再点一次 → 再随机等 …；
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
    RAPID_REENTER_MAX_ROUNDS,
    SOLD_OUT_TEXTS,
    SALE_TIME_REGEX,
    REENTER_GRACE_SECONDS,
    REENTER_MIN_INTERVAL,
    DETAIL_ENTER_TIMEOUT,
    DETAIL_ENTER_POLL,
    STABLE_READ_COUNT,
    WAIT_HEARTBEAT,
    TAP_JITTER_PX,
    IGOU_TAB_TEXT,
    IGOU_TAB_REGION_PX,
    JINGDIAN_TAB_TEXT,
    JINGDIAN_TAB_REGION_PX,
    YEAR_TARGET_TEXT,
    YEAR_CELL_REGION_PX,
    QTY_TARGET,
    QTY_VALUE_REGION_PX,
    QTY_PLUS_CENTER_PX,
    QTY_REGEX,
    QTY_MAX_TAPS,
    RUNTIME_STALL_RECAL_SECONDS,
    MANUAL_LAUNCH_LEAD_SECONDS,
)

# 状态
IDLE = u"IDLE"                # 等待首次倒计时
NAVIGATE_IGOU = u"NAV"        # 启动后导航：点 i购 → 点经典
ENTER_PRODUCT = u"ENTER"      # 列表查找商品并点击进入
WAIT_DETAIL = u"DETAIL"       # 已点商品，等详情页渲染（「数量」出现）
SELECT_YEAR = u"YEAR"         # 详情页先识别并点击年份（规格）
SELECT_QTY = u"QTY"           # 再把数量改为目标瓶数（6）
READ_DETAIL = u"READ"         # 数量确认后识别抢购按钮
RAPID_BUY = u"RAPID"          # 立即抢购后按 0.xx 秒间隔连点
WAIT_VERIFY = u"VERIFY"       # 安全组件验证弹窗：只等待，不点击
WAIT_TIME = u"WAIT"           # 列表等待开售整点
DONE = u"DONE"                # 结束（售罄）或中止（异常）


class FlowCore(object):
    """循环申购状态机"""

    def __init__(self, bridge, logger=None):
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
        # 节点对不上停滞检测：同一状态累计找不到控件的秒数
        self._stall_seconds = 0.0
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

    # ---------------- 日志 ----------------
    def _log(self, message):
        if self.logger is not None:
            self.logger.log(message)
        else:
            print(message)

    # ---------------- 档案 bounds 兜底 ----------------
    def _profile_controls(self):
        if self.profile is None:
            return {}
        return self.profile.controls or {}

    def _profile_record(self, control_key, sub_key=None):
        controls = self._profile_controls()
        if sub_key is None:
            record = controls.get(control_key)
        else:
            group = controls.get(control_key)
            record = group.get(sub_key) if isinstance(group, dict) else None
        return record if isinstance(record, dict) else None

    def _profile_bounds(self, control_key, sub_key=None):
        record = self._profile_record(control_key, sub_key)
        if record is None:
            return None
        bounds = record.get(u"bounds")
        if not bounds or len(bounds) != 4:
            return None
        return tuple(int(v) for v in bounds)

    def _profile_center(self, control_key, sub_key=None):
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
        return self._region(u"action_button", BUTTON_REGION_PX)

    def _tick_stall(self, dt):
        """等待分支累计停滞；超阈值请求自动重校"""
        self._stall_seconds += dt
        if self._stall_seconds >= RUNTIME_STALL_RECAL_SECONDS:
            self.needs_recalibration = True
            self._log(u"节点持续对不上，请求自动重新校准")

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
        self._entry_wait = 0.0
        self._rapid_reenter_limit = 0
        self._rapid_reenter_rounds = 0
        self._slot_fast_done = False
        self._detail_enter_elapsed = 0.0
        self._detail_enter_next = 0.0
        self._reenter_next_at = None
        self._log(
            u"已设置定时，开售时刻 %s，计划拉起时刻 %s"
            % (
                first_target.strftime(u"%Y-%m-%d %H:%M:%S"),
                launch_target.strftime(u"%H:%M:%S"),
            )
        )

    @property
    def is_done(self):
        return self.state == DONE

    def _finish(self, success, message):
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
        self._stall_seconds = 0.0
        # 年份、数量各自独立计时 3 秒宽限：年份加载慢不能把数量的
        # 宽限一起吃掉，否则会跳过"改 6 瓶"。
        if state in (SELECT_YEAR, SELECT_QTY):
            self._entry_wait = 0.0
        # 整点快速入页/等详情页：进入新状态时重新计时
        self._slot_fast_done = False
        self._detail_enter_elapsed = 0.0
        self._detail_enter_next = 0.0
        # 注意：_reenter_next_at 不在此重置——重进间隔由 _handle_sale_time
        # 在 _goto 之后设置，跨 WAIT 保留才有意义。
        # 注意：_soldout_pending 不在此重置，售罄复核要跨 ENTER→READ 保留

    def _heartbeat_log(self, dt, message):
        """等待期间按 WAIT_HEARTBEAT 周期记录心跳"""
        self._heartbeat += dt
        if self._heartbeat >= WAIT_HEARTBEAT:
            self._log(message)
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
                self.bridge.back()
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
        self.bridge.back()
        self.session_target = target
        self.display_target = target
        self._goto(
            WAIT_TIME,
            u"等待开售 %s" % target.strftime(u"%m-%d %H:%M"),
        )
        return True

    def _current_page(self):
        """
        任意页面接入：靠通用文字特征判定当前停在 i茅台 的哪个页面，
        全机型通用、不依赖 px。返回 detail/list/igou/home/unknown。
        列表页必须认到完整商品名：只认「飞天」+「%vol」会把 i购
        「全部」视图里的「鼓乐飞天」也当成目标商品。
        """
        if self.bridge.text_exists(u"数量"):
            return u"detail"
        has_jd = self.bridge.text_exists(JINGDIAN_TAB_TEXT)
        if has_jd and self._product_center() is not None:
            return u"list"
        if has_jd:
            return u"igou"
        if self.bridge.text_exists(IGOU_TAB_TEXT):
            return u"home"
        return u"unknown"

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
          unknown→ 加载中，动态等待（停滞累计，超限触发重校）。
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
                    self._goto(SELECT_YEAR, u"已进入商品，识别年份规格…")
                    return
                self._tick_stall(dt)
                self.status = u"点击目标商品失败，重试…"
                return
            # 判定在列表但未取到中心，下轮重试
            self._tick_stall(dt)
            self.status = u"列表确认中…"
            return

        if page == u"igou":
            jd_region = self._region(
                u"jingdian_tab", JINGDIAN_TAB_REGION_PX
            )
            self._log(u"识别到当前在 i购，区域内点击「经典」")
            if not self.bridge.click_text_in_px_region(
                JINGDIAN_TAB_TEXT, jd_region
            ):
                self._log(u"「经典」点击失败，下轮重试")
            self.status = u"已点击经典，等待商品列表…"
            return

        if page == u"home":
            igou_region = self._region(
                u"igou_tab", IGOU_TAB_REGION_PX
            )
            self._log(u"识别到当前在首页，区域内点击「i购」")
            if not self.bridge.click_text_in_px_region(
                IGOU_TAB_TEXT, igou_region
            ):
                self._log(u"「i购」点击失败，下轮重试")
            self.status = u"已点击 i购，等待页面加载…"
            return

        # unknown：冷启动/加载中，动态等待可识别页面出现
        self._heartbeat_log(
            dt, u"等待 i茅台加载可识别页面（首页/i购/列表/详情）…"
        )
        self._tick_stall(dt)
        self.status = u"等待 i茅台页面加载…"


    # ---------------- ENTER_PRODUCT ----------------
    def _update_enter_product(self, dt, now):
        """列表查找商品：商品节点+列表标签双确认才进入（弹窗期无限等待）"""
        if not self.bridge.is_connected():
            self._finish(
                False,
                u"无障碍服务未开启，请先到设置中开启后重新定时",
            )
            return

        center = self._list_ready()
        if center is not None:
            self.recorded_pos = center
            self._log(
                u"列表确认（完整商品名+列表标签），点击商品进入，"
                u"位置 (%d, %d)" % center
            )
            if self._click_product():
                self._goto(SELECT_YEAR, u"已进入商品，识别年份规格…")
                return
            self._tick_stall(dt)
            self.status = u"点击目标商品失败，重试…"
            return

        # 未确认在列表：可能弹窗未消失或停在详情页，无限等待
        self._heartbeat_log(
            dt, u"未确认在商品列表（弹窗/详情页），继续等待…"
        )
        self._tick_stall(dt)
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
        hits = self.bridge.find_regex_in_px_region(
            SALE_TIME_REGEX, self._button_region()
        )
        if hits:
            self._log(
                u"详情页按钮仍为 %s，不选年份/数量，直接退回等待"
                % hits[0]
            )
            self._handle_sale_time(hits[0], now)
            return

        year = self.year_target or YEAR_TARGET_TEXT
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
        button_ready = self.bridge.find_regex_in_px_region(
            SALE_TIME_REGEX, button_region
        )
        for texts in (BUY_NOW_TEXTS, SOLD_OUT_TEXTS):
            for t in texts:
                if self.bridge.text_exists_in_px_region(
                    t, button_region
                ):
                    button_ready = True
                    break
        # 2) 兜底：按钮已渲染且等待超过宽限（页面确实改版），
        #    才放行；宽限内即使按钮先出现也坚持等年份，防止跳过
        if button_ready and self._entry_wait >= ENTRY_CONTROL_GRACE_SECONDS:
            self._log(
                u"等待 %.1f 秒仍无年份规格区域，按钮已出现，"
                u"跳过年份尝试数量修改" % self._entry_wait
            )
            self._goto(SELECT_QTY, u"跳过年份，修改数量…")
            return

        # 3) 详情页加载中（含按钮先渲染但宽限未到）：动态等待
        self._entry_wait += dt
        self._heartbeat_log(
            dt,
            u"等待详情页年份规格区域渲染（年份「%s」）…" % year,
        )
        self._tick_stall(dt)
        self.status = u"等待详情页年份规格区域…"

    # ---------------- SELECT_QTY ----------------
    def _button_ready(self):
        """抢购按钮区是否已出现可识别内容（时间/立即抢购/售罄）"""
        region = self._button_region()
        if self.bridge.find_regex_in_px_region(
            SALE_TIME_REGEX, region
        ):
            return True
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
            # 档案加号中心优先，无档案退回 OPPO 固定中心。
            # 一次手势派发多点（新 APK），旧 APK 自动退回逐个点击。
            plus_center = self._profile_center(u"qty_plus") \
                or QTY_PLUS_CENTER_PX
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

        # 读不到数量：按钮已渲染且等待超过宽限（页面改版）才放行；
        # 宽限内坚持等数量控件，保证正常加载时一定改 6 瓶
        if self._button_ready() \
                and self._entry_wait >= ENTRY_CONTROL_GRACE_SECONDS:
            self._log(
                u"等待 %.1f 秒仍无数量控件，按钮已出现，直接识别按钮"
                % self._entry_wait
            )
            self._goto(READ_DETAIL, u"跳过数量，识别抢购按钮…")
            return
        self._entry_wait += dt
        self._heartbeat_log(
            dt, u"等待详情页数量区域渲染…"
        )
        self._tick_stall(dt)
        self.status = u"等待详情页数量区域…"

    # ---------------- READ_DETAIL ----------------
    def _update_read_detail(self, dt, now):
        """详情页：售罄结束；立即抢购点击；时间则安排或重侦"""

        # 1) 立即抢购：1 秒内识别并点击，随后进入连点模式
        hit = self._tap_buy()
        if hit is not None:
            self._log(u"识别到「%s」，立即点击购买" % hit)
            self._soldout_pending = False
            self._goto(
                RAPID_BUY,
                u"已点击购买，进入连点模式…",
            )
            # 第一下已在 READ 点出，下一次点击前先等一个
            # 独立随机的 0.[X][X] 秒
            self._rapid_wait_left = rapid_click_delay()
            # 本轮连点达到该随机次数后自动 back 重进刷新
            self._rapid_reenter_limit = rapid_reenter_count()
            self._log(
                u"本轮自动重进阈值：连点 %d 次后返回上一层重进"
                % self._rapid_reenter_limit
            )
            return

        # 2) 已售罄：需二次确认——先返回列表重新进入，
        #    再次读到的按钮仍为售罄才结束（防 H5 缓存旧状态误判）
        sold_out = False
        for text in SOLD_OUT_TEXTS:
            if self.bridge.text_exists(text):
                sold_out = True
                break
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

        # 3) 开售时间（按钮区域，档案 bounds 优先）
        hits = self.bridge.find_regex_in_px_region(
            SALE_TIME_REGEX, self._button_region()
        )
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
        self._heartbeat_log(
            dt,
            u"详情页等待按钮刷新/弹窗消失（不做任何点击）…",
        )
        self._tick_stall(dt)
        self.status = u"详情页等待按钮刷新…"

    # ---------------- RAPID_BUY ----------------
    def _update_rapid_buy(self, dt, now):
        """
        抢购连点（严格 0.[X][X] 秒间隔，无轮次、无连击）：
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

        # 2) 售罄优先（唯一正常退出，首次走复核）
        sold_out = False
        for text in SOLD_OUT_TEXTS:
            if self.bridge.text_exists(text):
                sold_out = True
                break
        if sold_out:
            self._soldout_pending = True
            self._log(
                u"连点中识别到「已售罄」，停止连点，"
                u"返回列表并重新进入复核"
            )
            self.bridge.back()
            self._goto(ENTER_PRODUCT, u"售罄复核，重新进入确认…")
            return

        # 3) 点一次（按钮区优先，失败退回全页节点点击）
        hit = self._tap_buy()
        clicked = hit is not None
        if clicked:
            self._rapid_click_count += 1
            if self._rapid_click_count == 1:
                self._log(
                    u"连点模式：每点一次后随机等 0.[X][X] 秒"
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
                    u"继续按 0.[X][X] 秒间隔点击" % self._soft_hint_count
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
        if self._verify_elapsed < VERIFY_POLL_INTERVAL:
            self.status = u"等待人工完成安全验证…"
            return
        self._verify_elapsed = 0.0

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
            self._log(u"开售整点到达但不在 i茅台，自行启动并等待接入")
            if callable(self.on_launch_app):
                self.on_launch_app()
            self.status = u"整点已到，拉起 i茅台…"
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
                # 列表未确认，下轮重试，不盲目点击
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
            self._goto(SELECT_YEAR, u"整点进入，识别年份规格…")
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

