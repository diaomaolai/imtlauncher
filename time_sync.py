# -*- coding: utf-8 -*-
"""
服务器时间校准：算出「服务器时间 − 手机本地时间」的偏移（秒）。

抢购成败由服务器整点决定，手机时钟漂移几百毫秒~几秒都会让第一击
早/晚。每次武装前校准一次，流程里所有整点判定改用 手机时间+偏移。

- 首选 NTP（UDP 123，毫秒级，纯标准库，无新依赖）；
- NTP 被运营商拦（UDP 受限）→ 退回读 HTTPS 响应 Date 头（秒级）；
- 两者都失败返回 None，调用方按偏移 0（纯手机时间）运行并记日志。

用法：
    offset, source = fetch_offset()   # offset: float 秒；source: NTP/HTTP-Date/None
"""

import socket
import struct
import time
import urllib.request
from datetime import datetime
from email.utils import parsedate_to_datetime

NTP_EPOCH = 2208988800  # NTP 1900 年与 Unix 1970 年的秒差
NTP_HOST = u"ntp.aliyun.com"
NTP_PORT = 123
HTTP_DATE_URL = u"https://www.baidu.com/"
MAX_ABS_OFFSET = 120.0  # 偏移超过 ±120 秒视为不可信（手机时间太离谱）


def parse_ntp_response(data):
    """
    解析 NTP 48 字节应答，返回 (transmit_unix_seconds, fraction)。
    纯函数，方便单测。
    """
    if len(data) < 48:
        raise ValueError(u"NTP 应答不足 48 字节")
    tx = struct.unpack(u"!I", data[40:44])[0]
    frac = struct.unpack(u"!I", data[44:48])[0]
    return tx - NTP_EPOCH + frac / float(2 ** 32)


def ntp_offset(host=NTP_HOST, port=NTP_PORT, timeout=1.0):
    """
    向 NTP 服务器取偏移（秒）。返回服务器时间与本地时间的差。
    """
    packet = b"\x1b" + 47 * b"\x00"  # LI=0 VN=3 Mode=3（客户端）
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sent_at = time.monotonic()
        sock.sendto(packet, (host, port))
        data, _addr = sock.recvfrom(1024)
        got_at = time.monotonic()
    server_epoch = parse_ntp_response(data)
    rtt = got_at - sent_at
    # 服务器发射时刻 + 半程往返 ≈ 当前服务器时间
    server_now = server_epoch + rtt / 2.0
    return server_now - time.time()


def parse_http_date(header_value):
    """解析 HTTP Date 头（RFC 1123）为 Unix 时间戳。纯函数。"""
    if not header_value:
        raise ValueError(u"无 Date 头")
    return parsedate_to_datetime(header_value).timestamp()


def http_date_offset(url=HTTP_DATE_URL, timeout=2.0):
    """
    读 HTTPS 响应 Date 头算偏移。以「请求发出/收到中间时刻」为本地
    时间基准，抵消网络单程误差（秒级精度）。
    """
    before = time.time()
    request = urllib.request.Request(url, headers={u"User-Agent": u"Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        header = resp.headers.get(u"Date")
        after = time.time()
    server_epoch = parse_http_date(header)
    local_mid = (before + after) / 2.0
    return server_epoch - local_mid


def fetch_offset():
    """
    取一次时间偏移：先 NTP 后 HTTP Date。
    返回 (offset, source)；失败返回 (None, None)。
    """
    try:
        offset = ntp_offset()
        if abs(offset) <= MAX_ABS_OFFSET:
            return offset, u"NTP"
    except Exception:
        pass
    try:
        offset = http_date_offset()
        if abs(offset) <= MAX_ABS_OFFSET:
            return offset, u"HTTP-Date"
    except Exception:
        pass
    return None, None


if __name__ == u"__main__":
    offset, source = fetch_offset()
    if source is None:
        print(u"校准失败（NTP/HTTP-Date 都不可用）")
    else:
        print(u"来源 %s，偏移 %.3f 秒（服务器时间 − 手机时间）"
              % (source, offset))
        print(u"手机现在：%s" % datetime.now())
        print(u"服务器现在：%s" % (datetime.fromtimestamp(
            time.time() + offset)))
