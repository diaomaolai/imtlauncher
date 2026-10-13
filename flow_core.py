# -*- coding: utf-8 -*-
"""
核心流程模块（循环作战版）

前提：手动打开 i茅台并停在 i购商品列表页（能看到飞天商品）。

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
2. 详情页（动态识别，无固定等待）：
   - 立即抢购/立即购买：0.3 秒轮询，识别到立刻点（1 秒内完成）；
   - 开售时间（按钮"HH:MM投放"，右下角区域）：连续 2 次读数一致
     才采信；未来时间返回列表等整点（不加秒）；已过时间返回列表，
     每 4 秒重新进入侦察下一场；
   - 已售罄：首次返回列表重新进入复核，第二次仍售罄才结束；
   - 未识别到：不中止、不返回，无限等待（应对弹窗/未刷新）；
3. 点击购买后（按钮不会消失，只以弹窗出现为生效依据）：
   - 0.3 秒内出现弹窗 → 点击生效，只等待，不点任何弹窗按钮；
   - 0.3 秒内未出现弹窗 → 返回列表重进再点；
   - 列表双确认回来后 → 重新进入读下一场；
4. 整点等待：到点点击记录位置进入，交由详情页处理；
5. 弹窗（含风控倒计时）：任何环节只等待，不点任何按钮。

全程通过 AppLogger 打印并写入 txt 日志。
"""

from datetime import timedelta

from config import (
    PRODUCT_KEYWORDS,
    BUTTON_REGION_PX,
    BUY_NOW_TEXTS,
    LIST_MARKER_TEXTS,
    POPUP_MARKER_TEXTS,
    BUY_VERIFY_SECONDS,
    SOLD_OUT_TEXTS,
    SALE_TIME_REGEX,
    RE_SCOUT_INTERVAL,
    STABLE_READ_COUNT,
    WAIT_HEARTBEAT,
    TAP_JITTER_PX,
)

# 状态
IDLE = u"IDLE"                # 等待首次倒计时
ENTER_PRODUCT = u"ENTER"      # 列表查找商品并点击进入
READ_DETAIL = u"READ"         # 详情页识别按钮
POST_PURCHASE = u"POST"       # 购买后等待弹窗/返回列表
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
        elif self.state == ENTER_PRODUCT:
            self._update_enter_product(dt, now)
        elif self.state == READ_DETAIL:
            self._update_read_detail(dt, now)
        elif self.state == POST_PURCHASE:
            self._update_post_purchase(dt, now)
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
            self._log(u"倒计时到达，开始识别商品「飞天%vol」")
            self._goto(ENTER_PRODUCT, u"正在识别商品…")

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
            self._goto(READ_DETAIL, u"已进入商品，读取详情页…")
            return

        # 未确认在列表：可能弹窗未消失或停在详情页，无限等待
        self._heartbeat_log(
            dt, u"未确认在商品列表（弹窗/详情页），继续等待…"
        )
        self.status = u"等待商品列表页…"

    # ---------------- READ_DETAIL ----------------
    def _update_read_detail(self, dt, now):
        """详情页：售罄结束；立即抢购点击；时间则安排或重侦"""
        self._elapsed += dt

        # 1) 立即抢购：1 秒内识别并点击
        for text in BUY_NOW_TEXTS:
            if self.bridge.click_text(text):
                self._log(u"识别到「%s」，立即点击购买" % text)
                self._soldout_pending = False
                self._goto(
                    POST_PURCHASE,
                    u"已点击购买，等待弹窗处理/返回列表…",
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

    # ---------------- POST_PURCHASE ----------------
    def _update_post_purchase(self, dt, now):
        """
        点击购买后（购买按钮本身不会消失，只以弹窗出现为生效依据）：
        1) BUY_VERIFY_SECONDS 内出现弹窗特征文字 → 点击生效，
           只等待、不点任何弹窗按钮；
        2) 到时仍无弹窗 → 判定无响应，返回列表重新进入再点；
        3) 列表标签+商品双确认回到列表后，进入读取下一场。
        """
        # 1) 点击生效验证：等弹窗出现
        if not self._buy_verified:
            self._elapsed += dt
            if self._popup_visible():
                self._buy_verified = True
                self._log(u"购买弹窗已出现，点击生效，等待处理…")
                if callable(getattr(self, "on_popup_success", None)):
                    try:
                        self.on_popup_success()
                    except Exception:
                        pass
            elif self._elapsed >= BUY_VERIFY_SECONDS:
                self._log(
                    u"点击购买后 %.1f 秒未出现弹窗，"
                    u"返回列表重新进入" % self._elapsed
                )
                self.bridge.back()
                self._goto(ENTER_PRODUCT, u"购买无响应，返回重进…")
                return
            else:
                # 0.3 秒窗口内，继续等弹窗
                return

        # 2) 等待真正回到列表（标签+商品双确认，排除详情页标题）
        center = self._list_ready()
        if center is not None:
            self.recorded_pos = center
            self._log(
                u"已返回列表，重新进入商品读取下一场，位置 (%d, %d)"
                % center
            )
            self.bridge.click_node_by_parts(PRODUCT_KEYWORDS)
            self._goto(READ_DETAIL, u"读取下一场详情…")
            return
        # 弹窗等待：不点击任何按钮，无限等，心跳记录
        self._heartbeat_log(
            dt, u"购买后等待弹窗消失/页面返回列表（不做任何点击）…"
        )
        self.status = u"等待弹窗消失，返回列表…"

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
            self._goto(READ_DETAIL, u"整点进入，识别立即抢购…")
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
                self._goto(READ_DETAIL, u"重新侦察读取详情…")
                return
            # 列表还没准备好：再等一个间隔
            self._log(u"重新侦察：列表未出现商品，继续等待…")
            self._elapsed = 0.0
