"""审计记录：敏感操作落库与检索。"""

from __future__ import annotations

import hashlib
import time

AUDIT_TABLE = "myserver_audit"


class AuditLog:
    """审计日志（sdk.storage 单表）。"""

    def __init__(self, storage):
        self.storage = storage
        self._initialized = False

    def _ensure_table(self):
        """{!--< internal-use >!--} 惰性建表。"""
        if self._initialized:
            return
        try:
            if not self.storage.HasTable(AUDIT_TABLE):
                self.storage.CreateTable(AUDIT_TABLE, {
                    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                    "ts": "REAL NOT NULL",
                    "machine": "TEXT NOT NULL",
                    "actor": "TEXT NOT NULL",
                    "action": "TEXT NOT NULL",
                    "detail": "TEXT",
                    "level": "TEXT",
                    "digest": "TEXT",
                })
            self._initialized = True
        except Exception:
            pass

    def record(self, machine: str, actor: str, action: str, detail: str = "",
               level: str = "ok") -> None:
        """
        落一条审计。

        :param machine: [str] 机器名
        :param actor: [str] 操作者标识（chat:onebot11:uid / dashboard / ai:eco）
        :param action: [str] 动作（exec/confirm/session/upload/download）
        :param detail: [str] 命令或路径文本
        :param level: [str] 危险级 ok/warn/confirm
        """
        self._ensure_table()
        try:
            self.storage.Table(AUDIT_TABLE).Insert({
                "ts": time.time(),
                "machine": str(machine or ""),
                "actor": str(actor or ""),
                "action": str(action or ""),
                "detail": str(detail or "")[:2000],
                "level": str(level or "ok"),
                "digest": hashlib.sha256(str(detail or "").encode()).hexdigest()[:12],
            }).Execute()
        except Exception:
            pass

    def tail(self, machine: str = "", limit: int = 20) -> list[dict]:
        """
        最近审计（新在前）。

        :param machine: [str] 机器名过滤，空 = 全部 (默认: "")
        :param limit: [int] 条数上限 (默认: 20)
        :return: [list[dict]] 审计行
        """
        self._ensure_table()
        try:
            query = self.storage.Table(AUDIT_TABLE).Select("*").ToDict()
            if machine:
                rows = (query.Where("machine = ?", machine)
                        .OrderBy("ts", desc=True).Limit(int(limit)).Execute())
            else:
                rows = query.OrderBy("ts", desc=True).Limit(int(limit)).Execute()
            return rows if rows else []
        except Exception:
            return []

    def cleanup(self, retention_days: int = 30) -> None:
        """
        清理超期审计。

        :param retention_days: [int] 保留天数 (默认: 30)
        """
        self._ensure_table()
        try:
            cutoff = time.time() - retention_days * 86400
            self.storage.Table(AUDIT_TABLE).Delete().Where("ts < ?", cutoff).Execute()
        except Exception:
            pass
