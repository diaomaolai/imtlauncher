# -*- coding: utf-8 -*-
"""
卡密本地持久化模块。

登录成功后把卡密保存到应用私有目录，APP 大退/重启后自动回填到
卡密输入框，避免每次重新输入。仅保存卡密文本，不保存任何授权
状态——授权仍以 /api/card/login 后端返回为准。

文件位置（与日志同目录）：
- 安卓：/sdcard/Android/data/org.personal.imtlauncher/files/logs/
  下 card_saved.json
- 电脑：用户目录下 imt_logs/card_saved.json
"""

import json
import os

from app_logger import resolve_log_dir

CARD_STORE_FILE = u"card_saved.json"


class CardStore(object):
    """最近一次登录成功卡密的本地持久化（重启不丢）"""

    def __init__(self):
        self.path = os.path.join(resolve_log_dir(), CARD_STORE_FILE)
        self.card_no = u""
        self._load()

    def _load(self):
        try:
            with open(self.path, u"r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.card_no = u"%s" % (data.get(u"card_no") or u"")
        except Exception:
            pass

    def save(self, card_no):
        """保存卡密；写失败只静默，不影响登录主流程"""
        self.card_no = u"%s" % (card_no or u"")
        try:
            with open(self.path, u"w", encoding="utf-8") as f:
                json.dump(
                    {u"card_no": self.card_no}, f, ensure_ascii=False
                )
        except Exception:
            pass

    def get(self):
        """读取上次保存的卡密（无则空串）"""
        return self.card_no
