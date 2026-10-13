# -*- coding: utf-8 -*-
"""
本机设备标识模块。

获取本机：
- 序列号（SN / adb 设备码）：Build.getSerial()，安卓 10 及以后
  普通应用无权限读取，会返回空或 "unknown"，此时需用户手动填写；
- Android ID：Settings.Secure.ANDROID_ID，无需权限可读。

拼接规则：SN + Android ID，例如
    AYNF99X8WC89BQDQa0445b718d9bdca8
电脑端（非安卓环境）返回空串，文本框可手动编辑。
"""

try:
    from jnius import autoclass
    _ANDROID = True
except Exception:
    autoclass = None
    _ANDROID = False


def _get_serial():
    """读取设备序列号；无权限/失败返回空串"""
    if not _ANDROID:
        return u""
    try:
        build = autoclass("android.os.Build")
        serial = u""
        # 安卓 9+ 推荐 getSerial()，无权限会抛 SecurityException
        try:
            serial = str(build.getSerial())
        except Exception:
            serial = u""
        if not serial:
            try:
                serial = str(build.SERIAL)
            except Exception:
                serial = u""
        if serial in ("unknown", "Unknown", "UNKNOWN", "null", "None"):
            return u""
        return serial
    except Exception:
        return u""


def _get_android_id():
    """读取 Android ID；失败返回空串"""
    if not _ANDROID:
        return u""
    try:
        python_activity = autoclass("org.kivy.android.PythonActivity")
        activity = python_activity.mActivity
        settings_secure = autoclass("android.provider.Settings$Secure")
        content_resolver = activity.getContentResolver()
        android_id = settings_secure.getString(
            content_resolver, settings_secure.ANDROID_ID
        )
        return str(android_id) if android_id else u""
    except Exception:
        return u""


def get_device_code():
    """
    返回 SN + Android ID 拼接结果。
    SN 无权限读到时仅返回 Android ID（文本框可手动补 SN）。
    """
    serial = _get_serial()
    android_id = _get_android_id()
    code = u"%s%s" % (serial, android_id)
    return code
