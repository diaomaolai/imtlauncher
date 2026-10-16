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
from flow_core import FlowCore
from scheduler import parse_target_time, format_remaining
from app_logger import AppLogger
from app_ui import MainScreen
from status_reporter import StatusStore
import card_client
from slot_monitor import SlotMonitor


class FlowWorker(threading.Thread):
    """
    流程工作线程。

    切换到 i茅台后我们的 Activity 进入后台，Kivy/SDL 主循环
    （Clock）被系统暂停；普通 Python 线程不受前后台影响，因此由本
    线程以固定间隔推进状态机。
    """

    def __init__(self, flow, logger=None):
        super(FlowWorker, self).__init__(daemon=True)
        self.flow = flow
        self.logger = logger
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

            # 主动释放本线程上附着的 JNI 环境
            try:
                from jnius import detach
                detach()
            except Exception:
                pass

            self.stop_event.wait(TICK_INTERVAL)


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
        self.card_unlocked = False

        # 界面
        self.screen = MainScreen()
        self.screen.login_btn.bind(on_press=self._on_login_pressed)
        self.screen.schedule_btn.bind(on_press=self._on_schedule_pressed)

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
    def _arm_schedule(self, target):
        """真正武装流程（卡密校验通过后调用）"""
        self.flow.reset(target)
        self.status_store.mark_start(
            target.strftime(u"%H:%M:%S"),
            self.screen.get_card_key(),
        )
        self.flow.on_popup_success = self._on_popup_success
        self.app_logger.log(u"设备标识：%s" % self.screen.get_device_code())

        self.flow_worker = FlowWorker(self.flow, self.app_logger)
        self.flow_worker.start()
        self.screen.set_schedule_button_armed(True)
        self.screen.set_status(
            u"已设定：%s" % target.strftime(u"%Y-%m-%d %H:%M:%S")
        )

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
            self._ui(lambda: self._arm_schedule(target))

        threading.Thread(target=work, daemon=True).start()

    def _auto_arm(self, target):
        """
        场次到点自动武装（slot_monitor 线程调用）：
        先停旧流程，再以该时刻立即启动（卡密已登录才会进入这里）。
        """
        if self.flow_worker is not None:
            self.flow_worker.stop()
            self.flow_worker = None

        def armed():
            self.flow.reset(target)
            self.status_store.mark_start(
                target.strftime(u"%H:%M:00"),
                self.screen.get_card_key(),
            )
            self.flow.on_popup_success = self._on_popup_success
            self.app_logger.log(
                u"设备标识：%s" % self.screen.get_device_code()
            )

            self.flow_worker = FlowWorker(self.flow, self.app_logger)
            self.flow_worker.start()
            self.screen.set_schedule_button_armed(True)
            self.screen.set_status(
                u"场次自启动：%s" % target.strftime(u"%Y-%m-%d %H:%M:%S")
            )
        self._ui(armed)

    def _disarm(self, status_text=None):
        """取消定时并恢复界面"""
        if self.flow_worker is not None:
            self.flow_worker.stop()
            self.flow_worker = None
        self.screen.set_schedule_button_armed(False)
        self.screen.set_countdown(u"倒计时：未设定")
        if status_text:
            self.screen.set_status(status_text)

    def _close_android_activity(self):
        """结束启动器 APP（已售罄分支）；电脑端不执行"""
        try:
            from jnius import autoclass
            PythonActivity = autoclass(u"org.kivy.android.PythonActivity")
            activity = PythonActivity.mActivity
            if activity is not None:
                activity.finish()
        except Exception:
            pass

    # ---------------- 界面刷新 ----------------
    def _tick(self, dt):
        if self.flow.is_done:
            should_exit = self.flow.request_app_exit
            self.screen.set_status(self.flow.status)
            self._disarm(self.flow.status)
            if should_exit:
                self._close_android_activity()
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


def main():
    register_cjk_font()
    IMtAssistantApp().run()


if __name__ == "__main__":
    main()
