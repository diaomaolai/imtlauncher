# -*- coding: utf-8 -*-
"""
安卓应用启动模块

通过 pyjnius 调用 Android 原生 PackageManager / Intent，
检测并启动手机上已安装的第三方 APP（i茅台）。

在非安卓环境（电脑端调试）下 pyjnius 不可用，本模块安全降级，
界面仍可正常预览。
"""

from config import TARGET_PACKAGE, SCAN_KEYWORDS

# pyjnius 只存在于 python-for-android 打包后的安卓环境
try:
    from jnius import autoclass
    _ANDROID = True
except Exception:
    autoclass = None
    _ANDROID = False


class AndroidLauncher(object):
    """封装第三方 APP 的检测、扫描与启动"""

    def __init__(self):
        self.activity = None
        self.package_manager = None
        self.intent_class = None
        if _ANDROID:
            self._init_native()

    def _init_native(self):
        """初始化安卓原生上下文；失败时抛出带说明的异常"""
        try:
            python_activity = autoclass("org.kivy.android.PythonActivity")
            self.activity = python_activity.mActivity
            self.package_manager = self.activity.getPackageManager()
            self.intent_class = autoclass("android.content.Intent")
        except Exception as exc:
            raise RuntimeError(u"Android 原生环境初始化失败: %s" % exc)

    @property
    def is_android(self):
        """当前是否运行在安卓设备上"""
        return _ANDROID

    def is_installed(self, package_name=TARGET_PACKAGE):
        """检测指定包名的 APP 是否已安装（存在可启动入口即视为已安装）"""
        if not _ANDROID:
            return False
        try:
            launch_intent = self.package_manager.getLaunchIntentForPackage(
                package_name
            )
            return launch_intent is not None
        except Exception:
            # 部分 ROM 对未声明可见性的包会直接抛异常
            return False

    def scan_moutai_packages(self):
        """
        兜底方案：扫描手机上已安装的应用，
        返回 [(包名, 应用显示名), ...]，命中茅台相关关键字的应用。
        安卓 11+ 需 QUERY_ALL_PACKAGES 权限才能扫全。
        """
        results = []
        if not _ANDROID:
            return results
        try:
            installed = self.package_manager.getInstalledApplications(0)
            for app_info in installed:
                pkg = app_info.packageName
                label = self.package_manager.getApplicationLabel(
                    app_info
                ).toString()
                hay = (pkg + label).lower()
                if any(keyword.lower() in hay for keyword in SCAN_KEYWORDS):
                    results.append((pkg, label))
        except Exception:
            return results
        return results

    def launch(self, package_name=TARGET_PACKAGE):
        """
        启动指定 APP。
        成功返回 (True, 提示信息)；失败返回 (False, 原因)。
        """
        if not _ANDROID:
            return False, u"当前不是安卓环境，电脑端仅可预览界面"
        try:
            launch_intent = self.package_manager.getLaunchIntentForPackage(
                package_name
            )
            if launch_intent is None:
                return False, u"未检测到该应用，请先安装 i茅台"
            # 以新任务栈方式拉起，避免退回时停留在异常栈
            launch_intent.addFlags(
                self.intent_class.FLAG_ACTIVITY_NEW_TASK
            )
            self.activity.startActivity(launch_intent)
            return True, u"正在启动 i茅台…"
        except Exception as exc:
            return False, u"启动失败: %s" % exc

    def toast(self, text):
        """弹出安卓原生 Toast 提示；非安卓环境静默忽略"""
        if not _ANDROID:
            return
        try:
            toast_class = autoclass("android.widget.Toast")
            java_string = autoclass("java.lang.String")
            toast_class.makeText(
                self.activity, java_string(text), toast_class.LENGTH_SHORT
            ).show()
        except Exception:
            pass
