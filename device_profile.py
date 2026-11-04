# -*- coding: utf-8 -*-
"""
设备档案模块（设备校准建档）。

职责：
1. 采集本机原生指标：品牌、型号、系统版本、物理分辨率、密度；
2. 采集 i茅台 包信息：版本号、版本码、应用标签、签名 SHA-256；
3. 计算设备指纹，档案按 品牌+型号+分辨率+密度+i茅台版本 区分；
4. 档案落盘应用私有目录 profiles/：JSON 机器读 + TXT 可读说明。

非安卓环境（电脑端）所有原生采集安全降级为空值，存取逻辑可独立测试。
"""

import hashlib
import json
import os
import re

from datetime import datetime

PROFILE_SCHEMA = 1
PROFILE_DIR_NAME = u"profiles"
MOUTAI_PACKAGE = u"com.moutai.mall"

# 指纹匹配必须一致的字段（任一不同即视为新设备/新版本，需重新校准）
FINGERPRINT_KEYS = (
    u"brand", u"model", u"android_sdk",
    u"screen_w", u"screen_h", u"density",
    u"moutai_package", u"moutai_version",
    u"moutai_version_code",
)


# ------------------------------------------------------------------
# 目录定位
# ------------------------------------------------------------------

def resolve_files_dir():
    """
    应用私有外部文件目录（与日志目录同级）。
    非安卓环境退回当前工作目录。
    """
    try:
        from jnius import autoclass
        PythonActivity = autoclass(u"org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity
        if activity is None:
            return os.getcwd()
        ctx = activity.getApplicationContext()
        files = ctx.getExternalFilesDir(None)
        if files is not None:
            return str(files.getAbsolutePath())
        return str(ctx.getFilesDir().getAbsolutePath())
    except Exception:
        return os.getcwd()


# ------------------------------------------------------------------
# 原生指标与包信息采集
# ------------------------------------------------------------------

def read_native_metrics():
    """读取品牌/型号/系统/物理屏/密度；非安卓环境返回空字典"""
    try:
        from jnius import autoclass
        Build = autoclass(u"android.os.Build")
        PythonActivity = autoclass(u"org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity
        ctx = activity.getApplicationContext()
        wm = ctx.getSystemService(u"window")
        display = wm.getDefaultDisplay()
        metrics = autoclass(u"android.util.DisplayMetrics")()
        display.getRealMetrics(metrics)
        return {
            u"brand": str(Build.MANUFACTURER),
            u"model": str(Build.MODEL),
            u"android_release": str(Build.VERSION.RELEASE),
            u"android_sdk": int(Build.VERSION.SDK_INT),
            u"screen_w": int(metrics.widthPixels),
            u"screen_h": int(metrics.heightPixels),
            u"density": float(metrics.density),
            u"density_dpi": int(metrics.densityDpi),
        }
    except Exception:
        return {}


def read_package_info(pkg=MOUTAI_PACKAGE):
    """
    读取指定包的版本/标签/签名 SHA-256。
    GET_SIGNATURES(=64) 在全版本可用；未安装返回 installed=False。
    """
    result = {u"package": pkg, u"installed": False}
    try:
        from jnius import autoclass
        PythonActivity = autoclass(u"org.kivy.android.PythonActivity")
        ctx = PythonActivity.mActivity.getApplicationContext()
        pm = ctx.getPackageManager()
        info = pm.getPackageInfo(pkg, 64)
        result[u"label"] = str(info.applicationInfo.loadLabel(pm))
        result[u"version_name"] = str(info.versionName)
        result[u"version_code"] = int(info.versionCode)
        sig_hash = u""
        signatures = info.signatures
        if signatures is not None and len(signatures) > 0:
            raw = bytes(signatures[0].toByteArray())
            sig_hash = hashlib.sha256(raw).hexdigest()
        result[u"signature_sha256"] = sig_hash
        result[u"installed"] = True
    except Exception:
        pass
    return result


def build_fingerprint():
    """
    汇总当前设备指纹，返回 (fingerprint, metrics, package_info)。
    指纹字段缺失时保留空值，由调用方判断是否可校准。
    """
    metrics = read_native_metrics()
    package = read_package_info()
    fingerprint = {
        u"brand": metrics.get(u"brand", u""),
        u"model": metrics.get(u"model", u""),
        u"android_release": metrics.get(u"android_release", u""),
        u"android_sdk": metrics.get(u"android_sdk", 0),
        u"screen_w": metrics.get(u"screen_w", 0),
        u"screen_h": metrics.get(u"screen_h", 0),
        u"density": metrics.get(u"density", 0.0),
        u"density_dpi": metrics.get(u"density_dpi", 0),
        u"moutai_package": package.get(u"package", pkg_default()),
        u"moutai_version": package.get(u"version_name", u""),
        u"moutai_version_code": package.get(u"version_code", 0),
        u"signature_sha256": package.get(u"signature_sha256", u""),
        u"app_label": package.get(u"label", u""),
        u"installed": bool(package.get(u"installed", False)),
    }
    return fingerprint, metrics, package


def pkg_default():
    """默认 i茅台包名。"""
    return MOUTAI_PACKAGE


# ------------------------------------------------------------------
# 档案数据类
# ------------------------------------------------------------------

class DeviceProfile(object):
    """单台设备的参数档案"""

    def __init__(self, fingerprint=None, controls=None,
                 metrics=None, screenshots=None):
        """初始化 DeviceProfile 实例。"""
        self.fingerprint = fingerprint or {}
        self.controls = controls or {}
        self.metrics = metrics or {}
        self.screenshots = screenshots or []
        self.collected_at = datetime.now().strftime(u"%Y-%m-%d %H:%M:%S")

    def to_dict(self):
        """序列化为字典。"""
        return {
            u"schema": PROFILE_SCHEMA,
            u"collected_at": self.collected_at,
            u"fingerprint": self.fingerprint,
            u"metrics": self.metrics,
            u"controls": self.controls,
            u"screenshots": self.screenshots,
        }

    @classmethod
    def from_dict(cls, data):
        """从字典还原档案。"""
        profile = cls(
            fingerprint=data.get(u"fingerprint", {}),
            controls=data.get(u"controls", {}),
            metrics=data.get(u"metrics", {}),
            screenshots=data.get(u"screenshots", []),
        )
        profile.collected_at = data.get(
            u"collected_at", profile.collected_at
        )
        return profile

    def matches(self, fingerprint):
        """指纹关键字段全部一致才认定为同一设备同一版本"""
        for key in FINGERPRINT_KEYS:
            if self.fingerprint.get(key) != fingerprint.get(key):
                return False
        return True


# ------------------------------------------------------------------
# 档案存取
# ------------------------------------------------------------------

def _safe_name(value):
    """文件名安全化（去掉路径非法字符）。"""
    return re.sub(r"[^A-Za-z0-9_.-]+", u"_", str(value)).strip(u"_")


class ProfileStore(object):
    """profiles/ 目录下的档案读写与匹配"""

    def __init__(self, base_dir=None, logger=None):
        """初始化 ProfileStore 实例。"""
        base = base_dir or resolve_files_dir()
        self.dir = os.path.join(base, PROFILE_DIR_NAME)
        self.logger = logger
        if not os.path.isdir(self.dir):
            os.makedirs(self.dir)

    def _log(self, line):
        """写一行日志。"""
        if self.logger is not None:
            self.logger.log(line)

    def _stem(self, fingerprint):
        """档案文件名主干。"""
        name = u"%s_%s_%sx%s_%s" % (
            fingerprint.get(u"brand", u"unknown"),
            fingerprint.get(u"model", u"unknown"),
            fingerprint.get(u"screen_w", 0),
            fingerprint.get(u"screen_h", 0),
            fingerprint.get(u"moutai_version", u"na"),
        )
        return _safe_name(name)

    def json_path(self, fingerprint):
        """档案 JSON 路径。"""
        return os.path.join(
            self.dir, u"profile_%s.json" % self._stem(fingerprint)
        )

    def txt_path(self, fingerprint):
        """档案说明 TXT 路径。"""
        return os.path.join(
            self.dir, u"profile_%s_说明.txt" % self._stem(fingerprint)
        )

    def save(self, profile):
        """落盘 JSON + 可读 TXT，返回 JSON 路径"""
        fingerprint = profile.fingerprint
        json_path = self.json_path(fingerprint)
        with open(json_path, u"w", encoding=u"utf-8") as handle:
            handle.write(json.dumps(
                profile.to_dict(), ensure_ascii=False, indent=2
            ))
        txt_path = self.txt_path(fingerprint)
        with open(txt_path, u"w", encoding=u"utf-8") as handle:
            handle.write(self._render_text(profile))
        self._log(u"设备档案已保存：%s" % json_path)
        return json_path

    def load_all(self):
        """加载目录下全部档案。"""
        profiles = []
        for name in os.listdir(self.dir):
            if not name.endswith(u".json") or not name.startswith(u"profile_"):
                continue
            try:
                with open(os.path.join(self.dir, name),
                          u"r", encoding=u"utf-8") as handle:
                    profiles.append(
                        DeviceProfile.from_dict(json.load(handle))
                    )
            except Exception as exc:
                self._log(u"档案读取失败 %s：%s" % (name, exc))
        return profiles

    def find_matching(self, fingerprint):
        """返回匹配指纹的档案；无匹配返回 None"""
        for profile in self.load_all():
            if profile.matches(fingerprint):
                return profile
        return None

    # ---------------- 可读 TXT ----------------

    @staticmethod
    def _bounds_text(bounds):
        """bounds 转可读文本。"""
        if not bounds:
            return u"未采集"
        return u"[%d,%d][%d,%d]" % (
            bounds[0], bounds[1], bounds[2], bounds[3]
        )

    def _render_text(self, profile):
        """生成档案说明文本。"""
        fp = profile.fingerprint
        controls = profile.controls
        lines = [
            u"i茅台启动器 设备参数档案",
            u"====================================",
            u"品牌/型号：%s %s" % (
                fp.get(u"brand", u""), fp.get(u"model", u"")
            ),
            u"系统：Android %s（SDK %d）" % (
                fp.get(u"android_release", u""),
                fp.get(u"android_sdk", 0),
            ),
            u"物理屏：%d x %d，密度 %s（%d dpi）" % (
                fp.get(u"screen_w", 0), fp.get(u"screen_h", 0),
                fp.get(u"density", 0.0), fp.get(u"density_dpi", 0),
            ),
            u"i茅台包名：%s" % fp.get(u"moutai_package", u""),
            u"i茅台版本：%s（版本码 %d）" % (
                fp.get(u"moutai_version", u""),
                fp.get(u"moutai_version_code", 0),
            ),
            u"应用标签：%s" % fp.get(u"app_label", u""),
            u"签名 SHA-256：%s" % fp.get(u"signature_sha256", u""),
            u"采集时间：%s" % profile.collected_at,
            u"",
            u"控件 bounds（绝对像素，运行时节点树兜底用）",
            u"------------------------------------",
            u"i购标签：%s" % self._bounds_text(
                controls.get(u"igou_tab", {}).get(u"bounds")
            ),
            u"经典标签：%s" % self._bounds_text(
                controls.get(u"jingdian_tab", {}).get(u"bounds")
            ),
            u"商品卡位：%s" % self._bounds_text(
                controls.get(u"product_card", {}).get(u"bounds")
            ),
            u"年份格：",
        ]
        for year, cell in sorted(
            controls.get(u"year_cells", {}).items(), reverse=True
        ):
            lines.append(u"  %s：%s，中心 %s" % (
                year,
                self._bounds_text(cell.get(u"bounds")),
                tuple(cell.get(u"center", ())),
            ))
        lines.extend([
            u"数量数字框：%s" % self._bounds_text(
                controls.get(u"qty_value", {}).get(u"bounds")
            ),
            u"数量减号：%s" % self._bounds_text(
                controls.get(u"qty_minus", {}).get(u"bounds")
            ),
            u"数量加号：%s" % self._bounds_text(
                controls.get(u"qty_plus", {}).get(u"bounds")
            ),
            u"购买按钮区：%s" % self._bounds_text(
                controls.get(u"action_button", {}).get(u"bounds")
            ),
            u"",
            u"截图存证",
            u"------------------------------------",
        ])
        if profile.screenshots:
            for shot in profile.screenshots:
                lines.append(u"%s：%s" % (
                    shot.get(u"stage", u""), shot.get(u"path", u"")
                ))
        else:
            lines.append(u"无")
        lines.append(u"")
        return u"\n".join(lines)
