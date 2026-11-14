"""对外服务层：框架服务白名单 + QvQChat 生态约定（schemas/access/extensions/settings）。

工具描述写给 AI 读——「何时用、何时不用、失败了怎么办」都在描述里。
"""

from __future__ import annotations

from . import safety, texts
from .fleet import days_until
from .utils import mask_ip, truncate_output

def _param(param_type: str, description: str) -> dict:
    """{!--< internal-use >!--} schema 参数项。"""
    return {"type": param_type, "description": description}

SERVICES = [
    {
        "name": "server_list",
        "description": "List managed servers with live online/offline state, specs snapshot (OS/cores/memory/disk), expiry date and notes. Available to all chat members; call this first to discover machine names.",
        "signature": "() -> dict",
    },
    {
        "name": "server_status",
        "description": "Live metrics of one server: CPU/memory/disk/load/uptime, collected on demand. Available to all chat members. Use before and after risky work to confirm the box is healthy.",
        "signature": "(name: str) -> dict",
    },
    {
        "name": "server_add",
        "description": "Register a new server so it can be managed from chat. ADMIN ONLY. Requires name + host; credentials via password or private_key. Tests the connection, auto-collects a specs snapshot, and returns the result. Set expiry (YYYY-MM-DD) to enable expiry reminders.",
        "signature": "(name: str, host: str, port: int = 22, username: str = 'root', auth_type: str = 'password', password: str = '', private_key: str = '', group: str = '', expiry: str = '', notes: str = '') -> dict",
    },
    {
        "name": "server_remove",
        "description": "Remove a managed server (its hosted sessions are closed too). ADMIN ONLY. Credentials are deleted from storage; remote data is untouched.",
        "signature": "(name: str) -> dict",
    },
    {
        "name": "server_exec",
        "description": "Run a shell command on one server and return stdout/stderr. ADMIN ONLY. Dangerous commands (rm -rf /, mkfs, shutdown, dd to devices...) are blocked and return a confirmation token — explain the danger to the user, then call server_confirm ONLY after the user explicitly agrees. Never retry a blocked command unmodified.",
        "signature": "(name: str, command: str, timeout: int = 0) -> dict",
    },
    {
        "name": "server_confirm",
        "description": "Execute a previously blocked command using the token from server_exec. ADMIN ONLY. Call only when the user explicitly confirmed the exact command. Token is single-use and expires in 120s.",
        "signature": "(name: str, token: str) -> dict",
    },
    {
        "name": "server_session",
        "description": "Persistent terminal sessions backed by remote tmux (survive restarts/disconnects). ADMIN ONLY. action=open|write|capture|close|list. In-chat equivalent of opening a terminal: write sends a command line, capture reads the screen.",
        "signature": "(action: str, name: str, session: str, command: str = '', lines: int = 30) -> dict",
    },
    {
        "name": "server_upload",
        "description": "Upload a local sandbox file to a server via SFTP. ADMIN ONLY. local_path must be inside the chat work sandbox.",
        "signature": "(name: str, local_path: str, remote_path: str) -> dict",
    },
    {
        "name": "server_download",
        "description": "Download a remote file into the chat work sandbox via SFTP. ADMIN ONLY.",
        "signature": "(name: str, remote_path: str, local_path: str) -> dict",
    },
    {
        "name": "server_history",
        "description": "Recent audit trail of who ran what on which server. ADMIN ONLY. Use to answer 'what did we do earlier'.",
        "signature": "(name: str = '', limit: int = 20) -> dict",
    },
    {
        "name": "qvq_schemas",
        "description": "约定服务：给 QvQChat 生态桥提供参数级 schema",
        "signature": "() -> dict",
    },
    {
        "name": "qvq_access",
        "description": "约定服务：自声明服务访问级别（server_list/status 对所有人开放，其余仅管理员）",
        "signature": "() -> dict",
    },
    {
        "name": "qvq_settings",
        "description": "归属标记：声明本模块出现在 QvQChat 设置页插件分区",
        "signature": "() -> dict",
    },
    {
        "name": "qvq_extensions",
        "description": "约定服务：向 QvQChat 注入服务器操作安全守则（提示词）",
        "signature": "() -> dict",
    },
]

ACCESS = {
    "server_list": "safe",
    "server_status": "safe",
    "server_add": "admin",
    "server_remove": "admin",
    "server_exec": "admin",
    "server_confirm": "admin",
    "server_session": "admin",
    "server_upload": "admin",
    "server_download": "admin",
    "server_history": "admin",
}

