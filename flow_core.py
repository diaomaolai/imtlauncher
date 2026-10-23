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
   - 立即抢购/立即购买：识别到立刻点（1 秒内完成），随后进入连点模式：
     随机等待 0.xx 秒 → 随机连续点击 N 次（N 为 0-9 随机数）→
     再随机等待、再随机连点，循环不返回上一层，直到售罄；
   - 开售时间（按钮"HH:MM投放"，右下角区域）：连续 2 次读数一致
     才采信；未来时间返回列表等整点（不加秒）；已过时间返回列表，
     每 4 秒重新进入侦察下一场；
   - 已售罄：首次返回列表重新进入复核，第二次仍售罄才结束；
   - 未识别到：不中止、不返回，无限等待（应对弹窗/未刷新）；
4. 连点模式（点击购买后）：
   - 随机等待 0.xx 秒 → 随机连续点击 N 次（N=0-9 随机数，一拍
     一次约 10ms）→ 再随机等待、再随机连点，循环不返回；
   - 节点级 ACTION_CLICK，不会误点到弹窗上的按钮；
   - 期间出现弹窗（支付确认/安全组件填字）→ 判定成功一次
     （上报 rush-record + 扣次），不点任何弹窗按钮，连点不中断；
   - 按钮变为开售时间 → 交回详情识别（WAIT/重侦）；
   - 只有识别到「已售罄」才停止：返回列表重新进入复核，
     二次仍为售罄才结束；
5. 整点等待：到点点击记录位置进入，先选年份、改数量再交由详情页；
6. 弹窗（含风控倒计时）：任何环节只等待，不点任何按钮。

