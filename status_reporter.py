# -*- coding: utf-8 -*-
"""
抢购状态本地存储 + 可读报文拼装模块。

实际网络请求在 card_client.py（四个接口）。

状态流转：
- 设置定时/卡密登录解锁后开始一场：mark_start(定时时间, 卡密) -> 0
- 识别到购买弹窗（抢购成功）：mark_success() -> 1
- 主程序在成功时调用 card_client.rush_record(1) 上报，
  随后 card_client.card_decrease() 扣一次，成功后 clear()
- 失败（无弹窗）场次：本地保留 status=0，下次卡密登录成功后
  补报一次 rush-record(0)，成功后 clear()

可读报文（result 字段）：
  机器码;卡密;状态码;日期时间;定时时间
  例：AYNF99X8WC89BQDQa0445b718d9bdca8;7XZJ5-HFTN6-7LN8R-2MD3L;1;
      2026-10-14 08:55:03;09:00:00
"""

import json
import os
from datetime import datetime

from app_logger import resolve_log_dir

STORE_FILE = u"status_report.json"

# 可读报文：机器码;卡密;状态码;日期时间;定时时间
PAYLOAD_FORMAT = u"%s;%s;%s;%s;%s"


def now_text():
    return datetime.now().strftime(u"%Y-%m-%d %H:%M:%S")


class StatusStore(object):
    """抢购状态与卡密的本地持久化（重启不丢）"""

    def __init__(self):
        self.path = os.path.join(resolve_log_dir(), STORE_FILE)
        self.data = {
            u"card_no": u"",
            u"scheduled_time": u"",
            u"status": 0,
            u"updated": u"",
            u"reported": 1,
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

    def mark_start(self, scheduled_time, card_no=u""):
        """新一场开始：状态置 0（未出现弹窗），等待上报"""
        self.data = {
            u"card_no": u"%s" % card_no,
            u"scheduled_time": u"%s" % scheduled_time,
            u"status": 0,
            u"updated": now_text(),
            u"reported": 0,
        }
        self._save()

    def mark_success(self):
        """确认弹窗出现：抢购成功，置 1"""
        self.data[u"status"] = 1
        self.data[u"updated"] = now_text()
        self.data[u"reported"] = 0
        self._save()

    def clear(self):
        """记录已成功上报，清空待报状态，避免下次重复上报"""
        self.data[u"scheduled_time"] = u""
        self.data[u"status"] = 0
        self.data[u"reported"] = 1
        self.data[u"updated"] = now_text()
        self._save()

    def has_pending(self):
        """是否有一场结果尚未上报（已设定过定时）"""
        return bool(self.data.get(u"scheduled_time"))

    def snapshot(self):
        return dict(self.data)

    def build_payload(self, device_code, card_no, now=None):
        """机器码;卡密;状态码;日期时间;定时时间"""
        rec = self.snapshot()
        return PAYLOAD_FORMAT % (
            device_code,
            card_no,
            rec.get(u"status", 0),
            now or now_text(),
            rec.get(u"scheduled_time", u""),
        )
