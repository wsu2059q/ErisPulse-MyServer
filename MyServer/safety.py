"""危险命令分级与确认令牌。

分级：
- confirm：拦截并要求一次性确认令牌（120 秒 TTL，绑定机器+命令哈希）；
- warn：放行，回复附警告。
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid

CONFIRM_TTL = 120.0

# confirm 级词表：正则 → 拦截原因
CONFIRM_PATTERNS: list[tuple[str, str]] = [
    (r"rm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)+(/|~|~/?\*|\*)($|\s)", "递归强删根/家目录"),
    (r"rm\s+.*--(recursive|force)\b[^;|]*\s(/|~|~/?\*|\*)( |$)", "递归强删根/家目录"),
    (r"rm\s+-[a-zA-Z]*[rf][a-zA-Z]*\s+--(recursive|force|no-preserve-root)", "递归强删根/家目录"),
    (r"rm\s+.*--no-preserve-root", "no-preserve-root 删根"),
    (r"\bmkfs(\.\w+)?\b", "格式化文件系统"),
    (r"\bdd\b[^|;]*of=/dev/(sd|vd|nvme|hd|mmcblk)", "dd 直写块设备"),
    (r"^\s*(sudo\s+)?(shutdown|reboot|halt|poweroff|init\s+[06])\b(?!.*--help)", "关机/重启"),
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "fork 炸弹"),
    (r"chmod\s+-R\s+777\s+/", "根目录递归 777"),
    (r"\bwipefs\b", "清除文件系统签名"),
    (r">\s*/dev/(sd|vd|nvme|hd)", "重定向覆盖块设备"),
    (r"\b(chown|chmod)\s+-R\s+\S+\s+/( |$)", "根目录递归改权限"),
    (r"\biptables(-nft)?\s+-F\b", "清空防火墙规则"),
    (r"\bcrontab\s+-r\b", "清空 crontab"),
    (r"\bmv\s+\S+\s+/\s*$", "移动到根目录覆盖"),
]

# warn 级词表：正则 → 警告文案
WARN_PATTERNS: list[tuple[str, str]] = [
    (r"(curl|wget)\b[^|;]*\|\s*(ba)?sh\b", "下载脚本直接执行（先审查来源）"),
    (r"\bchmod\s+-R\b", "递归改权限"),
    (r"\bchown\s+-R\b", "递归改属主"),
    (r"\bkill\s+-9\b", "强杀进程（先试普通 kill）"),
    (r"\b(apt|yum|dnf)\b.*(-y\s+)?(remove|autoremove|erase)\b", "卸载系统包"),
    (r"\b(git|pip|npm|apt|yum|dnf)\b.*--force\b", "强制模式"),
    (r"\btruncate\s+-s\s*0\b", "清空文件"),
    (r"\bsystemctl\s+(stop|disable|restart)\b", "操作系统服务"),
]


def grade(command: str) -> dict:
    """
    命令定级。

    :param command: [str] 命令文本
    :return: [dict] {"level": "ok"|"warn"|"confirm", "reason": str}
    """
    text = str(command or "").strip()
    if not text:
        return {"level": "ok", "reason": ""}
    for pattern, reason in CONFIRM_PATTERNS:
        if re.search(pattern, text):
            return {"level": "confirm", "reason": reason}
    for pattern, reason in WARN_PATTERNS:
        if re.search(pattern, text):
            return {"level": "warn", "reason": reason}
    return {"level": "ok", "reason": ""}


class ConfirmGate:
    """一次性确认令牌：绑定（机器， 命令哈希），TTL 120 秒，用过即焚。"""

    def __init__(self):
        self._pending: dict[str, dict] = {}

    @staticmethod
    def _fingerprint(machine: str, command: str) -> str:
        """{!--< internal-use >!--} 机器+命令哈希。"""
        return hashlib.sha256(f"{machine}\n{command}".encode()).hexdigest()[:16]

    def issue(self, machine: str, command: str) -> dict:
        """
        签发令牌；同机同命令未过期时复用。

        :param machine: [str] 机器名
        :param command: [str] 待确认命令
        :return: [dict] {"token", "expires_in"}
        """
        fp = self._fingerprint(machine, command)
        now = time.time()
        for token, item in list(self._pending.items()):
            if item["fp"] == fp:
                if item["expires"] > now:
                    return {"token": token, "expires_in": int(item["expires"] - now)}
                self._pending.pop(token, None)
        token = uuid.uuid4().hex[:8]
        self._pending[token] = {"fp": fp, "command": command, "machine": machine,
                                "expires": now + CONFIRM_TTL}
        return {"token": token, "expires_in": int(CONFIRM_TTL)}

    def consume(self, machine: str, token: str) -> str | None:
        """
        校验并销毁令牌。

        :param machine: [str] 机器名
        :param token: [str] 令牌
        :return: [str | None] 有效返回绑定的命令，否则 None
        """
        item = self._pending.pop(str(token or "").strip(), None)
        if item is None:
            return None
        if item["machine"] != machine or item["expires"] < time.time():
            return None
        return item["command"]

    def sweep(self) -> int:
        """
        清理过期令牌。

        :return: [int] 清理条数
        """
        now = time.time()
        stale = [t for t, item in self._pending.items() if item["expires"] < now]
        for token in stale:
            self._pending.pop(token, None)
        return len(stale)

    @property
    def pending_count(self) -> int:
        """[int] 当前未过期令牌数。"""
        now = time.time()
        return sum(1 for item in self._pending.values() if item["expires"] >= now)
