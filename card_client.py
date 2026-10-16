# -*- coding: utf-8 -*-
"""
卡密接口客户端模块（四个接口，全部 POST JSON，HTTPS）。

服务端：https://www.20471.top
统一返回：{"code": 200, "message": "success", "data": {...}}

接口：
  card_login(card_no, device_id)
      POST /api/card/login  前端卡密授权登录
      请求 {"card_no": 卡密, "device_id_raw": 机器码}
      成功 data: {"card_no", "device_id_raw", "token"(JWT 120 分钟)}

  card_info(card_no, device_id)
      POST /api/card/info   前端卡密信息查询（不扣次）
      请求同上
      成功 data: {"card_no", "used_times"(剩余次数，-1 不限),
                  "expire_at"(到期时间)}

  card_decrease(card_no, device_id)
      POST /api/card/decrease  前端卡密减次数（used_times + 1）
      请求同上

  rush_record(card_no, result, status)
      POST /api/card/rush-record  上报抢购记录
      请求 {"card_no", "result": 结果详情, "status": 0失败/1成功}

所有函数均为同步调用，返回 (ok: bool, message: str, data: dict)，
网络异常也以 ok=False 返回，不抛异常；网络请求请放在后台线程。
"""

import json
import ssl

from config import (
    CARD_API_BASE,
    CARD_LOGIN_PATH,
    CARD_INFO_PATH,
    CARD_DECREASE_PATH,
    RUSH_RECORD_PATH,
    CARD_HTTP_TIMEOUT,
    REPORT_DISABLED,
)


def _verified_context():
    """
    优先使用 certifi 内置 CA 根证书库（安卓打包内置）；
    没有 certifi 时退回系统默认信任库。
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _unverified_context():
    """最后兜底：跳过证书校验（仅在证书链异常时一次性降级使用）"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _is_cert_error(exc):
    """判断是否为证书校验类错误"""
    if isinstance(exc, ssl.SSLError):
        text = u"%s" % exc
        return (
            u"CERTIFICATE" in text
            or u"certificate" in text
            or u"issuer" in text
        )
    return False


def _post_json(path, body, timeout=None, context=None):
    """同步 POST JSON，返回 (http_status, dict|str)。异常向上抛。"""
    import urllib.request

    url = CARD_API_BASE + path
    if timeout is None:
        timeout = CARD_HTTP_TIMEOUT
    data = json.dumps(body, ensure_ascii=False).encode(u"utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=u"POST",
        headers={
            u"Content-Type": u"application/json;charset=utf-8",
            u"Accept": u"application/json",
            u"User-Agent": u"imtlauncher",
        },
    )
    if context is None:
        context = _verified_context()
    with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
        raw = resp.read().decode(u"utf-8", u"replace")
        http_status = getattr(resp, u"status", 0)
    try:
        return http_status, json.loads(raw)
    except Exception:
        return http_status, raw


def _result(path, body, log=None):
    """
    统一执行：REPORT_DISABLED 直接返回禁用；
    成功判定 code == 200；任何异常都包装成 (False, message, {})。
    证书校验失败时降级为不校验证书重试一次（保证弱环境可达）。
    """
    def _emit(line):
        if log is not None:
            try:
                log(line)
            except Exception:
                pass

    if REPORT_DISABLED:
        _emit(u"REPORT_DISABLED 已开启，跳过请求 %s" % path)
        return False, u"本地调试模式，未联网", {}

    try:
        http_code, resp = _post_json(path, body)
    except Exception as exc:
        if _is_cert_error(exc):
            _emit(u"请求 %s 证书校验失败（%s），降级为不校验证书重试"
                  % (path, exc))
            try:
                http_code, resp = _post_json(
                    path, body, context=_unverified_context()
                )
            except Exception as exc2:
                _emit(u"请求 %s 降级后仍失败：%s" % (path, exc2))
                return False, u"网络异常：%s" % exc2, {}
        else:
            _emit(u"请求 %s 网络异常：%s" % (path, exc))
            return False, u"网络异常：%s" % exc, {}

    if not isinstance(resp, dict):
        _emit(u"请求 %s 响应非 JSON：%s" % (path, resp))
        return False, u"服务器响应异常", {}

    ok = (resp.get(u"code") == 200)
    message = u"%s" % resp.get(u"message", u"")
    data = resp.get(u"data") or {}
    if not isinstance(data, dict):
        data = {}
    _emit(u"POST %s -> code=%s message=%s"
          % (path, resp.get(u"code"), message))
    return ok, message, data


def card_login(card_no, device_id, log=None):
    """前端卡密授权登录。成功返回 (True, message, data 含 token)。"""
    body = {
        u"card_no": u"%s" % card_no,
        u"device_id_raw": u"%s" % device_id,
    }
    return _result(CARD_LOGIN_PATH, body, log)


def card_info(card_no, device_id, log=None):
    """前端卡密信息查询（剩余次数/到期时间，不扣次）。"""
    body = {
        u"card_no": u"%s" % card_no,
        u"device_id_raw": u"%s" % device_id,
    }
    return _result(CARD_INFO_PATH, body, log)


def card_decrease(card_no, device_id, log=None):
    """前端卡密减次数：抢购成功后调用一次。"""
    body = {
        u"card_no": u"%s" % card_no,
        u"device_id_raw": u"%s" % device_id,
    }
    return _result(CARD_DECREASE_PATH, body, log)


def rush_record(card_no, result, status, log=None):
    """
    上报抢购记录。
    status: 1=成功（弹窗出现），0=失败；
    result: 完整可读报文 机器码;卡密;状态码;日期时间;定时时间。
    """
    body = {
        u"card_no": u"%s" % card_no,
        u"result": u"%s" % result,
        u"status": int(1 if status else 0),
    }
    return _result(RUSH_RECORD_PATH, body, log)
