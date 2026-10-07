# -*- coding: utf-8 -*-
"""
日志记录模块

所有关键操作同时：
1. print 到控制台（安卓上即 logcat，可 adb logcat 查看）；
2. 追加写入可读的 txt 日志文件。

日志位置：
- 安卓：/sdcard/Android/data/org.personal.imtlauncher/files/logs/
  （APP 私有外部目录，手机文件管理器可直接读取，无需 root）
- 电脑：用户目录下 imt_logs/

每次武装生成一个带时间戳的日志文件，同时更新 latest.txt。
"""

import os
from datetime import datetime

LOG_FOLDER_NAME = u"logs"
PC_LOG_DIR = os.path.join(os.path.expanduser(u"~"), u"imt_logs")


def resolve_log_dir():
    """返回日志目录绝对路径（自动创建）；失败时退回电脑目录"""
    try:
        from jnius import autoclass
        PythonActivity = autoclass(u"org.kivy.android.PythonActivity")
        activity = PythonActivity.mActivity
        folder = activity.getExternalFilesDir(None)
        if folder is not None:
            base = str(folder.getAbsolutePath())
        else:
            base = str(activity.getFilesDir().getAbsolutePath())
        log_dir = os.path.join(base, LOG_FOLDER_NAME)
    except Exception:
        log_dir = PC_LOG_DIR

    try:
        os.makedirs(log_dir, exist_ok=True)
        return log_dir
    except Exception:
        try:
            os.makedirs(PC_LOG_DIR, exist_ok=True)
        except Exception:
            pass
        return PC_LOG_DIR


class AppLogger(object):
    """统一日志记录器：控制台 + txt 文件"""

    def __init__(self):
        self.log_dir = resolve_log_dir()
        stamp = datetime.now().strftime(u"%Y%m%d_%H%M%S")
        self.session_file = os.path.join(
            self.log_dir, u"imt_log_%s.txt" % stamp
        )
        self.latest_file = os.path.join(self.log_dir, u"latest.txt")
        self.log(u"日志初始化，文件：%s" % self.session_file)

    def log(self, message):
        """记录一行：[HH:MM:SS] message"""
        line = u"[%s] %s" % (
            datetime.now().strftime(u"%H:%M:%S"),
            message,
        )
        print(line)
        for path in (self.session_file, self.latest_file):
            try:
                with open(path, u"a", encoding="utf-8") as handle:
                    handle.write(line + u"\n")
            except Exception:
                # 日志失败绝不能影响主流程
                pass
        return line
