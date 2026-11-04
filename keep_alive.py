# -*- coding: utf-8 -*-
"""
前台保活服务（KeepAliveService）的 Python 侧开关。

背景：抢购助手切到后台后，部分 ROM 会冻结进程，FlowWorker 线程停摆，
日志表现为“到达拉起时刻”晚几十秒、详情页几十秒不刷新。武装时启动
前台服务 + WakeLock，流程结束/取消时停止。电脑端无 jnius 时静默跳过。
"""

SERVICE_CLASS = u"org.personal.imtlauncher.KeepAliveService"

# 本进程是否已启动过保活服务：stop 只在启动过时才真正停止并打日志，
# 防止"未武装时每 0.2 秒调一次 stop"把日志刷屏。
_active = False


def _emit(logger, line):
    """输出一行日志。"""
    if logger is not None:
        logger.log(line)
    else:
        print(line)


def _intent():
    """构造前台保活服务的 Intent。"""
    from jnius import autoclass
    PythonActivity = autoclass(u"org.kivy.android.PythonActivity")
    activity = PythonActivity.mActivity
    if activity is None:
        return None, None
    Intent = autoclass(u"android.content.Intent")
    intent = Intent()
    intent.setClassName(
        activity.getPackageName(), SERVICE_CLASS
    )
    return activity, intent


def start(logger=None):
    """启动前台保活服务；失败不影响主流程"""
    global _active
    try:
        from jnius import autoclass  # noqa: F401
    except Exception:
        return False
    try:
        activity, intent = _intent()
        if activity is None:
            return False
        sdk = autoclass(u"android.os.Build$VERSION").SDK_INT
        if sdk >= 26:
            activity.startForegroundService(intent)
        else:
            activity.startService(intent)
        _active = True
        _emit(logger, u"[keepalive] 前台保活服务已启动")
        return True
    except Exception as exc:
        _emit(logger, u"[keepalive] 启动失败：%s" % exc)
        return False


def stop(logger=None):
    """停止前台保活服务（未启动过则静默返回）"""
    global _active
    if not _active:
        return False
    try:
        from jnius import autoclass  # noqa: F401
    except Exception:
        return False
    try:
        activity, intent = _intent()
        if activity is None:
            return False
        activity.stopService(intent)
        _active = False
        _emit(logger, u"[keepalive] 前台保活服务已停止")
        return True
    except Exception as exc:
        _emit(logger, u"[keepalive] 停止失败：%s" % exc)
        return False
