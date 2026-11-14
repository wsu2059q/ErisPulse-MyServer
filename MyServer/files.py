"""SFTP 传输与文件管理：连接复用池、体积上限、在线编辑、目录操作。

本地路径合法性由调用方负责（聊天端 = QvQChat 沙箱，Dashboard = 上传目录）。
"""

from __future__ import annotations

import asyncio
import os

EDIT_MAX_BYTES = 256 * 1024


class FileOps:
    """文件操作集（每机器持久连接池，按机器串行）。"""

    def __init__(self, main):
        self.main = main
        self._pool: dict[str, dict] = {}

    async def _client(self, machine_name: str) -> tuple:
        """
        取（或建立）机器的复用连接，配套串行锁。

        :param machine_name: [str] 机器名
        :return: [tuple] (SSHClient, asyncio.Lock)
        """
        machine = self._machine(machine_name)
        entry = self._pool.get(machine_name)
        if entry is None:
            entry = {"lock": asyncio.Lock(), "client": None}
            self._pool[machine_name] = entry
        if entry["client"] is None or not entry["client"].connected:
            client = self.main.make_client(machine)
            await client.connect()
            entry["client"] = client
        return entry["client"], entry["lock"]

    async def close_all(self) -> None:
        """关闭全部复用连接（模块卸载时调用）。"""
        for entry in self._pool.values():
            client = entry.get("client")
            if client is not None:
                try:
                    await client.close()
                except Exception:
                    pass
        self._pool.clear()

    # ---------- 传输 ----------

    async def upload(self, machine_name: str, local_path: str, remote_path: str,
                     actor: str = "") -> dict:
        """
        上传本地文件到远端。

        :param machine_name: [str] 机器名
        :param local_path: [str] 本地文件路径
        :param remote_path: [str] 远端目标路径
        :param actor: [str] 操作者标识（审计用）
        :return: [dict] {"machine", "remote", "size", "size_text"}
        :raises FileNotFoundError: 本地文件不存在
        :raises ValueError: 机器不存在或超体积上限
        :raises ConnectionError: SSH 连接失败
        """
        self._machine(machine_name)
        if not os.path.isfile(local_path):
            raise FileNotFoundError(local_path)
        client, lock = await self._client(machine_name)
        async with lock:
            info = await client.upload(local_path, remote_path,
                                       max_mb=int(self.main.cfg.transfer_max_mb))
        self.main.audit.record(machine_name, actor, "upload",
                               f"{local_path} -> {remote_path}")
        return {"machine": machine_name, "remote": remote_path, **info}

    async def download(self, machine_name: str, remote_path: str, local_path: str,
                       actor: str = "") -> dict:
        """
        下载远端文件到本地。

        :param machine_name: [str] 机器名
        :param remote_path: [str] 远端文件路径
        :param local_path: [str] 本地目标路径
        :param actor: [str] 操作者标识（审计用）
        :return: [dict] {"machine", "remote", "local", "size", "size_text"}
        :raises ValueError: 机器不存在或超体积上限
        :raises ConnectionError: SSH 连接失败
        """
        self._machine(machine_name)
        os.makedirs(os.path.dirname(os.path.abspath(local_path)) or ".", exist_ok=True)
        client, lock = await self._client(machine_name)
        async with lock:
            info = await client.download(remote_path, local_path,
                                         max_mb=int(self.main.cfg.transfer_max_mb))
        self.main.audit.record(machine_name, actor, "download",
                               f"{remote_path} -> {local_path}")
        return {"machine": machine_name, "remote": remote_path,
                "local": local_path, **info}

    async def list_dir(self, machine_name: str, remote_path: str = ".") -> list:
        """
        远端目录列表。

        :param machine_name: [str] 机器名
        :param remote_path: [str] 远端目录 (默认: ".")
        :return: [list] [{name, is_dir, size, mtime}]
        """
        self._machine(machine_name)
        client, lock = await self._client(machine_name)
        async with lock:
            return await client.list_dir(remote_path)

    # ---------- 管理 ----------

    async def read_file(self, machine_name: str, remote_path: str,
                        actor: str = "") -> str:
        """
        读取远端文本文件（在线编辑）。

        :param machine_name: [str] 机器名
        :param remote_path: [str] 远端路径
        :param actor: [str] 操作者标识
        :return: [str] 文件文本
        """
        self._machine(machine_name)
        client, lock = await self._client(machine_name)
        async with lock:
            return await client.read_text(remote_path, max_bytes=EDIT_MAX_BYTES)

    async def write_file(self, machine_name: str, remote_path: str, text: str,
                         actor: str = "") -> dict:
        """
        写回远端文本文件。

        :param machine_name: [str] 机器名
        :param remote_path: [str] 远端路径
        :param text: [str] 文件内容
        :param actor: [str] 操作者标识
        :return: [dict] {"size"}
        """
        self._machine(machine_name)
        client, lock = await self._client(machine_name)
        async with lock:
            info = await client.write_text(remote_path, text)
        self.main.audit.record(machine_name, actor, "file_write", remote_path)
        return info

    async def mkdir(self, machine_name: str, remote_path: str, actor: str = "") -> None:
        """
        创建远端目录。

        :param machine_name: [str] 机器名
        :param remote_path: [str] 目录路径
        :param actor: [str] 操作者标识
        """
        self._machine(machine_name)
        client, lock = await self._client(machine_name)
        async with lock:
            await client.mkdir(remote_path)
        self.main.audit.record(machine_name, actor, "file_mkdir", remote_path)

    async def rename(self, machine_name: str, old_path: str, new_path: str,
                     actor: str = "") -> None:
        """
        重命名 / 移动。

        :param machine_name: [str] 机器名
        :param old_path: [str] 原路径
        :param new_path: [str] 新路径
        :param actor: [str] 操作者标识
        """
        self._machine(machine_name)
        client, lock = await self._client(machine_name)
        async with lock:
            await client.rename(old_path, new_path)
        self.main.audit.record(machine_name, actor, "file_rename",
                               f"{old_path} -> {new_path}")

    async def delete(self, machine_name: str, remote_path: str, is_dir: bool,
                     actor: str = "") -> None:
        """
        删除文件或目录（目录递归删除，审计记录）。

        :param machine_name: [str] 机器名
        :param remote_path: [str] 目标路径
        :param is_dir: [bool] 是否目录
        :param actor: [str] 操作者标识
        """
        self._machine(machine_name)
        client, lock = await self._client(machine_name)
        async with lock:
            await client.delete(remote_path, is_dir=is_dir)
        self.main.audit.record(machine_name, actor, "file_delete",
                               remote_path, "confirm" if is_dir else "warn")

    def _machine(self, name: str) -> dict:
        """{!--< internal-use >!--} 取机器，不存在抛 ValueError。"""
        machine = self.main.fleet.get(str(name or ""))
        if machine is None:
            raise ValueError(f"machine not found: {name}")
        return machine
