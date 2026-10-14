# -*- coding: utf-8 -*-
"""
Android 原生启动模块（预留：多场次自动拉起 i茅台）。

通过 pyjnius 调用系统 PackageManager，按包名启动 i茅台
（com.moutai.mall），等价于在桌面点击图标。
电脑端无 jnius 时只打印日志，不执行任何操作。
"""

# i茅台包名
MOUTAI_PACKAGE = u"com.moutai.mall"


def launch_app(package_name, logger=None):
    """
    按包名拉起已安装 APP。
    返回 True 表示成功下发启动意图，False 表示未找到 / 不在安卓环境。
    """
    def _emit(line):
        if logger is not None:
            logger.log(line)
        else:
            print(line)

    try:
        from jnius import autoclass
    except Exception:
        _emit(u"[launch] 非安卓环境（无 jnius），仅模拟启动：%s"
              % package_name)
        return False

    try:
        PythonActivity = autoclass(u"org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity
        if activity is None:
            _emit(u"[launch] Activity 未就绪，无法启动：%s" % package_name)
            return False

        pm = activity.getPackageManager()
        intent = pm.getLaunchIntentForPackage(package_name)
        if intent is None:
            _emit(u"[launch] 未找到已安装应用：%s" % package_name)
            return False

        # FLAG_ACTIVITY_NEW_TASK(0x10000000) |
        # FLAG_ACTIVITY_RESET_TASK_IF_NEEDED(0x00200000)
        intent.addFlags(0x10200000)
        activity.startActivity(intent)
        _emit(u"[launch] 已自动拉起 APP：%s" % package_name)
        return True
    except Exception as exc:
        _emit(u"[launch] 启动 %s 异常：%s" % (package_name, exc))
        return False


def launch_moutai(logger=None):
    """拉起 i茅台"""
    return launch_app(MOUTAI_PACKAGE, logger)