全程通过 AppLogger 打印并写入 txt 日志。
"""

from config import (
    PRODUCT_KEYWORDS,
    BUTTON_REGION_PX,
    BUY_NOW_TEXTS,
    LIST_MARKER_TEXTS,
    POPUP_MARKER_TEXTS,
    rapid_click_delay,
    SOLD_OUT_TEXTS,
    SALE_TIME_REGEX,
    RE_SCOUT_INTERVAL,
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
    rapid_burst_count,
)

# 状态
IDLE = u"IDLE"                # 等待首次倒计时
NAVIGATE_IGOU = u"NAV"        # 启动后导航：点 i购 → 点经典
ENTER_PRODUCT = u"ENTER"      # 列表查找商品并点击进入
SELECT_YEAR = u"YEAR"         # 详情页先识别并点击年份（规格）
SELECT_QTY = u"QTY"           # 再把数量改为目标瓶数（6）
READ_DETAIL = u"READ"         # 数量确认后识别抢购按钮
RAPID_BUY = u"RAPID"          # 立即抢购后持续连点（不返回，直到售罄）
WAIT_TIME = u"WAIT"           # 列表等待开售整点
RE_SCOUT = u"SCOUT"           # 时间已过，重新进入读取下一场
DONE = u"DONE"                # 结束（售罄）或中止（异常）


class FlowCore(object):
    """循环申购状态机"""

    def __init__(self, bridge, logger=None):
        self.bridge = bridge
        self.logger = logger
        self.first_target = None
        self.session_target = None
        self.display_target = None
        self.recorded_pos = None
        self.state = DONE
        self.status = u""
        self.success = False
        self.request_app_exit = False
        self._elapsed = 0.0
        self._heartbeat = 0.0
        self._last_time_hit = None
        self._stable_count = 0
        self._buy_verified = False
        self._soldout_pending = False
        # 连点模式：点击计数 + 等待/连点轮次状态
        self._rapid_click_count = 0
        self._rapid_phase = u"wait"     # wait：随机等待；burst：连续点击
        self._rapid_wait_left = 0.0
        self._rapid_burst_left = 0
        self._rapid_rounds = 0
        # 数量修改：本拍/累计加号点击
        self._qty_taps = 0
        # 导航阶段标记（只在每次运行开始时走一次）
        self._nav_igou_clicked = False
        self._nav_jd_clicked = False
        # 本次要选择的年份（UI 下拉菜单武装时写入；默认当前年份）
        self.year_target = YEAR_TARGET_TEXT
        # 弹窗确认成功回调（由 main 注入，用于状态上报置 1）
        self.on_popup_success = None

    # ---------------- 日志 ----------------
    def _log(self, message):
        if self.logger is not None:
            self.logger.log(message)
        else:
            print(message)

    # ---------------- 生命周期 ----------------
    def reset(self, first_target):
        """武装流程，first_target 为首次触发整点"""
        self.first_target = first_target
        self.session_target = None
        self.display_target = first_target
        self.recorded_pos = None
        self.state = IDLE
        self.status = u"等待启动时刻…"
        self.success = False
        self.request_app_exit = False
        self._elapsed = 0.0
        self._heartbeat = 0.0
        self._last_time_hit = None
        self._stable_count = 0
        self._buy_verified = False
        self._soldout_pending = False
        self._rapid_click_count = 0
        self._rapid_phase = u"wait"
        self._rapid_wait_left = 0.0
        self._rapid_burst_left = 0
        self._rapid_rounds = 0
        self._qty_taps = 0
        self._nav_igou_clicked = False
        self._nav_jd_clicked = False
        self._log(
            u"已设置定时，首次触发时刻 %s"
            % first_target.strftime(u"%Y-%m-%d %H:%M:%S")
        )

    @property
    def is_done(self):
        return self.state == DONE

    def _finish(self, success, message):
        self.success = success
        self.status = message
        self.state = DONE
        self._log(u"流程结束：%s" % message)

    # ---------------- 主循环 ----------------
    def update(self, dt, now):
        if self.state == IDLE:
            self._update_idle(now)
        elif self.state == NAVIGATE_IGOU:
            self._update_navigate(dt, now)
        elif self.state == ENTER_PRODUCT:
            self._update_enter_product(dt, now)
        elif self.state == SELECT_YEAR:
            self._update_select_year(dt, now)
        elif self.state == SELECT_QTY:
            self._update_select_qty(dt, now)
        elif self.state == READ_DETAIL:
            self._update_read_detail(dt, now)
        elif self.state == RAPID_BUY:
            self._update_rapid_buy(dt, now)
        elif self.state == WAIT_TIME:
            self._update_wait_time(dt, now)
        elif self.state == RE_SCOUT:
            self._update_re_scout(dt, now)

    def _goto(self, state, status, elapsed=0.0):
        """切换状态并重置计时器"""
        self.state = state
        self.status = status
        self._elapsed = elapsed
        self._heartbeat = 0.0
        self._last_time_hit = None
        self._stable_count = 0
        self._buy_verified = False
        self._rapid_click_count = 0
        self._rapid_phase = u"wait"
        self._rapid_wait_left = 0.0
        self._rapid_burst_left = 0
        self._rapid_rounds = 0
        self._qty_taps = 0
        # 注意：_soldout_pending 不在此重置，售罄复核要跨 ENTER→READ 保留

    def _heartbeat_log(self, dt, message):
        """等待期间按 WAIT_HEARTBEAT 周期记录心跳"""
        self._heartbeat += dt
        if self._heartbeat >= WAIT_HEARTBEAT:
            self._log(message)
            self._heartbeat = 0.0

    def _list_ready(self):
        """
        确认当前确实在商品列表页：
        既有「飞天」+「%vol」商品节点，又有列表独有标签
        （全部/经典/精品）。返回商品节点中心，否则 None。
        详情页标题也含"飞天"，靠标签排除误判。
        """
        center = self.bridge.node_center(PRODUCT_KEYWORDS)
        if center is None:
            return None
        for marker in LIST_MARKER_TEXTS:
            if self.bridge.text_exists(marker):
                return center
        return None

    def _popup_visible(self):
        """点击购买后是否出现弹窗（任一弹窗特征文字存在即视为出现）"""
        for marker in POPUP_MARKER_TEXTS:
            if self.bridge.text_exists(marker):
                return True
        return False

    # ---------------- IDLE ----------------
    def _update_idle(self, now):
        if now >= self.first_target:
            self._log(u"倒计时到达，开始自动进入 i购→经典")
            self._goto(NAVIGATE_IGOU, u"正在进入 i购…")

    # ---------------- NAVIGATE_IGOU ----------------
    def _update_navigate(self, dt, now):
        """
        启动后导航（区域限定识别，再点击）：
        1) i购页的子标签「经典」可见 → 已在 i购，点击经典；
        2) 否则底部 i购 tab 可见 → 在首页，点击 i购（只点一次）；
        3) 经典点击后，等经典列表双确认（飞天+%vol 与 全部/经典/精品），
           确认后进入商品，后续逻辑不变。
        全程动态轮询，不设固定等待。
        """
        if not self.bridge.is_connected():
            self._finish(
                False,
                u"无障碍服务未开启，请先到设置中开启后重新定时",
            )
            return

        # 第一步：点 i购；第二步：点经典
        if not self._nav_jd_clicked:
            if self.bridge.text_exists_in_px_region(
                JINGDIAN_TAB_TEXT, JINGDIAN_TAB_REGION_PX
            ):
                self._log(
                    u"已在 i购，区域内识别到「经典」，点击经典"
                )
                if self.bridge.click_text_in_px_region(
                    JINGDIAN_TAB_TEXT, JINGDIAN_TAB_REGION_PX
                ):
                    self._nav_jd_clicked = True
                    self.status = u"已点击经典，等待商品列表…"
                else:
                    self._log(u"「经典」点击失败，下轮重试")
                return

            if not self._nav_igou_clicked:
                if self.bridge.text_exists_in_px_region(
                    IGOU_TAB_TEXT, IGOU_TAB_REGION_PX
                ):
                    self._log(
                        u"首页底部区域内识别到「i购」，点击 i购"
                    )
                    if self.bridge.click_text_in_px_region(
                        IGOU_TAB_TEXT, IGOU_TAB_REGION_PX
                    ):
                        self._nav_igou_clicked = True
                        self.status = u"已点击 i购，等待页面加载…"
                    else:
                        self._log(u"「i购」点击失败，下轮重试")
                    return

            # 冷启动/页面加载中：无限等，i购 tab 或经典子标签出现即动作
            self._heartbeat_log(
                dt, u"等待 i茅台加载（寻找 i购/经典）…"
            )
            self.status = u"等待 i茅台页面加载…"
            return

        # 经典已点：等经典列表双确认，确认后进入商品
        center = self._list_ready()
        if center is not None:
            self.recorded_pos = center
            self._log(
                u"经典列表确认（全部/经典/精品），点击「飞天」进入，位置 (%d, %d)"
                % center
            )
            self.bridge.click_node_by_parts(PRODUCT_KEYWORDS)
            self._goto(SELECT_YEAR, u"已进入商品，识别年份规格…")
            return

        self._heartbeat_log(
            dt, u"已点经典，等待经典列表渲染（飞天+%vol）…"
        )
        self.status = u"等待经典商品列表…"


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
                u"列表确认（全部/经典/精品），点击「飞天」进入，位置 (%d, %d)"
                % center
            )
            self.bridge.click_node_by_parts(PRODUCT_KEYWORDS)
            self._goto(SELECT_YEAR, u"已进入商品，识别年份规格…")
            return

        # 未确认在列表：可能弹窗未消失或停在详情页，无限等待
        self._heartbeat_log(
            dt, u"未确认在商品列表（弹窗/详情页），继续等待…"
        )
        self.status = u"等待商品列表页…"

    # ---------------- SELECT_YEAR ----------------
    def _update_select_year(self, dt, now):
        """
        进入详情页后第一步：在规格区域识别并点击 UI 选定的年份
        （默认当前年份，如 2026），点击一次后再进入抢购按钮识别。
        动态轮询：年份区域未渲染（加载中）就等待，不设固定等待。
        兜底：若年份区域始终没出现、但抢购按钮区已出现可识别文字
        （立即抢购/投放/售罄），直接放行到 READ，避免页面改版时卡死。
        """
        if not self.bridge.is_connected():
            self._finish(
                False,
                u"无障碍服务未开启，请先到设置中开启后重新定时",
            )
            return

        year = self.year_target or YEAR_TARGET_TEXT
        # UI 选了未知年份时退回默认年份的识别框
        region = YEAR_CELL_REGION_PX.get(
            year, YEAR_CELL_REGION_PX[YEAR_TARGET_TEXT]
        )

        # 1) 该年份格区域内识别到目标年份 → 点击一次，进入数量修改
        if self.bridge.text_exists_in_px_region(year, region):
            self._log(
                u"详情页识别到年份规格「%s」，点击选择年份" % year
            )
            self.bridge.click_text_in_px_region(year, region)
            self._goto(SELECT_QTY, u"已选择年份%s，修改数量…" % year)
            return

        # 2) 兜底：年份区域缺失但抢购按钮已渲染，
        #    仍尝试数量修改（数量状态有自己的兜底），再识别按钮
        button_ready = self.bridge.find_regex_in_px_region(
            SALE_TIME_REGEX, BUTTON_REGION_PX
        )
        for texts in (BUY_NOW_TEXTS, SOLD_OUT_TEXTS):
            for t in texts:
                if self.bridge.text_exists_in_px_region(
                    t, BUTTON_REGION_PX
                ):
                    button_ready = True
                    break
        if button_ready:
            self._log(
                u"未找到年份规格区域，但抢购按钮已出现，尝试数量修改"
            )
            self._goto(SELECT_QTY, u"跳过年份，修改数量…")
            return

        # 3) 详情页加载中：动态等待年份区域出现
        self._heartbeat_log(
            dt,
            u"等待详情页年份规格区域渲染（年份「%s」）…" % year,
        )
        self.status = u"等待详情页年份规格区域…"

    # ---------------- SELECT_QTY ----------------
    def _button_ready(self):
        """抢购按钮区是否已出现可识别内容（时间/立即抢购/售罄）"""
        if self.bridge.find_regex_in_px_region(
            SALE_TIME_REGEX, BUTTON_REGION_PX
        ):
            return True
        for texts in (BUY_NOW_TEXTS, SOLD_OUT_TEXTS):
            for t in texts:
                if self.bridge.text_exists_in_px_region(
                    t, BUTTON_REGION_PX
                ):
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

        hits = self.bridge.find_regex_in_px_region(
            QTY_REGEX, QTY_VALUE_REGION_PX
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
            # 同一拍内连续点完需要的次数（加号节点无文字，固定坐标）
            px, py = QTY_PLUS_CENTER_PX
            for _ in range(need):
                if self._qty_taps >= QTY_MAX_TAPS:
                    break
                self.bridge.tap_px(px, py, TAP_JITTER_PX)
                self._qty_taps += 1
            self._log(
                u"当前数量 %d 瓶，连续点击加号 %d 次（累计 %d 次），"
                u"改为 %d 瓶"
                % (value, need, self._qty_taps, QTY_TARGET)
            )
            self.status = u"修改数量 %d→%d…" % (value, QTY_TARGET)
            return

        # 读不到数量：按钮已渲染则放行，否则等待详情页加载
        if self._button_ready():
            self._log(
                u"未找到数量控件，但抢购按钮已出现，直接识别按钮"
            )
            self._goto(READ_DETAIL, u"跳过数量，识别抢购按钮…")
            return
        self._heartbeat_log(
            dt, u"等待详情页数量区域渲染…"
        )
        self.status = u"等待详情页数量区域…"

    # ---------------- READ_DETAIL ----------------
    def _update_read_detail(self, dt, now):
        """详情页：售罄结束；立即抢购点击；时间则安排或重侦"""
        self._elapsed += dt

        # 1) 立即抢购：1 秒内识别并点击，随后进入连点模式
        for text in BUY_NOW_TEXTS:
            if self.bridge.click_text(text):
                self._log(u"识别到「%s」，立即点击购买" % text)
                self._soldout_pending = False
                self._goto(
                    RAPID_BUY,
                    u"已点击购买，进入连点模式直到售罄…",
                )
                # 进入连点：先随机等待，再随机连点一轮
                self._rapid_phase = u"wait"
                self._rapid_wait_left = rapid_click_delay()
                self._rapid_burst_left = 0
                self._rapid_rounds = 0
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
                self.request_app_exit = True
                self._finish(True, u"商品已售罄（二次确认），启动器结束")
                return
            self._soldout_pending = True
            self._log(
                u"首次识别到「已售罄」，返回列表并重新进入复核"
            )
            self.bridge.back()
            self._goto(ENTER_PRODUCT, u"售罄复核，重新进入确认…")
            return

        # 3) 开售时间（右下角区域）
        hits = self.bridge.find_regex_in_px_region(
            SALE_TIME_REGEX, BUTTON_REGION_PX
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
            try:
                hour, minute = (int(v) for v in hhmm.split(u":"))
            except ValueError:
                hour = minute = None
            if hour is not None:
                target = now.replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                )
                if target > now:
                    # 未来时间：返回列表，整点等待，不加秒
                    self._log(
                        u"读取到开售时间 %s（未来），返回列表，等待整点"
                        % hhmm
                    )
                    self.bridge.back()
                    self.session_target = target
                    self.display_target = target
                    self._goto(
                        WAIT_TIME,
                        u"等待开售 %s" % target.strftime(u"%H:%M:%S"),
                    )
                    return
                # 已过时间：返回列表 → 重新进入读取下一场
                self._log(
                    u"读取到开售时间 %s（已过），返回列表，重新侦察下一场"
                    % hhmm
                )
                self.bridge.back()
                self._goto(
                    RE_SCOUT,
                    u"开售时间已过，准备重新侦察…",
                )
                return

        # 4) 按钮尚未刷新/弹窗遮挡：不中止、不返回，无限等待，
        #    每 5 秒记心跳；按钮一出现立即处理（识别在 1 秒内）。
        self._heartbeat_log(
            dt,
            u"详情页等待按钮刷新/弹窗消失（不做任何点击）…",
        )
        self.status = u"详情页等待按钮刷新…"

    # ---------------- RAPID_BUY ----------------
    def _update_rapid_buy(self, dt, now):
        """
        连点模式（随机等待 + 随机连点轮次）：
        - 每个轮次：先随机等待 0.xx 秒（0.00~0.99，两位数字各取
          0-9 随机数），再随机连续点击 N 次（N 为 0-9 随机数，
          一拍一次，约 10ms 一拍），然后进入下一轮；
        - 每拍都先判断：售罄退出 / 弹窗记一次成功 / 按钮变时间
          交回 READ；节点级 ACTION_CLICK，弹窗覆盖也不会误点弹窗；
        - 不返回上一层，直到识别到「已售罄」：返回列表重新进入复核，
          READ 二次确认仍为售罄才结束启动器。
        """
        if not self.bridge.is_connected():
            self._finish(
                False, u"无障碍服务未开启，请先到设置中开启后重新定时"
            )
            return

        # 1) 售罄优先（唯一退出条件，首次走复核）
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

        # 2) 弹窗出现：只记一次成功（上报扣次），不点弹窗，连点继续
        if not self._buy_verified and self._popup_visible():
            self._buy_verified = True
            self._log(u"购买弹窗已出现，判定抢购成功（继续连点，不点弹窗）")
            if callable(getattr(self, "on_popup_success", None)):
                try:
                    self.on_popup_success()
                except Exception:
                    pass

        # 3) 随机等待阶段：只观察，不点击
        if self._rapid_phase == u"wait":
            self._rapid_wait_left -= dt
            if self._rapid_wait_left > 0.0:
                # 等待期间按钮若已变为开售时间，交回 READ
                hits = self.bridge.find_regex_in_px_region(
                    SALE_TIME_REGEX, BUTTON_REGION_PX
                )
                if hits:
                    self._log(
                        u"连点中按钮变为开售时间 %s，交回详情识别"
                        % hits[0]
                    )
                    self._goto(READ_DETAIL, u"按钮变为时间，重新识别…")
                    return
                self.status = (
                    u"连点等待中（已点 %d 次，剩 %.2f 秒）…"
                    % (self._rapid_click_count,
                       max(0.0, self._rapid_wait_left))
                )
                return

            # 随机等待结束：决定本轮随机连点次数 N（0-9）
            burst = rapid_burst_count()
            self._rapid_rounds += 1
            self._rapid_burst_left = burst
            self._rapid_phase = u"burst"
            if burst > 0:
                self._log(
                    u"第 %d 轮连点开始：随机等待结束，本轮连续点击 %d 次"
                    % (self._rapid_rounds, burst)
                )
            else:
                # 本轮随机到 0 次，直接进入下一轮等待
                self._rapid_phase = u"wait"
                self._rapid_wait_left = rapid_click_delay()
            return

        # 4) 连点阶段：一拍点击一次购买按钮
        clicked = False
        for text in BUY_NOW_TEXTS:
            if self.bridge.click_text(text):
                clicked = True
                self._rapid_click_count += 1
                self._rapid_burst_left -= 1
                if self._rapid_click_count == 1:
                    self._log(
                        u"连点模式：随机等待 0.xx 秒 → 随机连续点击 N 次"
                        u"（N 为 0-9 随机数）→ 再随机等待、再连点，"
                        u"循环点击「%s」直到售罄" % text
                    )
                elif self._rapid_click_count % 20 == 0:
                    self._log(
                        u"连点中：已点击购买 %d 次（%d 轮）"
                        % (self._rapid_click_count, self._rapid_rounds)
                    )
                break

        # 5) 找不到按钮：弹窗遮挡则继续；变成开售时间则交回 READ
        if not clicked:
            hits = self.bridge.find_regex_in_px_region(
                SALE_TIME_REGEX, BUTTON_REGION_PX
            )
            if hits:
                self._log(
                    u"连点中按钮变为开售时间 %s，交回详情识别" % hits[0]
                )
                self._goto(READ_DETAIL, u"按钮变为时间，重新识别…")
                return

        # 6) 本轮连点次数用完：进入下一轮随机等待
        if self._rapid_burst_left <= 0:
            if self._rapid_rounds % 5 == 0:
                self._log(
                    u"第 %d 轮连点完成，累计点击 %d 次，重新随机等待"
                    % (self._rapid_rounds, self._rapid_click_count)
                )
            self._rapid_phase = u"wait"
            self._rapid_wait_left = rapid_click_delay()
            return

        self.status = (
            u"第 %d 轮连点中（本轮剩 %d 次，累计 %d 次）…"
            % (
                self._rapid_rounds,
                max(0, self._rapid_burst_left),
                self._rapid_click_count,
            )
        )

    # ---------------- WAIT_TIME ----------------
    def _update_wait_time(self, dt, now):
        """列表等待开售整点：到点点击记录位置进入，交由详情页处理"""
        if now >= self.session_target:
            if self.recorded_pos is None:
                # 无记录位置：改为查找节点进入
                self._log(u"开售整点到达，无记录位置，改为查找商品进入")
                self._goto(ENTER_PRODUCT, u"整点查找商品…")
                return
            x, y = self.recorded_pos
            self._log(
                u"开售整点到达，点击记录位置 (%d, %d) 进入" % (x, y)
            )
            self.bridge.tap_px(x, y, TAP_JITTER_PX)
            self._goto(SELECT_YEAR, u"整点进入，先识别年份规格…")
            return
        self.status = u"等待开售整点 %s…" \
            % self.session_target.strftime(u"%H:%M:%S")

    # ---------------- RE_SCOUT ----------------
    def _update_re_scout(self, dt, now):
        """已过时间：间隔后重新进入商品读取下一场"""
        self._elapsed += dt
        if self._elapsed >= RE_SCOUT_INTERVAL:
            center = self._list_ready()
            if center is not None:
                self.recorded_pos = center
                self._log(
                    u"重新侦察：点击商品进入，位置 (%d, %d)" % center
                )
                self.bridge.click_node_by_parts(PRODUCT_KEYWORDS)
                self._goto(SELECT_YEAR, u"重新侦察，先识别年份规格…")
                return
            # 列表还没准备好：再等一个间隔
            self._log(u"重新侦察：列表未出现商品，继续等待…")
            self._elapsed = 0.0