SCHEMAS = {
    "server_list": {"type": "object", "properties": {}, "required": []},
    "server_add": {
        "type": "object",
        "properties": {
            "name": _param("string", "Unique machine name, e.g. web-1"),
            "host": _param("string", "SSH host (IP or domain)"),
            "port": _param("integer", "SSH port (default 22)"),
            "username": _param("string", "SSH username (default root)"),
            "auth_type": _param("string", "password / key"),
            "password": _param("string", "SSH password (auth_type=password)"),
            "private_key": _param("string", "Private key content (auth_type=key)"),
            "group": _param("string", "Optional group tag, e.g. web"),
            "expiry": _param("string", "Expiry date YYYY-MM-DD; enables expiry reminders"),
            "notes": _param("string", "Free-form notes, visible to AI later"),
        },
        "required": ["name", "host"],
    },
    "server_remove": {
        "type": "object",
        "properties": {"name": _param("string", "Machine name to remove")},
        "required": ["name"],
    },
    "server_status": {
        "type": "object",
        "properties": {"name": _param("string", "Machine name from server_list")},
        "required": ["name"],
    },
    "server_exec": {
        "type": "object",
        "properties": {
            "name": _param("string", "Machine name from server_list"),
            "command": _param("string", "Shell command to run; output is truncated to the tail"),
            "timeout": _param("integer", "Timeout seconds; 0 uses the configured default"),
        },
        "required": ["name", "command"],
    },
    "server_confirm": {
        "type": "object",
        "properties": {
            "name": _param("string", "Machine name"),
            "token": _param("string", "Confirmation token returned by a blocked server_exec"),
        },
        "required": ["name", "token"],
    },
    "server_session": {
        "type": "object",
        "properties": {
            "action": _param("string", "open / write / capture / close / list"),
            "name": _param("string", "Machine name"),
            "session": _param("string", "Session name (your choice, e.g. 'deploy')"),
            "command": _param("string", "Command line for action=write"),
            "lines": _param("integer", "Screen lines for action=capture (default 30)"),
        },
        "required": ["action", "name", "session"],
    },
    "server_upload": {
        "type": "object",
        "properties": {
            "name": _param("string", "Machine name"),
            "local_path": _param("string", "Local file inside the chat sandbox"),
            "remote_path": _param("string", "Destination path on the server"),
        },
        "required": ["name", "local_path", "remote_path"],
    },
    "server_download": {
        "type": "object",
        "properties": {
            "name": _param("string", "Machine name"),
            "remote_path": _param("string", "Remote file path"),
            "local_path": _param("string", "Destination file inside the chat sandbox"),
        },
        "required": ["name", "remote_path", "local_path"],
    },
    "server_history": {
        "type": "object",
        "properties": {
            "name": _param("string", "Machine name filter; empty = all"),
            "limit": _param("integer", "Max entries (default 20)"),
        },
        "required": [],
    },
}

EXTENSION_PROMPTS = [
    {
        "text": (
            "管服务器（原生能力）：机器清单与配置/到期用 server_list（所有成员可用），"
            "先看状态再动手；跑命令用 server_exec（仅管理员），输出只显示尾部，"
            "长输出让用户去 Dashboard 终端看。"
            "用户新买小鸡让你接管时，用 server_add 注册（拿到密码或私钥就够），"
            "顺手问一句到期时间并填 expiry；server_remove 删除机器。"
            "server_exec 返回 needs_confirm 时说明危险原因并征求同意，用户明确同意后"
            "才 server_confirm；绝不修改被拦命令绕过确认。"
            "长任务、交互程序（top/htop/vim）用 server_session 的 tmux 会话托管，"
            "断线不丢。命令失败先解释 stderr，再提议修正；不要编造执行结果，"
            "不要把密钥/密码回显到聊天里。到期临近（server_list 里 days_left 变小）"
            "时主动提醒用户续费。"
        ),
        "priority": 5,
    },
]


