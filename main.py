# -*- coding: utf-8 -*-
"""
i茅台助手 - 主入口（Buildozer 要求入口文件名必须为 main.py）

功能：
1. 启动展示本机设备 ID，提示复制设备ID联系管理员获取卡密；
2. 输入卡密后点「卡密登录」，POST /api/card/login 授权：
   成功才解锁定时按钮与到点自启动，并调用 /api/card/info 显示
   剩余次数/到期时间；同时补报上一场未上报的抢购记录；
3. 点「设置定时」前再次 POST /api/card/login 校验卡密有效，
   通过才启动抢购流程；
4. 抢购成功（购买弹窗出现）：rush-record(status=1) 上报，
   随后 decrease 扣一次；失败记录本地保留，下次登录补报 0；
5. 抢购流程（i购→经典→飞天→详情按钮）见 flow_core.py。
"""

import threading
import time
from datetime import datetime

from kivy.app import App
from kivy.clock import Clock

from config import APP_TITLE, TICK_INTERVAL
from font_setup import register_cjk_font
from a11y_bridge import A11yBridge
from android_launcher import launch_moutai
from flow_core import (
    FlowCore,
    RAPID_BUY,
    SELECT_YEAR,
    SELECT_QTY,
    WAIT_TIME,
)
from scheduler import parse_target_time, format_remaining
from app_logger import AppLogger
from app_ui import MainScreen
from status_reporter import StatusStore
from card_store import CardStore
import card_client
from slot_monitor import SlotMonitor
from device_profile import ProfileStore, build_fingerprint
from calibration import DeviceCalibrator


class FlowWorker(threading.Thread):
    """
    流程工作线程。

    切换到 i茅台后我们的 Activity 进入后台，Kivy/SDL 主循环
    （Clock）被系统暂停；普通 Python 线程不受前后台影响，因此由本
    线程以固定间隔推进状态机。
    """

    def __init__(self, flow, logger=None, recal_fn=None):
        super(FlowWorker, self).__init__(daemon=True)
        self.flow = flow
        self.logger = logger
        self.recal_fn = recal_fn
        self.stop_event = threading.Event()

    def stop(self):
        self.stop_event.set()

    def run(self):
        last = time.monotonic()
        while not self.stop_event.is_set() and not self.flow.is_done:
            current = time.monotonic()
            dt = current - last
            last = current
            now_dt = datetime.now()
            try:
                self.flow.update(dt, now_dt)
            except Exception as exc:
                if self.logger is not None:
                    self.logger.log(u"流程推进异常: %s" % exc)
                else:
                    print(u"流程推进异常: %s" % exc)

            # 节点持续对不上：停掉本线程，直接在工作线程交主程序重新
            # 校准再武装（不依赖 Clock，后台 Clock 暂停也能执行）
            if self.flow.needs_recalibration \
                    and callable(self.recal_fn):
                self.stop_event.set()
                self.recal_fn()
                return

            # 主动释放本线程上附着的 JNI 环境
            try:
                from jnius import detach
                detach()
            except Exception:
                pass

            # 节拍：
            # - RAPID 连点：0.01s，保证一轮内连续点击间隔约 10ms；
            # - 选年份/改数量/整点等待：0.02s，整点重进后年份+数量
            #   在约 0.1s 内完成，抢购按钮识别点击落在 1 秒内；
            # - 其余状态（导航/读按钮/侦察）：0.3s 动态轮询。
            if self.flow.state == RAPID_BUY:
                self.stop_event.wait(0.01)
            elif self.flow.state in (
                SELECT_YEAR, SELECT_QTY, WAIT_TIME
            ):
                self.stop_event.wait(0.02)
            else:
                self.stop_event.wait(TICK_INTERVAL)


class CalibrationWorker(threading.Thread):
    """
    自动校准工作线程：跑导航链采集节点 bounds 与截图，
    结束后在本工作线程直接回调 on_done；回调内的 UI 操作自行通过
    Clock 切回主线程，保证后台 Clock 暂停时校准武装不被挂起。
    """

    def __init__(self, calibrator, on_done):
        super(CalibrationWorker, self).__init__(daemon=True)
        self.calibrator = calibrator
        self.on_done = on_done

    def run(self):
        try:
            ok, result = self.calibrator.run()
        except Exception as exc:
            ok, result = False, str(exc)
        try:
            from jnius import detach
            detach()
        except Exception:
            pass
        self.on_done(ok, result)


