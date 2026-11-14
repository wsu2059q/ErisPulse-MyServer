"""终端会话托管：命名会话 + 远端 tmux 兜底持久化 + 多端挂接。

会话两种模式：
- tmux：远端 `tmux new -A -s myserver_<name>`，MyServer 重启/断线不丢现场，
  聊天端经 send-keys/capture-pane 操作，Dashboard 经独立 SSH 进程 attach 同一
  tmux 会话；
- local：远端无 tmux 时的降级，直接 create_process，会话随连接结束终止。
"""

from __future__ import annotations

import shlex

from .ssh import SSHClient
from .utils import safe_session_name

TMUX_PREFIX = "myserver_"

# 跨发行版 tmux 安装命令（apt / dnf / yum / apk 依次探测）
INSTALL_TMUX_CMD = (
    "(command -v apt-get >/dev/null 2>&1 && apt-get update -qq && apt-get install -y tmux)"
    " || (command -v dnf >/dev/null 2>&1 && dnf install -y tmux)"
    " || (command -v yum >/dev/null 2>&1 && yum install -y tmux)"
    " || (command -v apk >/dev/null 2>&1 && apk add tmux)"
)


class Session:
    """一个已连接机器上的持久会话。"""

    def __init__(self, machine: str, session_name: str, client: SSHClient, mode: str):
        self.machine = machine
        self.name = session_name
        self.tmux_name = f"{TMUX_PREFIX}{safe_session_name(session_name)}"
        self.client = client
        self.mode = mode  # tmux / local
        self.local_process = None

    async def write(self, text: str) -> None:
        """
        向会话写入一行（tmux: send-keys / local: stdin）。

        :param text: [str] 命令文本
        """
        if self.mode == "tmux":
            # -l 字面量写入，再单独发回车：文本里的特殊键名不被解释
            await self.client.exec_command(
                f"tmux send-keys -t {shlex.quote(self.tmux_name)} -l {shlex.quote(text)}",
                timeout=10)
            await self.client.exec_command(
                f"tmux send-keys -t {shlex.quote(self.tmux_name)} Enter", timeout=10)
            return
        if self.local_process is not None:
            self.local_process.stdin.write(text + "\n")

    async def capture(self, lines: int = 30) -> str:
        """
        抓取会话当前屏输出。

        :param lines: [int] 回看行数 (默认: 30)
        :return: [str] 屏幕文本
        """
        if self.mode == "tmux":
            result = await self.client.exec_command(
                f"tmux capture-pane -t {shlex.quote(self.tmux_name)} -p -S -{int(lines)}",
                timeout=10)
            return result.get("stdout", "")
        return ""

    async def alive(self) -> bool:
        """
        会话是否存活。

        :return: [bool] tmux 会话存在 / local 进程未退出
        """
        if self.mode == "tmux":
            result = await self.client.exec_command(
                f"tmux has-session -t {shlex.quote(self.tmux_name)} 2>/dev/null; echo $?",
                timeout=10)
            return result.get("stdout", "").strip() != "0"
        if self.local_process is None:
            return False
        return not self.local_process.stdout.at_eof()

    async def kill(self) -> None:
        """终结会话（tmux kill-session / local terminate）。"""
        if self.mode == "tmux":
            await self.client.exec_command(
                f"tmux kill-session -t {shlex.quote(self.tmux_name)}", timeout=10)
        else:
            if self.local_process is not None:
                self.local_process.terminate()
                self.local_process = None
        await self.client.close()


class SessionManager:
    """命名会话集合（进程内），容量与模式策略来自配置。"""

    def __init__(self, max_sessions: int = 8, prefer_tmux: bool = True):
        self.max_sessions = max_sessions
        self.prefer_tmux = prefer_tmux
        self._sessions: dict[str, Session] = {}

    def list(self, machine: str = "") -> list[dict]:
        """
        会话清单。

        :param machine: [str] 机器过滤，空 = 全部
        :return: [list[dict]] [{machine, name, mode}]
        """
        result = []
        for key, session in self._sessions.items():
            if machine and session.machine != machine:
                continue
            result.append({"machine": session.machine, "name": session.name,
                           "mode": session.mode})
        return result

    def get(self, machine: str, session_name: str) -> Session | None:
        """
        取会话。

        :param machine: [str] 机器名
        :param session_name: [str] 会话名
        :return: [Session | None] 会话对象
        """
        return self._sessions.get(self._key(machine, session_name))

    async def open(self, machine: str, session_name: str, client: SSHClient) -> Session:
        """
        开启或复用会话：远端有 tmux 用 tmux 模式，否则降级 local。

        :param machine: [str] 机器名
        :param session_name: [str] 会话名
        :param client: [SSHClient] 已连接的客户端（会话持有，close 由 kill 负责）
        :return: [Session] 会话对象
        :raises RuntimeError: 超出容量上限
        """
        key = self._key(machine, session_name)
        existing = self._sessions.get(key)
        if existing is not None:
            return existing
        if len(self._sessions) >= self.max_sessions:
            raise RuntimeError(f"session limit {self.max_sessions} reached")

        mode = "local"
        if self.prefer_tmux:
            probe = await client.exec_command("command -v tmux", timeout=5)
            if probe.get("exit_code") == 0:
                mode = "tmux"

        session = Session(machine, session_name, client, mode)
        if mode == "tmux":
            await client.exec_command(
                f"tmux new -A -s {shlex.quote(session.tmux_name)}", timeout=15)
        else:
            try:
                session.local_process = await client._conn.create_process(
                    term_type="xterm", term_size=(120, 30))
            except Exception:
                session.local_process = None
        self._sessions[key] = session
        return session

    async def close(self, machine: str, session_name: str) -> bool:
        """
        关闭会话并断开其 SSH 连接。

        :param machine: [str] 机器名
        :param session_name: [str] 会话名
        :return: [bool] 会话是否存在并被关闭
        """
        key = self._key(machine, session_name)
        session = self._sessions.pop(key, None)
        if session is None:
            return False
        try:
            await session.kill()
        except Exception:
            pass
        return True

    async def close_all(self) -> int:
        """
        关闭全部会话（模块卸载时调用）。

        :return: [int] 关闭数量
        """
        count = 0
        for key in list(self._sessions):
            if await self.close(*key):
                count += 1
        return count

    def _key(self, machine: str, session_name: str) -> tuple[str, str]:
        """{!--< internal-use >!--} 会话字典键。"""
        return (machine, session_name)
