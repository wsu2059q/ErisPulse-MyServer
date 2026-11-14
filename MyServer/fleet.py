"""机器注册表：增删改查、分组标签、批量目标解析、到期计算。"""

from __future__ import annotations

import datetime
import time

MACHINE_PREFIX = "mjj:machine:"
MACHINE_LIST_KEY = "mjj:machines"
STATUS_PREFIX = "mjj:status:"
SECRET_FIELDS = ("password", "private_key", "key_path")

VALID_AUTH = ("password", "key")


def days_until(expiry: str) -> int | None:
    """
    计算距到期日（YYYY-MM-DD）的剩余天数。

    :param expiry: [str] 到期日期文本
    :return: [int | None] 剩余天数（负数 = 已过期），缺失/非法返回 None
    """
    text = str(expiry or "").strip().replace("/", "-")
    if not text:
        return None
    try:
        expiry_date = datetime.date.fromisoformat(text[:10])
    except ValueError:
        return None
    today = datetime.date.today()
    return (expiry_date - today).days



class Fleet:
    """机器注册表（sdk.storage）。"""

    def __init__(self, storage):
        self.storage = storage

    def save(self, machine: dict) -> bool:
        """
        保存机器（新增或更新）。

        :param machine: [dict] 至少含 name/ip/port/username/auth_type
        :return: [bool] 是否成功
        """
        name = str(machine.get("name") or "").strip()
        if not name:
            return False
        machine["name"] = name
        machine["updated_at"] = time.time()
        if "added_at" not in machine:
            machine["added_at"] = time.time()
        self.storage.set(f"{MACHINE_PREFIX}{name}", machine)
        names = self._names()
        if name not in names:
            names.append(name)
            self.storage.set(MACHINE_LIST_KEY, names)
        return True

    def get(self, name: str) -> dict | None:
        """
        取单台机器（含凭据字段）。

        :param name: [str] 机器名
        :return: [dict | None] 机器字典，不存在返回 None
        """
        data = self.storage.get(f"{MACHINE_PREFIX}{name}")
        return data if isinstance(data, dict) else None

    def delete(self, name: str) -> bool:
        """
        删除机器及其状态。

        :param name: [str] 机器名
        :return: [bool] 是否删除了机器
        """
        if self.get(name) is None:
            return False
        self.storage.delete(f"{MACHINE_PREFIX}{name}")
        self.storage.delete(f"{STATUS_PREFIX}{name}")
        names = self._names()
        if name in names:
            names.remove(name)
            self.storage.set(MACHINE_LIST_KEY, names)
        return True

    def names(self) -> list[str]:
        """
        全部机器名。

        :return: [list[str]] 机器名列表
        """
        return self._names()

    def all(self, include_secrets: bool = False) -> list[dict]:
        """
        全部机器。

        :param include_secrets: [bool] 是否保留凭据字段 (默认: False)
        :return: [list[dict]] 机器列表，附最近状态 online
        """
        result = []
        for name in self._names():
            machine = self.get(name)
            if machine is None:
                continue
            machine["online"] = (self.status(name) or {}).get("online", False)
            if not include_secrets:
                machine = self.redact(machine)
            result.append(machine)
        return result

    def redact(self, machine: dict) -> dict:
        """
        剥离凭据字段的机器副本（API 返回用）。

        :param machine: [dict] 原始机器字典
        :return: [dict] 已剥凭据的副本
        """
        clean = dict(machine)
        for field in SECRET_FIELDS:
            if clean.get(field):
                clean[field] = "****"
        return clean

    def groups(self) -> dict[str, list[str]]:
        """
        分组视图：group 名 → 机器名列表（无分组的归 "default"）。

        :return: [dict[str, list[str]]] 分组映射
        """
        result: dict[str, list[str]] = {}
        for machine in self.all():
            group = str(machine.get("group") or "default")
            result.setdefault(group, []).append(machine["name"])
        return result

    def resolve_targets(self, spec: str) -> list[str]:
        """
        解析批量目标：逗号分隔的机器名或 group:组名。

        :param spec: [str] 如 "web-1,web-2" 或 "group:web"
        :return: [list[str]] 去重后的机器名列表
        """
        targets: list[str] = []
        for part in str(spec or "").split(","):
            part = part.strip()
            if not part:
                continue
            if part.startswith("group:"):
                targets.extend(self.groups().get(part[6:], []))
            elif self.get(part) is not None:
                targets.append(part)
        return list(dict.fromkeys(targets))

    def save_status(self, name: str, status: dict) -> None:
        """
        保存最近一次探测状态。

        :param name: [str] 机器名
        :param status: [dict] 含 online 与指标
        """
        status["checked_at"] = time.time()
        self.storage.set(f"{STATUS_PREFIX}{name}", status)

    def status(self, name: str) -> dict:
        """
        取最近一次探测状态。

        :param name: [str] 机器名
        :return: [dict] 状态字典，无记录返回空字典
        """
        data = self.storage.get(f"{STATUS_PREFIX}{name}", {})
        return data if isinstance(data, dict) else {}

    def stats(self) -> dict:
        """
        舰队统计。

        :return: [dict] {"total", "online", "offline"}
        """
        machines = self.all()
        online = sum(1 for m in machines if m.get("online"))
        return {"total": len(machines), "online": online, "offline": len(machines) - online}

    def _names(self) -> list[str]:
        """{!--< internal-use >!--} 机器名清单。"""
        data = self.storage.get(MACHINE_LIST_KEY, [])
        return data if isinstance(data, list) else []