class IMtAssistantApp(App):
    """Kivy 应用主类"""

    def build(self):
        self.title = APP_TITLE

        # 功能模块
        self.app_logger = AppLogger()
        self.bridge = A11yBridge()
        self.flow = FlowCore(self.bridge, self.app_logger)
        self.flow_worker = None
        self.status_store = StatusStore()
        self.profile_store = ProfileStore(logger=self.app_logger)
        self.calibration_worker = None
        self.card_store = CardStore()
        self.card_unlocked = False

        # 界面
        self.screen = MainScreen()
        self.screen.login_btn.bind(on_press=self._on_login_pressed)
        self.screen.schedule_btn.bind(on_press=self._on_schedule_pressed)

        # 回填上次登录成功的卡密，大退重启后无需重新输入
        saved_card = self.card_store.get()
        if saved_card:
            self.screen.card_input.text = saved_card
            self.screen.set_status(
                u"已填入上次使用的卡密，请点击卡密登录"
            )

        # 界面刷新循环（只更新界面；流程推进在工作线程）
        Clock.schedule_interval(self._tick, TICK_INTERVAL)

        # 多场次自启动监控（卡密登录前 enabled=False，空转不动作）
        self.slot_monitor = SlotMonitor(
            is_running_fn=self._is_flow_running,
            autostart_fn=self._auto_arm,
            logger=self.app_logger,
        )
        self.slot_monitor.start()

        return self.screen

    # ---------------- 通用 ----------------
    def _ui(self, fn):
        """把 UI 操作切回 Kivy 主线程执行"""
        Clock.schedule_once(lambda _dt: fn())

    def _card_and_device(self):
        return self.screen.get_card_key(), self.screen.get_device_code()

    def _is_flow_running(self):
        return (
            self.flow_worker is not None
            and not self.flow.is_done
        )

    # ---------------- 自动校准触发 ----------------
    def _ensure_profile(self, after_fn):
        """
        武装前检查本地档案：匹配则直接加载；缺失或 i茅台版本变化
        则自动校准（不抢购），成功后再执行 after_fn 武装流程。
        """
        try:
            fingerprint, _m, _pkg = build_fingerprint()
        except Exception:
            fingerprint = {}
        profile = self.profile_store.find_matching(fingerprint)
        if profile is not None:
            self.flow.profile = profile
            self.app_logger.log(u"已加载匹配设备档案，跳过校准")
            after_fn()
            return

        self._ui(lambda: self.screen.set_status(
            u"首次运行，设备校准中（不抢购）…"))
        self._ui(lambda: setattr(
            self.screen.schedule_btn, u"disabled", True))
        calibrator = DeviceCalibrator(
            self.bridge, self.profile_store, self.app_logger
        )

        def on_done(ok, result):
            # 本回调在 CalibrationWorker 工作线程执行
            if ok:
                self.flow.profile = result
                self._ui(lambda: self.screen.set_status(
                    u"设备校准完成，继续武装"))
                self.app_logger.log(u"校准成功，继续武装流程")
                after_fn()
                return

            def fail_ui():
                self.screen.set_login_button_busy(False)
                self.screen.schedule_btn.disabled = False
                self.screen.set_status(u"设备校准失败：%s" % result)

            self._ui(fail_ui)
            self.app_logger.log(u"设备校准失败：%s" % result)

        self.calibration_worker = CalibrationWorker(calibrator, on_done)
        self.calibration_worker.start()

    # ---------------- 卡密登录 ----------------
    def _on_login_pressed(self, instance):
        """卡密授权登录：login 成功后解锁功能、补报、查卡密信息"""
        card, device = self._card_and_device()
        if not card:
            self.screen.set_status(u"请先填写卡密")
            return
        if not device:
            self.screen.set_status(u"设备 ID 为空，请检查本机设备ID")
            return

        self.screen.set_login_button_busy(True)
        self.screen.set_status(u"正在进行卡密授权登录…")

        def work():
            ok, msg, _data = card_client.card_login(
                card, device, self.app_logger
            )
            if not ok:
                self.app_logger.log(u"卡密登录失败：%s" % msg)

                def fail():
                    self.screen.set_login_button_busy(False)
                    self.card_unlocked = False
                    self.screen.set_unlocked(False)
                    self.slot_monitor.set_enabled(False)
                    self.screen.set_card_info(u"未授权")
                    self.screen.set_status(u"卡密登录失败：%s" % msg)
                self._ui(fail)
                return

            self.app_logger.log(u"卡密登录成功，功能已解锁")
            # 登录成功后：补报上一场记录 + 查询卡密信息
            self._report_pending(card, device)
            info_ok, info_msg, info = card_client.card_info(
                card, device, self.app_logger
            )

            def done():
                self.card_unlocked = True
                # 登录成功后持久化卡密，重启自动回填
                self.card_store.save(card)
                self.screen.set_login_button_busy(False)
                self.screen.set_unlocked(True)
                self.slot_monitor.set_enabled(True)
                if info_ok:
                    used = info.get(u"used_times", u"")
                    expire = info.get(u"expire_at", u"")
                    used_text = u"不限次" if str(used) == "-1" \
                        else u"剩余 %s 次" % used
                    self.screen.set_card_info(
                        u"%s，到期：%s" % (used_text, expire)
                    )
                else:
                    self.screen.set_card_info(
                        u"已授权（信息查询失败：%s）" % info_msg
                    )
                self.screen.set_status(u"卡密授权成功，可设定定时时间")
            self._ui(done)

        threading.Thread(target=work, daemon=True).start()

    # ---------------- 状态上报 / 扣次 ----------------
    def _report_pending(self, card, device):
        """登录成功后补报本地尚未上报的一场结果（不扣次）"""
        if not self.status_store.has_pending():
            return
        payload = self.status_store.build_payload(device, card)
        status = int(self.status_store.snapshot().get(u"status", 0) or 0)
        self.app_logger.log(u"补报上一场抢购记录：%s" % payload)
        ok, msg, _d = card_client.rush_record(
            card, payload, status, self.app_logger
        )
        if ok:
            self.status_store.clear()
            self.app_logger.log(u"上一场记录已补报，本地待报已清空")
        else:
            self.app_logger.log(u"补报失败，保留待下次登录：%s" % msg)

    def _on_popup_success(self):
        """
        识别到购买弹窗（抢购成功）：
        1) 本地状态置 1；
        2) rush-record(status=1) 上报；
        3) decrease 扣一次（成功才扣）；
        4) 上报与扣次成功后清空本地待报。
        """
        self.status_store.mark_success()
        card, device = self._card_and_device()
        payload = self.status_store.build_payload(device, card)
        self.app_logger.log(u"购买弹窗出现，抢购成功：%s" % payload)

        def work():
            ok1, m1, _ = card_client.rush_record(
                card, payload, 1, self.app_logger
            )
            if not ok1:
                self.app_logger.log(
                    u"成功记录上报失败：%s（保留待补报）" % m1
                )
                return
            self.app_logger.log(u"成功记录已上报，调用扣减次数")
            ok2, m2, _ = card_client.card_decrease(
                card, device, self.app_logger
            )
            if ok2:
                self.status_store.clear()
                self.app_logger.log(u"卡密已扣减一次，本地待报已清空")
            else:
                self.app_logger.log(u"扣减次数失败：%s" % m2)

        threading.Thread(target=work, daemon=True).start()

    # ---------------- 定时武装（先校验卡密）----------------
    def _arm_flow(self, target, scheduled_text, immediate_launch=False):
        """
        统一武装核心（可在普通线程安全调用，手动/自启动共用）：
        - 手动定时（immediate_launch=False）：reset(target) 后在后台静默
          等待，不拉起 i茅台；状态机在开售前提前量（config 15 秒）
          才经 on_launch_app 自行拉起，导航到详情读开售时间，未来则
          WAIT 到整点，到点节点确认进入抢购；
        - 自启动（immediate_launch=True）：slot_monitor 已提前触发，
          launch_target=now，立即拉起并导航，后续同样 WAIT 到整点。
        界面更新单独走 Clock，延迟或冻结不影响工作线程武装与抢购。
        """
        card = self.screen.get_card_key()
        self.flow.year_target = self.screen.get_year_text()
        if immediate_launch:
            self.flow.reset(target, launch_target=datetime.now())
        else:
            # launch_target 自动 = target - MANUAL_LAUNCH_LEAD_SECONDS
            self.flow.reset(target)
        self.status_store.mark_start(scheduled_text, card)
        self.flow.on_popup_success = self._on_popup_success
        # 注入拉起回调：状态机在 IDLE/WAIT 需要时自行拉起，
        # 已在前台时 launch 幂等无副作用
        self.flow.on_launch_app = lambda: launch_moutai(self.app_logger)
        self.app_logger.log(u"设备标识：%s" % self.screen.get_device_code())
        self.app_logger.log(u"选择年份：%s" % self.flow.year_target)

        self.flow_worker = FlowWorker(
            self.flow, self.app_logger,
            recal_fn=self._on_runtime_recal_requested,
        )
        self.flow_worker.start()

        self._ui(lambda: self.screen.set_schedule_button_armed(True))
        if immediate_launch:
            self._ui(lambda: self.screen.set_status(
                u"已自启动武装，导航到详情，到点抢购"))
        else:
            self._ui(lambda: self.screen.set_status(
                u"已武装，后台等待，到点自行拉起抢购"))

    def _arm_schedule(self, target):
        """手动定时武装（卡密校验通过后，工作线程调用）"""
        self._arm_flow(target, target.strftime(u"%H:%M:%S"))

    def _on_schedule_pressed(self, instance):
        """设置定时 / 取消定时 按钮回调"""
        if self.flow_worker is not None and not self.flow.is_done:
            self._disarm(u"已取消定时")
            # 手动取消：清空待报，避免把未开始的一场记为失败
            self.status_store.clear()
            return

        if not self.card_unlocked:
            self.screen.set_status(u"请先完成卡密登录")
            return

        card, device = self._card_and_device()
        if not card:
            self.screen.set_status(u"请先填写卡密并登录")
            return

        try:
            target = parse_target_time(self.screen.get_time_text())
        except ValueError as exc:
            self.screen.set_status(str(exc))
            return

        self.screen.set_status(u"正在校验卡密有效性…")
        self.screen.schedule_btn.disabled = True

        def work():
            ok, msg, _data = card_client.card_login(
                card, device, self.app_logger
            )
            if not ok:
                self.app_logger.log(u"定时前卡密校验失败：%s" % msg)

                def fail():
                    self.card_unlocked = False
                    self.screen.set_unlocked(False)
                    self.slot_monitor.set_enabled(False)
                    self.screen.set_status(u"卡密校验失败：%s" % msg)
                self._ui(fail)
                return
            self.app_logger.log(u"定时前卡密校验通过")
            # 直接在工作线程执行（不依赖 Clock，后台 Clock 暂停也能武装）
            self._ensure_profile(
                lambda: self._arm_schedule(target)
            )

        threading.Thread(target=work, daemon=True).start()

    def _auto_arm(self, target):
        """
        场次提前自启动武装（slot_monitor 线程调用，target 为场次整点）。
        先停旧流程，再在本线程直接校准建档/武装，统一走 _arm_flow
        （immediate_launch=True）：立即拉起 i茅台 + 当场导航，读到未来
        时间后 WAIT 到整点，上报记录的 scheduled_time 写场次整点。
        """
        if self.flow_worker is not None:
            self.flow_worker.stop()
            self.flow_worker = None

        self._ensure_profile(
            lambda: self._arm_flow(
                target, target.strftime(u"%H:%M:00"),
                immediate_launch=True,
            )
        )

    def _on_runtime_recal_requested(self):
        """
        运行时节点对不上（停滞阈值触发）：停掉旧流程，重新走校准链
        生成新档案，再按原目标场次重新武装；原目标已过则立即开始。
        """
        if self.flow_worker is not None:
            self.flow_worker.stop()
            self.flow_worker = None
        self._ui(lambda: self.screen.set_status(
            u"节点对不上，自动重新校准中…"))
        self.app_logger.log(u"运行时节点对不上，开始自动重新校准")
        calibrator = DeviceCalibrator(
            self.bridge, self.profile_store, self.app_logger
        )

        def on_done(ok, result):
            # 在 CalibrationWorker 工作线程执行
            if not ok:
                self._ui(lambda: self.screen.set_status(
                    u"重新校准失败：%s" % result))
                self.app_logger.log(u"运行时重新校准失败：%s" % result)
                return
            self.flow.profile = result
            self.app_logger.log(u"运行时重新校准完成，重新武装")
            target = self.flow.first_target or datetime.now()
            self._arm_schedule(target)

        self.calibration_worker = CalibrationWorker(calibrator, on_done)
        self.calibration_worker.start()

    def _disarm(self, status_text=None):
        """取消定时并恢复界面"""
        if self.flow_worker is not None:
            self.flow_worker.stop()
            self.flow_worker = None
        self.screen.set_schedule_button_armed(False)
        self.screen.set_countdown(u"倒计时：未设定")
        if status_text:
            self.screen.set_status(status_text)

    # ---------------- 界面刷新 ----------------
    def _tick(self, dt):
        if self.flow.is_done:
            # 不再 finish 杀进程：保留进程与监控守护线程盯后续场次，
            # 退出由用户手动操作（request_app_exit 仅记录，不再执行）。
            self.screen.set_status(self.flow.status)
            self._disarm(self.flow.status)
            return
        if self.flow_worker is None:
            return

        now_dt = datetime.now()
        target_dt = self.flow.display_target
        if target_dt is not None:
            remaining = (target_dt - now_dt).total_seconds()
            self.screen.set_countdown(
                u"倒计时：%s" % format_remaining(remaining)
            )
        self.screen.set_status(self.flow.status)

    def on_resume(self):
        """从后台切回：Clock 恢复，立即刷新一次倒计时与状态，
        避免停留在后台期间的冻结值（如 10:58）。"""
        self._tick(0)

    def on_pause(self):
        # 允许后台驻留：返回 True，普通线程（FlowWorker/SlotMonitor）
        # 在后台继续等待与抢购
        return True


def main():
    register_cjk_font()
    IMtAssistantApp().run()


if __name__ == "__main__":
    main()
