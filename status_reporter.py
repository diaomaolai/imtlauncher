# -*- coding: utf-8 -*-
"""
卡密 + 抢购状态上报模块（独立功能）。

服务端：设备绑定卡密管理系统（Swagger:
http://120.77.83.232:8239/swagger-ui ），四个接口：
  POST /api/card/login        卡密登录：校验卡密有效性与一机一码绑定，
                              通过后签发 Token（JWT，120 分钟）；
  POST /api/card/info         查询卡密剩余次数 / 到期时间（不扣次）；
  POST /api/card/decrease     扣减一次抢购次数（used_times+1）；
  POST /api/card/rush-record  上报抢购记录（status 0 失败 / 1 成功）。

本模块目前使用 login + rush-record 两个接口：
- 打开 APP 时：先 login（校验卡密+绑定设备），再上报上一场抢购记录；
- 报文原文（也写入 result 字段）：
  机器码;卡密;状态码;日期时间;定时时间
  例：AYNF99X8WC89BQDQa0445b718d9bdca8;7XZJ5-HFTN6-7LN8R-2MD3L;1;
      2026-10-14 08:55:03;09:00:00
- 状态：设置定时时清零（0），确认购买弹窗出现置 1；
  结果本地持久化到 status_report.json，重启不丢。
- 卡密为空或 REPORT_DISABLED=True 时只写日志，不联网。
"""

import json
import os
import threading
from datetime import datetime

from app_logger import resolve_log_dir
from config import (
    CARD_API_BASE,
    CARD_LOGIN_PATH,
    RUSH_RECORD_PATH,
    REPORT_DISABLED,
)

STORE_FILE = u"status_report.json"

# 可读报文：机器码;卡密;状态码;日期时间;定时时间
PAYLOAD_FORMAT = u"%s;%s;%s;%s;%s"


def now_text():
    return datetime.now().strftime(u"%Y-%m-%d %H:%M:%S")


class StatusStore(object):
    """抢购状态与卡密的本地持久化（供下次打开 APP 时上报）"""

    def __init__(self):
        self.path = os.path.join(resolve_log_dir(), STORE_FILE)
        self.data = {
            u"card_no": u"",
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

    def mark_start(self, scheduled_time, card_no=u""):
        """设置定时：新一场开始，状态先置 0（未出现弹窗）"""
        self.data = {
            u"card_no": u"%s" % card_no,
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

    def build_payload(self, device_code, card_no):
        """机器码;卡密;状态码;日期时间;定时时间"""
        rec = self.snapshot()
        return PAYLOAD_FORMAT % (
            device_code,
            card_no,
            rec.get(u"status", 0),
            now_text(),
            rec.get(u"scheduled_time", u""),
        )


def _post_json(url, body, timeout=10):
    """同步 POST JSON，返回 (http_status, 响应字典或文本)"""
    import urllib.request
    data = json.dumps(body, ensure_ascii=False).encode(u"utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=u"POST",
        headers={
            u"Content-Type": u"application/json;charset=utf-8",
            u"Accept": u"application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode(u"utf-8", u"replace")
        http_status = getattr(resp, u"status", 0)
    try:
        return http_status, json.loads(raw)
    except Exception:
        return http_status, raw


def _worker(device_code, card_no, store, logger, emit):
    """后台线程：先登录卡密，再上报抢购记录"""
    try:
        rec = store.snapshot()
        status = int(rec.get(u"status", 0) or 0)
        payload = store.build_payload(device_code, card_no)

        # 1) 卡密登录：校验卡密 + 一机一码绑定
        login_url = CARD_API_BASE + CARD_LOGIN_PATH
        login_body = {
            u"card_no": card_no,
            u"device_id_raw": device_code,
        }
        emit(u"卡密登录请求：POST %s card_no=%s" %
             (login_url, card_no))
        try:
            http_code, resp = _post_json(login_url, login_body)
        except Exception as exc:
            emit(u"卡密登录失败（网络异常）：%s" % exc)
            return
        if not isinstance(resp, dict):
            emit(u"卡密登录失败：响应不是 JSON：%s" % resp)
            return
        if resp.get(u"code") != 200:
            emit(u"卡密登录失败：code=%s message=%s"
                 % (resp.get(u"code"), resp.get(u"message")))
            return
        token = (resp.get(u"data") or {}).get(u"token", u"")
        emit(u"卡密登录成功，Token 已签发（前 12 位）：%s…"
             % (token[:12] if token else u""))

        # 2) 上报抢购记录：card_no/result/status；
        #    result 存放完整可读报文（机器码;卡密;状态码;时间;定时时间）
        record_url = CARD_API_BASE + RUSH_RECORD_PATH
        record_body = {
            u"card_no": card_no,
            u"result": payload,
            u"status": status,
        }
        emit(u"抢购记录上报：%s" % payload)
        try:
            http_code, resp2 = _post_json(record_url, record_body)
        except Exception as exc:
            emit(u"抢购记录上报失败（网络异常）：%s" % exc)
            return
        if isinstance(resp2, dict):
            emit(u"抢购记录上报结果：code=%s message=%s"
                 % (resp2.get(u"code"), resp2.get(u"message")))
        else:
            emit(u"抢购记录上报结果：HTTP %s %s" % (http_code, resp2))
    except Exception as exc:
        emit(u"状态上报异常：%s" % exc)


def send_report(device_code, card_no, store, logger=None):
    """
    打开 APP 时调用：
    - 卡密为空 / REPORT_DISABLED：只打印并记录报文，不联网；
    - 卡密有效：后台线程执行 login + rush-record，不阻塞界面。
    """
    payload = store.build_payload(device_code, card_no)

    def _emit(line):
        if logger is not None:
            logger.log(line)
        else:
            print(line)

    _emit(u"状态上报报文：%s" % payload)

    if REPORT_DISABLED:
        _emit(u"REPORT_DISABLED 已开启，仅记录不发送")
        return
    if not card_no:
        _emit(u"卡密为空，跳过登录与上报（仅记录报文）")
        return

    threading.Thread(
        target=_worker,
        args=(device_code, card_no, store, logger, _emit),
        daemon=True,
    ).start()
