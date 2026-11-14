"""SSH 连接层（asyncssh）：连接、执行、指标采集、SFTP。"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import tempfile
import uuid

from .utils import format_size

# 单往返指标采集脚本：POSIX sh，缺项输出 null
METRICS_SCRIPT = r"""
MEM_TOTAL=$(awk '/^MemTotal:/{print $2}' /proc/meminfo 2>/dev/null)
MEM_AVAIL=$(awk '/^MemAvailable:/{print $2}' /proc/meminfo 2>/dev/null)
LOAD=$(cut -d' ' -f1,2,3 /proc/loadavg 2>/dev/null)
CPU=$(vmstat 1 2 2>/dev/null | tail -1 | awk '{print 100-$15}')
CPU_CORES=$(nproc 2>/dev/null)
UPTIME=$(awk '{print int($1)}' /proc/uptime 2>/dev/null)
TCP=$(cat /proc/net/tcp /proc/net/tcp6 2>/dev/null | awk '$4=="01"{c++} END{print c+0}')
NET=$(awk '$1!~/^lo:/ && $1~/:/ {gsub(/:/,"",$1); rx+=$2; tx+=$10} END{print rx+0":"tx+0}' /proc/net/dev 2>/dev/null)
DF=$(df -P / 2>/dev/null | awk 'NR==2{print $2":"$3}')
HOSTNAME=$(hostname 2>/dev/null)
KERNEL=$(uname -r 2>/dev/null)
OS=$(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-$(uname -s)}")
echo "{\"hostname\":\"$HOSTNAME\",\"os\":\"$OS\",\"kernel\":\"$KERNEL\",\"uptime_s\":${UPTIME:-null},\"cpu_cores\":${CPU_CORES:-null},\"cpu_percent\":${CPU:-null},\"mem_total_kb\":${MEM_TOTAL:-null},\"mem_avail_kb\":${MEM_AVAIL:-null},\"disk_kb\":\"$DF\",\"load\":\"$LOAD\",\"tcp\":${TCP:-null},\"net\":\"$NET\"}"
"""


class SSHClient:
    def __init__(self, host: str, port: int = 22, username: str = "root",
                 password: str = "", key_path: str = "", private_key: str = "",
                 allow_paste_keys: bool = True):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.key_path = key_path
        self.private_key = private_key
        self.allow_paste_keys = allow_paste_keys
        self._conn = None
        self._temp_key_path: str | None = None

    async def connect(self) -> bool:
        """
        建立 SSH 连接。密钥优先：key_path > private_key（粘贴内容落临时文件 0600）> 密码。

        :return: [bool] 连接成功
        :raises ConnectionError: 连接失败
        """
        try:
            import asyncssh

            kwargs: dict = {
                "host": self.host,
                "port": self.port,
                "username": self.username,
                "known_hosts": None,
            }
            key_path = self.key_path
            if not key_path and self.private_key:
                if not self.allow_paste_keys:
                    raise ValueError("paste-key disabled by config (allow_paste_keys=false)")
                key_path = self._write_temp_key(self.private_key)
            if key_path:
                kwargs["client_keys"] = [key_path]
            elif self.password:
                kwargs["password"] = self.password

            self._conn = await asyncssh.connect(**kwargs)
            return True
        except Exception as e:
            raise ConnectionError(f"SSH connect failed: {e}") from e

    def _write_temp_key(self, content: str) -> str:
        """{!--< internal-use >!--} 私钥内容写临时文件。"""
        fd, path = tempfile.mkstemp(suffix=".pem", prefix="myserver_")
        with os.fdopen(fd, "w") as f:
            f.write(content if content.endswith("\n") else content + "\n")
        os.chmod(path, 0o600)
        self._temp_key_path = path
        return path

    @property
    def connected(self) -> bool:
        """[bool] 当前是否已连接。"""
        return self._conn is not None

    async def exec_command(self, cmd: str, timeout: int = 30) -> dict:
        """
        非交互执行单条命令。

        :param cmd: [str] 命令文本
        :param timeout: [int] 超时秒数 (默认: 30)
        :return: [dict] stdout / stderr / exit_code；超时 exit_code=-1 且带 timed_out=True
        """
        if self._conn is None:
            await self.connect()
        try:
            result = await asyncio.wait_for(self._conn.run(cmd), timeout=timeout)
            return {
                "stdout": result.stdout or "",
                "stderr": result.stderr or "",
                "exit_code": result.exit_status,
            }
        except asyncio.TimeoutError:
            return {"stdout": "", "stderr": "timeout", "exit_code": -1, "timed_out": True}
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "exit_code": -1}

    async def exec_script(self, script: str, timeout: int = 120) -> dict:
        """
        多行脚本执行：SFTP 落远端 /tmp 后 bash 执行，结束清理。

        :param script: [str] 脚本内容
        :param timeout: [int] 执行超时秒数 (默认: 120)
        :return: [dict] 同 exec_command
        """
        if self._conn is None:
            await self.connect()
        remote_path = f"/tmp/_myserver_script_{uuid.uuid4().hex[:8]}.sh"
        try:
            async with await self._conn.start_sftp_client() as sftp:
                async with sftp.open(remote_path, "w") as handle:
                    await handle.write(script)
            await self.exec_command(f"chmod +x {shlex.quote(remote_path)}", timeout=5)
            result = await self.exec_command(f"bash {shlex.quote(remote_path)}", timeout=timeout)
            return result
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "exit_code": -1}
        finally:
            await self.exec_command(f"rm -f {shlex.quote(remote_path)}", timeout=3)

    async def collect_metrics(self) -> dict:
        """
        单往返指标采集：一条复合脚本输出一行 JSON。

        :return: [dict] hostname/os/kernel/uptime_s/cpu_cores/cpu_percent/load1/
                 mem_percent/disk_percent 等字段，缺项为 None
        :raises ConnectionError: 采集脚本无输出时
        """
        result = await self.exec_command(METRICS_SCRIPT, timeout=15)
        if result.get("exit_code") != 0 and not result.get("stdout"):
            raise ConnectionError(result.get("stderr") or "metrics collection failed")
        return parse_metrics(result.get("stdout", ""))

    async def upload(self, local_path: str, remote_path: str, max_mb: int = 100) -> dict:
        """
        SFTP 上传。

        :param local_path: [str] 本地文件路径
        :param remote_path: [str] 远端目标路径
        :param max_mb: [int] 体积上限 MB (默认: 100)
        :return: [dict] size（字节）、size_text
        :raises ValueError: 超出体积上限
        """
        if self._conn is None:
            await self.connect()
        size = os.path.getsize(local_path)
        if size > max_mb * 1024 * 1024:
            raise ValueError(f"file exceeds {max_mb} MB limit ({format_size(size)})")
        async with await self._conn.start_sftp_client() as sftp:
            await sftp.put(local_path, remote_path)
        return {"size": size, "size_text": format_size(size)}

    async def download(self, remote_path: str, local_path: str, max_mb: int = 100) -> dict:
        """
        SFTP 下载。

        :param remote_path: [str] 远端文件路径
        :param local_path: [str] 本地目标路径
        :param max_mb: [int] 体积上限 MB (默认: 100)
        :return: [dict] size（字节）、size_text
        :raises ValueError: 超出体积上限
        """
        if self._conn is None:
            await self.connect()
        async with await self._conn.start_sftp_client() as sftp:
            attrs = await sftp.stat(remote_path)
            size = getattr(attrs, "size", 0) or 0
            if size > max_mb * 1024 * 1024:
                raise ValueError(f"file exceeds {max_mb} MB limit ({format_size(size)})")
            await sftp.get(remote_path, local_path)
        return {"size": size, "size_text": format_size(size)}

    async def list_dir(self, remote_path: str = ".") -> list:
        """
        目录列表。

        :param remote_path: [str] 远端目录 (默认: ".")
        :return: [list] [{name, is_dir, size, mtime}]
        """
        if self._conn is None:
            await self.connect()
        entries = []
        async with await self._conn.start_sftp_client() as sftp:
            for entry in await sftp.readdir(remote_path):
                if entry.filename in (".", ".."):
                    continue
                attrs = entry.attrs
                entries.append({
                    "name": entry.filename,
                    "is_dir": _attr_is_dir(attrs, getattr(entry, "longname", "")),
                    "size": getattr(attrs, "size", 0) or 0,
                    "mtime": getattr(attrs, "mtime", 0) or 0,
                })
        entries.sort(key=lambda item: (not item["is_dir"], item["name"].lower()))
        return entries

    async def read_text(self, remote_path: str, max_bytes: int = 262144) -> str:
        """
        读取远端文本文件（在线编辑用）。

        :param remote_path: [str] 远端文件路径
        :param max_bytes: [int] 体积上限字节 (默认: 262144)
        :return: [str] 文件文本
        :raises ValueError: 超限或二进制文件
        """
        if self._conn is None:
            await self.connect()
        async with await self._conn.start_sftp_client() as sftp:
            async with sftp.open(remote_path, "r") as handle:
                data = await handle.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("文件超过在线编辑上限（256 KB）")
        if b"\x00" in data:
            raise ValueError("二进制文件不支持在线编辑")
        return data.decode("utf-8", "replace")

    async def write_text(self, remote_path: str, text: str) -> dict:
        """
        写回远端文本文件。

        :param remote_path: [str] 远端文件路径
        :param text: [str] 文件内容
        :return: [dict] size（字节）
        """
        if self._conn is None:
            await self.connect()
        data = text.encode("utf-8")
        async with await self._conn.start_sftp_client() as sftp:
            async with sftp.open(remote_path, "w") as handle:
                await handle.write(data)
        return {"size": len(data)}

    async def mkdir(self, remote_path: str) -> None:
        """
        创建远端目录。

        :param remote_path: [str] 目录路径
        """
        if self._conn is None:
            await self.connect()
        async with await self._conn.start_sftp_client() as sftp:
            await sftp.mkdir(remote_path)

    async def rename(self, old_path: str, new_path: str) -> None:
        """
        重命名 / 移动。

        :param old_path: [str] 原路径
        :param new_path: [str] 新路径
        """
        if self._conn is None:
            await self.connect()
        async with await self._conn.start_sftp_client() as sftp:
            await sftp.rename(old_path, new_path)

    async def delete(self, remote_path: str, is_dir: bool = False) -> None:
        """
        删除文件或目录（目录递归删除）。

        :param remote_path: [str] 目标路径
        :param is_dir: [bool] 是否目录
        """
        if self._conn is None:
            await self.connect()
        if is_dir:
            await self.exec_command(f"rm -rf -- {shlex.quote(remote_path)}", timeout=60)
        else:
            async with await self._conn.start_sftp_client() as sftp:
                await sftp.remove(remote_path)

    async def check_alive(self) -> bool:
        """
        探活：远端执行 echo ok。

        :return: [bool] 是否存活
        """
        result = await self.exec_command("echo ok", timeout=10)
        return result.get("exit_code") == 0

    async def close(self):
        """
        关闭连接并删除私钥临时文件。
        """
        if self._temp_key_path:
            try:
                os.unlink(self._temp_key_path)
            except Exception:
                pass
            self._temp_key_path = None
        if self._conn is not None:
            try:
                self._conn.close()
                await self._conn.wait_closed()
            except Exception:
                pass
            self._conn = None


def _attr_is_dir(attrs, longname: str = "") -> bool:
    """{!--< internal-use >!--} SFTP 属性是否目录。"""
    try:
        import stat as _stat

        permissions = getattr(attrs, "permissions", None)
        if permissions is not None:
            return bool(permissions & _stat.S_IFDIR)
    except Exception:
        pass
    return str(longname or "").startswith("d")


def parse_metrics(raw: str) -> dict:
    """
    解析采集脚本输出，归一化为指标字典。

    :param raw: [str] 脚本 stdout
    :return: [dict] 缺项为 None，磁盘拆 percent/used_text/total_text
    """
    line = ""
    for candidate in reversed(str(raw or "").strip().splitlines()):
        candidate = candidate.strip()
        if candidate.startswith("{"):
            line = candidate
            break
    data: dict = {}
    if line:
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            data = {}

    metrics = {
        "hostname": str(data.get("hostname") or ""),
        "os": str(data.get("os") or ""),
        "kernel": str(data.get("kernel") or ""),
        "uptime_s": _num(data.get("uptime_s")),
        "cpu_cores": _num(data.get("cpu_cores")),
        "cpu_percent": _num(data.get("cpu_percent")),
        "load1": None, "load5": None, "load15": None,
        "mem_percent": None, "mem_used_text": "", "mem_total_text": "",
        "disk_percent": None, "disk_used_text": "", "disk_total_text": "",
        "net_rx_bytes": None, "net_tx_bytes": None, "tcp": None,
    }
    loads = str(data.get("load") or "").split()
    if len(loads) >= 1:
        metrics["load1"] = _num(loads[0])
    if len(loads) >= 2:
        metrics["load5"] = _num(loads[1])
    if len(loads) >= 3:
        metrics["load15"] = _num(loads[2])

    net_raw = str(data.get("net") or "")
    if ":" in net_raw:
        try:
            rx, tx = (float(x) for x in net_raw.split(":", 1))
            metrics["net_rx_bytes"] = rx
            metrics["net_tx_bytes"] = tx
        except ValueError:
            pass
    metrics["tcp"] = _num(data.get("tcp"))

    mem_total = _num(data.get("mem_total_kb"))
    mem_avail = _num(data.get("mem_avail_kb"))
    if mem_total and mem_avail is not None:
        mem_used = max(0, mem_total - mem_avail)
        metrics["mem_percent"] = round(mem_used / mem_total * 100, 1)
        metrics["mem_used_text"] = _kb_text(mem_used)
        metrics["mem_total_text"] = _kb_text(mem_total)

    disk_raw = str(data.get("disk_kb") or "")
    if ":" in disk_raw:
        try:
            total_kb, used_kb = (float(x) for x in disk_raw.split(":", 1))
            if total_kb > 0:
                metrics["disk_percent"] = round(used_kb / total_kb * 100, 1)
                metrics["disk_used_text"] = _kb_text(used_kb)
                metrics["disk_total_text"] = _kb_text(total_kb)
        except ValueError:
            pass
    return metrics


def summary_line(metrics: dict) -> str:
    """
    指标转一行人类可读摘要（告警/列表用）。

    :param metrics: [dict] parse_metrics 输出
    :return: [str] 形如 "CPU 12% · MEM 45% · DISK 30% · up 3d2h"
    """
    cpu = metrics.get("cpu_percent")
    mem = metrics.get("mem_percent")
    disk = metrics.get("disk_percent")
    parts = []
    if cpu is not None:
        parts.append(f"CPU {cpu:.0f}%")
    if mem is not None:
        parts.append(f"MEM {mem:.0f}%")
    if disk is not None:
        parts.append(f"DISK {disk:.0f}%")
    uptime = metrics.get("uptime_s")
    if uptime:
        from .utils import format_duration

        parts.append(f"up {format_duration(uptime)}")
    return " · ".join(parts) or "online"


def _num(value) -> float | None:
    """{!--< internal-use >!--} 宽松转 float。"""
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _kb_text(kb: float) -> str:
    """{!--< internal-use >!--} KB 转可读体积。"""
    return format_size(kb * 1024)