class ServiceMixin:
    """框架服务 + qvq 约定实现（依赖宿主 Main 提供 ops/files/fleet/monitor/audit）。"""

    # ---- 查询（safe） ----

    async def server_list(self, **_) -> dict:
        """全部机器与在线状态、配置快照、到期信息。"""
        machines = self.fleet.all()
        items = []
        for m in machines:
            cached = self.fleet.status(m["name"])
            metrics = cached.get("metrics") or {}
            expiry = str(m.get("expiry") or "").strip()
            items.append({
                "name": m["name"],
                "host": mask_ip(m.get("ip", "")),
                "port": m.get("port", 22),
                "username": m.get("username", ""),
                "group": m.get("group", ""),
                "tags": m.get("tags", []),
                "online": bool(m.get("online")),
                "summary": _summary(metrics) if metrics else "",
                "specs": cached.get("specs") or m.get("specs") or {},
                "expiry": expiry,
                "days_left": days_until(expiry) if expiry else None,
                "notes": str(m.get("notes") or ""),
            })
        return {"count": len(items), "machines": items}

    async def server_add(self, name: str = "", host: str = "", port: int = 22,
                         username: str = "root", auth_type: str = "password",
                         password: str = "", private_key: str = "", key_path: str = "",
                         group: str = "", expiry: str = "", notes: str = "", **_) -> dict:
        """注册新机器：测连、采配置快照、可选到期日。"""
        machine = {
            "name": str(name or "").strip(),
            "ip": str(host or "").strip(),
            "port": int(port) if port else 22,
            "username": str(username or "root").strip() or "root",
            "auth_type": str(auth_type or "password"),
            "password": str(password or ""),
            "private_key": str(private_key or ""),
            "key_path": str(key_path or ""),
            "group": str(group or "").strip(),
            "expiry": str(expiry or "").strip(),
            "notes": str(notes or ""),
        }
        if not machine["name"] or not machine["ip"]:
            return {"ok": False, "error": "name and host are required"}
        if machine["auth_type"] not in ("password", "key"):
            machine["auth_type"] = "password"
        if machine["auth_type"] == "password" and not machine["password"]:
            return {"ok": False, "error": "password required for auth_type=password"}
        if machine["auth_type"] == "key" and not machine["private_key"] and not machine["key_path"]:
            return {"ok": False, "error": "private_key or key_path required for auth_type=key"}
        if days_until(machine["expiry"]) is None and machine["expiry"]:
            return {"ok": False, "error": "expiry must be YYYY-MM-DD"}
        if self.fleet.get(machine["name"]) is not None:
            return {"ok": False, "error": texts.t("machine_name_taken", name=machine["name"])}
        self.fleet.save(machine)
        ok, error = await self.test_connection(machine)
        if not ok:
            self.fleet.delete(machine["name"])
            return {"ok": False, "error": texts.t("machine_added", name=machine["name"],
                                                  host="", result=texts.t("machine_test_fail", error=error))}
        specs = await self.probe_specs(machine)
        self.audit.record(machine["name"], "ai:eco", "machine_add",
                          f"{machine['username']}@{machine['ip']}")
        return {"ok": True, "name": machine["name"], "specs": specs,
                "expiry": machine["expiry"]}

    async def server_remove(self, name: str = "", **_) -> dict:
        """移除机器（连同其托管会话），凭据从存储删除。"""
        machine_name = str(name or "").strip()
        if self.fleet.get(machine_name) is None:
            return {"ok": False, "error": texts.t("machine_not_found",
                                                  name=machine_name, names=", ".join(self.fleet.names()))}
        for session in self.sessions.list(machine_name):
            await self.sessions.close(machine_name, session["name"])
        removed = self.fleet.delete(machine_name)
        self.audit.record(machine_name, "ai:eco", "machine_remove", machine_name)
        return {"ok": removed, "message": texts.t("machine_removed", name=machine_name)}

    async def server_status(self, name: str = "", **_) -> dict:
        """单机实时状态。"""
        return await self.ops.status(str(name or ""))

    # ---- 执行（admin） ----

    async def server_exec(self, name: str = "", command: str = "", timeout: int = 0,
                          **_) -> dict:
        """执行命令（危险命令返回确认令牌）。"""
        result = await self.ops.exec(str(name or ""), str(command or ""),
                                     actor="ai:eco",
                                     timeout=int(timeout) if timeout else None)
        for field in ("stdout", "stderr"):
            if result.get(field):
                result[field] = truncate_output(result[field])
        return result

    async def server_confirm(self, name: str = "", token: str = "", **_) -> dict:
        """确认并执行被拦截的命令。"""
        machine_name = str(name or "")
        command = self.ops.confirm(machine_name, token, actor="ai:eco")
        if command is None:
            return {"ok": False, "error": texts.t("danger_token_expired")}
        return await self.ops.exec(machine_name, command, actor="ai:eco:confirmed",
                                   confirmed=True)

    async def server_session(self, action: str = "list", name: str = "",
                             session: str = "", command: str = "", lines: int = 30,
                             **_) -> dict:
        """tmux 持久会话管理：open/write/capture/close/list。"""
        machine_name = str(name or "")
        session_name = str(session or "").strip()
        action = str(action or "list").strip().lower()

        if action == "list":
            return {"sessions": self.sessions.list(machine_name or "")}

        machine = self.fleet.get(machine_name)
        if machine is None:
            return {"ok": False, "error": texts.t("machine_not_found",
                                                  name=machine_name, names=", ".join(self.fleet.names()))}
        if not session_name:
            return {"ok": False, "error": "session name required"}

        if action == "open":
            existing = self.sessions.get(machine_name, session_name)
            if existing is not None:
                return {"ok": True, "name": session_name, "mode": existing.mode,
                        "message": texts.t("session_opened", session=session_name,
                                           mode=texts.t("session_mode_tmux" if existing.mode == "tmux" else "session_mode_local"))}
            client = self.make_client(machine)
            try:
                await client.connect()
                opened = await self.sessions.open(machine_name, session_name, client)
            except RuntimeError:
                await client.close()
                return {"ok": False, "error": texts.t("session_limit", limit=self.cfg.max_sessions)}
            except Exception as e:
                await client.close()
                return {"ok": False, "error": str(e)}
            mode_text = texts.t("session_mode_tmux" if opened.mode == "tmux" else "session_mode_local")
            self.audit.record(machine_name, "ai:eco", "session_open", session_name)
            return {"ok": True, "name": session_name, "mode": opened.mode,
                    "message": texts.t("session_opened", session=session_name, mode=mode_text)}

        current = self.sessions.get(machine_name, session_name)
        if current is None:
            return {"ok": False, "error": texts.t("session_not_found", session=session_name)}

        if action == "write":
            if not str(command or "").strip():
                return {"ok": False, "error": "command required"}
            verdict = safety.grade(str(command))
            if verdict["level"] == "confirm":
                token = self.gate.issue(machine_name, str(command))
                return {"ok": False, "needs_confirm": True, "token": token["token"],
                        "level": "confirm", "reason": verdict["reason"],
                        "message": texts.t("danger_confirm_required", reason=verdict["reason"],
                                           command=command, token=token["token"])}
            await current.write(str(command))
            self.audit.record(machine_name, "ai:eco", "session_write", str(command),
                              verdict["level"])
            await _sleep(0.3)
            screen = await current.capture(int(lines))
            return {"ok": True, "screen": truncate_output(screen)}
        if action == "capture":
            screen = await current.capture(int(lines))
            return {"ok": True, "screen": truncate_output(screen)}
        if action == "close":
            closed = await self.sessions.close(machine_name, session_name)
            self.audit.record(machine_name, "ai:eco", "session_close", session_name)
            return {"ok": closed, "message": texts.t("session_closed", session=session_name)}
        return {"ok": False, "error": f"unknown action: {action}"}

    # ---- 传输（admin） ----

    async def server_upload(self, name: str = "", local_path: str = "",
                            remote_path: str = "", **_) -> dict:
        """上传本地沙箱文件。"""
        try:
            info = await self.files_ops.upload(str(name or ""), str(local_path or ""),
                                               str(remote_path or ""), actor="ai:eco")
            info["ok"] = True
            info["message"] = texts.t("upload_done", local=local_path,
                                      machine=name, remote=remote_path,
                                      size=info.get("size_text", ""))
            return info
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def server_download(self, name: str = "", remote_path: str = "",
                              local_path: str = "", **_) -> dict:
        """下载远端文件到沙箱。"""
        try:
            info = await self.files_ops.download(str(name or ""), str(remote_path or ""),
                                                 str(local_path or ""), actor="ai:eco")
            info["ok"] = True
            info["message"] = texts.t("download_done", machine=name, remote=remote_path,
                                      local=local_path, size=info.get("size_text", ""))
            return info
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ---- 审计（admin） ----

    async def server_history(self, name: str = "", limit: int = 20, **_) -> dict:
        """最近审计记录。"""
        rows = self.audit.tail(str(name or ""), max(1, min(int(limit or 20), 100)))
        return {"count": len(rows), "items": rows}

    # ---- 约定服务 ----

    async def qvq_schemas(self, **_) -> dict:
        """参数级 schema。"""
        return {name: dict(schema) for name, schema in SCHEMAS.items()}

    async def qvq_access(self, **_) -> dict:
        """访问级别声明。"""
        return dict(ACCESS)

    async def qvq_settings(self, **_) -> dict:
        """设置页归属标记。"""
        return {"title": "MyServer"}

    async def qvq_extensions(self, **_) -> dict:
        """安全守则提示词注入。"""
        return {"prompts": [dict(item) for item in EXTENSION_PROMPTS]}


async def _sleep(seconds: float) -> None:
    """{!--< internal-use >!--} capture 前短暂等待远端回显。"""
    import asyncio

    await asyncio.sleep(seconds)


def _summary(metrics: dict) -> str:
    """{!--< internal-use >!--} 指标摘要。"""
    from .ssh import summary_line

    return summary_line(metrics) if metrics else ""
