# -*- coding: utf-8 -*-
"""
抢购状态上报模块（独立功能）。

规则（按用户最新要求）：
- 不再固定每天 12:00 / 00:00 发送；改为「打开启动器 APP 时」发送一次；
- 报文内容：机器码;状态码;日期时间;定时时间
  - 机器码：SN + Android ID（与界面文本框一致）；
  - 状态码：上次抢购出现弹窗=1（成功），未出现弹窗=0（失败）；
  - 日期时间：本次打开 APP 的时间；
  - 定时时间：上次设置的抢购时间（用于区分 9:00 场 / 20:00 场）。
- 状态在本地持久化：设置定时时清零，POST 阶段确认弹窗出现置 1；
  这样下次打开 APP 时读到的就是上一场结果。
- 接口地址在 config.py 的 REPORT_URL 配置；为空时仅记录日志、不发送。
"""

import json
import os
import threading
from datetime import datetime

from app_logger import resolve_log_dir
from config import REPORT_URL

STORE_FILE = u"status_report.json"

# 报文：机器码;状态码;日期时间;定时时间
PAYLOAD_FORMAT = u"%s;%s;%s;%s"


def now_text():
    return datetime.now().strftime(u"%Y-%m-%d %H:%M:%S")


class StatusStore(object):
    """抢购状态持久化（供下次打开 APP 时上报）"""

    def __init__(self):
        self.path = os.path.join(resolve_log_dir(), STORE_FILE)
        self.data = {
            u"scheduled_time": u"",
            u"status": 0,
            u"updated": u"",
        }
        self._load()

    def _load(self):
        try:
            with open(self.path, u"r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self.data.update(loaded)
        except Exception:
            pass

    def _save(self):
        try:
            with open(self.path, u"w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False)
        except Exception:
            pass

    def mark_start(self, scheduled_time):
        """设置定时：新一场开始，状态先置 0（未出现弹窗）"""
        self.data = {
            u"scheduled_time": u"%s" % scheduled_time,
            u"status": 0,
            u"updated": now_text(),
        }
        self._save()

    def mark_success(self):
        """确认弹窗出现：抢购成功，置 1"""
        self.data[u"status"] = 1
        self.data[u"updated"] = now_text()
        self._save()

    def snapshot(self):
        return dict(self.data)

    def build_payload(self, device_code):
        rec = self.snapshot()
        return PAYLOAD_FORMAT % (
            device_code,
            rec.get(u"status", 0),
            now_text(),
            rec.get(u"scheduled_time", u""),
        )


def send_report(device_code, store, logger=None):
    """
    打开 APP 时调用：拼装报文并发送（后台线程，不阻塞界面）。
    接口未配置则只写日志。
    """
    payload = store.build_payload(device_code)

    def _emit(line):
        if logger is not None:
            logger.log(line)
        else:
            print(line)

    _emit(u"状态上报报文：%s" % payload)

    if not REPORT_URL:
        _emit(u"上报接口未配置（REPORT_URL 为空），仅记录不发送")
        return

    def _worker():
        try:
            import urllib.request
            req = urllib.request.Request(
                REPORT_URL,
                data=payload.encode(u"utf-8"),
                method=u"POST",
                headers={
                    u"Content-Type": u"text/plain;charset=utf-8",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                _emit(u"状态上报成功：HTTP %s" % getattr(resp, u"status", u"?"))
        except Exception as exc:
            _emit(u"状态上报失败：%s" % exc)

    threading.Thread(target=_worker, daemon=True).start()
