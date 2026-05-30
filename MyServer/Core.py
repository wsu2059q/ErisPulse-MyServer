import asyncio
from typing import Optional, Dict, Any

from ErisPulse import sdk
from ErisPulse.Core.Bases import BaseModule
from ErisPulse.Core.Event import command
from fastapi import Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from .Storage import MachineStorage
from .SSHClient import SSHClient
from .Templates import ServerTemplates


class Main(BaseModule):
    def __init__(self):
        self.sdk = sdk
        self.logger = sdk.logger.get_child("MyServer")
        self.storage = sdk.storage
        self.config = self._load_config()
        self.machine_storage = MachineStorage(self.storage)
        self._ws_sessions: Dict[str, Any] = {}

    @staticmethod
    def get_load_strategy():
        from ErisPulse.loaders import ModuleLoadStrategy
        return ModuleLoadStrategy(
            lazy_load=False,
            priority=50
        )

    async def on_load(self, event):
        self._register_commands()
        self._register_routes()
        self._register_dashboard_view()
        self.logger.info("MyServer 模块已加载")
        return True

    async def on_unload(self, event):
        await self._close_all_sessions()
        self._unregister_routes()
        if hasattr(self.sdk, 'Dashboard') and self.sdk.Dashboard:
            try:
                self.sdk.Dashboard.unregister_view("MyServer")
            except Exception:
                pass
        self.logger.info("MyServer 模块已卸载")
        return True

    async def _close_all_sessions(self):
        for session_id, session in self._ws_sessions.items():
            try:
                if session.get("ssh_client"):
                    await session["ssh_client"].close()
            except Exception:
                pass
        self._ws_sessions.clear()

    def _load_config(self) -> dict:
        config = sdk.config.getConfig("MyServer")
        if not config:
            default_config = {
                "exec_timeout": 30,
                "admin_users": [],
                "max_ssh_connections": 5,
            }
            sdk.config.setConfig("MyServer", default_config, immediate=True)
            self.logger.info("已创建默认配置")
            return default_config
        return config

    def _check_permission(self, user_id: str, level: str = "exec") -> bool:
        admin_users = self.config.get("admin_users", [])
        if not admin_users:
            return True
        return user_id in admin_users

    def _select_best_format(self, platform: str, templates: Dict[str, str]) -> tuple:
        try:
            supported_methods = sdk.adapter.list_sends(platform)
            if "Html" in supported_methods:
                return ("Html", templates["html"])
            elif "Markdown" in supported_methods:
                return ("Markdown", templates["markdown"])
            else:
                return ("Text", templates["text"])
        except Exception:
            return ("Text", templates["text"])

    async def _send_with_fallback(self, event, content_dict: Dict[str, str]):
        platform = event.get_platform()

        sent = False
        try:
            supported_methods = sdk.adapter.list_sends(platform)
            if "Html" in supported_methods:
                await event.reply(content_dict["html"], method="Html")
                sent = True
            elif "Markdown" in supported_methods:
                await event.reply(content_dict["markdown"], method="Markdown")
                sent = True
        except Exception:
            pass

        if not sent:
            try:
                await event.reply(content_dict["text"])
            except Exception as e:
                self.logger.error(f"发送消息失败: {e}")

    def _register_commands(self):
        @command("server", help="服务器管理", usage="/server [子命令] [参数]")
        async def server_handler(event):
            args = event.get_command_args()

            if not args:
                await self._cmd_list(event, [])
                return

            sub_cmd = args[0].lower()
            sub_args = args[1:]

            handlers = {
                "list": self._cmd_list,
                "ls": self._cmd_list,
                "info": self._cmd_info,
                "i": self._cmd_info,
                "add": self._cmd_add,
                "del": self._cmd_del,
                "rm": self._cmd_del,
                "exec": self._cmd_exec,
                "x": self._cmd_exec,
                "ssh": self._cmd_exec,
                "help": self._show_help,
            }

            handler = handlers.get(sub_cmd)
            if handler:
                await handler(event, sub_args)
            else:
                await self._cmd_exec(event, args)

    async def _show_help(self, event, args=None):
        templates = ServerTemplates.build_help()
        await self._send_with_fallback(event, templates)

    async def _cmd_list(self, event, args):
        machines = self.machine_storage.get_all_machines()
        if not machines:
            await event.reply("暂无服务器\n\n使用 /server add 添加服务器")
            return

        for machine in machines:
            status = await self._get_machine_status(machine, timeout=10)
            machine["status"] = status.get("online", False)
            self.machine_storage.save_status(machine["name"], status)

        templates = ServerTemplates.build_machine_list(machines)
        await self._send_with_fallback(event, templates)

    async def _cmd_info(self, event, args):
        machines = self.machine_storage.get_all_machines()

        if not machines:
            await event.reply("暂无服务器")
            return

        for machine in machines:
            status = await self._get_machine_status(machine, timeout=10)
            machine["status_data"] = status
            machine["status"] = status.get("online", False)
            self.machine_storage.save_status(machine["name"], status)

        templates = ServerTemplates.build_all_machines_detail(machines)
        await self._send_with_fallback(event, templates)

    async def _cmd_add(self, event, args):
        if not self._check_permission(event.get_user_id(), "admin"):
            await event.reply("权限不足，仅管理员可添加服务器")
            return

        conv = event.conversation(timeout=180)
        await conv.say(
            "添加服务器\n"
            "请按提示输入信息，发送 取消 可中止"
        )

        data = await conv.collect([
            {"key": "name", "prompt": "请输入服务器名称（用于标识）:"},
            {"key": "ip", "prompt": "请输入IP地址:"},
            {"key": "port", "prompt": "请输入SSH端口（直接回复默认22）:",
             "validator": lambda e: e.get_text().strip().isdigit() or e.get_text().strip() == ""},
            {"key": "username", "prompt": "请输入SSH用户名:"},
            {"key": "auth_type", "prompt": "请选择认证方式:\n1. 密码\n2. 私钥\n请输入 1 或 2:"},
        ])

        if not data:
            await conv.say("添加已取消或超时")
            return

        if self.machine_storage.machine_exists(data["name"]):
            await conv.say(f"服务器 {data['name']} 已存在")
            return

        auth_type = data.get("auth_type", "1").strip()
        password = ""
        private_key = ""

        if auth_type == "2":
            key_data = await conv.collect([
                {"key": "private_key", "prompt": "请输入私钥内容（直接粘贴）:"},
            ])
            if key_data:
                private_key = key_data["private_key"]
        else:
            pass_data = await conv.collect([
                {"key": "password", "prompt": "请输入SSH密码:"},
            ])
            if pass_data:
                password = pass_data["password"]

        machine = {
            "name": data["name"],
            "ip": data["ip"],
            "port": int(data["port"] or "22"),
            "username": data["username"],
            "password": password,
            "private_key": private_key,
            "auth_type": "key" if auth_type == "2" else "password",
            "tags": [],
            "notes": "",
            "added_by": event.get_user_id()
        }
        self.machine_storage.save_machine(machine)
        await conv.say(f"已添加服务器: {machine['name']}")

    async def _cmd_del(self, event, args):
        if not self._check_permission(event.get_user_id(), "admin"):
            await event.reply("权限不足，仅管理员可删除服务器")
            return

        machines = self.machine_storage.get_all_machines()

        if not machines:
            await event.reply("暂无服务器")
            return

        if not args:
            choice = await event.choose(
                "请选择要删除的服务器:",
                [m["name"] for m in machines]
            )
            if choice is None:
                await event.reply("选择超时")
                return
            machine_name = machines[choice]["name"]
        else:
            machine_name = args[0]

        machine = self.machine_storage.get_machine(machine_name)
        if not machine:
            await event.reply(f"未找到服务器: {machine_name}")
            return

        confirmed = await event.confirm(
            f"确认删除服务器 {machine_name}?\n此操作不可撤销"
        )

        if confirmed:
            self.machine_storage.delete_machine(machine_name)
            await event.reply(f"已删除服务器: {machine_name}")
        else:
            await event.reply("已取消删除")

    async def _cmd_exec(self, event, args):
        machines = self.machine_storage.get_all_machines()

        if not machines:
            await event.reply("暂无服务器，请先使用 /server add 添加")
            return

        if not args:
            choice = await event.choose(
                "请选择要连接的服务器:",
                [m["name"] for m in machines]
            )
            if choice is None:
                await event.reply("选择超时")
                return
            machine = machines[choice]
        else:
            machine_name = args[0]
            machine = self.machine_storage.get_machine(machine_name)
            if not machine:
                await event.reply(f"未找到服务器: {machine_name}")
                return

        timeout = self.config.get("exec_timeout", 30)
        conv = event.conversation(timeout=300)

        await conv.say(
            f"已连接: {machine['name']} ({machine['ip']}:{machine['port']})\n"
            f"\n"
            f"输入命令执行 | exit 断开 | ctrl+c 中断 | clear 清屏"
        )

        ssh_client = None
        try:
            ssh_client = self._create_ssh_client(machine)
            await ssh_client.connect()
        except Exception as e:
            await conv.say(f"SSH连接失败: {e}")
            return

        while conv.is_active:
            reply = await conv.wait()

            if reply is None:
                await conv.say("会话超时，已断开连接")
                break

            cmd = reply.get_text().strip()

            if cmd.lower() in ["exit", "quit", "退出"]:
                await conv.say("已断开连接")
                break

            if not cmd:
                continue

            if cmd.lower() in ["ctrl+c", "interrupt", "中断", "kill"]:
                if ssh_client._current_process:
                    try:
                        ssh_client._current_process.terminate()
                        await conv.say("已中断当前命令")
                    except Exception:
                        await conv.say("没有正在运行的命令")
                else:
                    await conv.say("没有正在运行的命令")
                continue

            if cmd.lower() in ["ctrl+z", "suspend", "挂起"]:
                if ssh_client._current_process:
                    try:
                        ssh_client._current_process.send_signal("SIGTSTP")
                        await conv.say("已挂起当前命令")
                    except Exception:
                        await conv.say("没有正在运行的命令")
                else:
                    await conv.say("没有正在运行的命令")
                continue

            if cmd.lower() in ["ctrl+d", "eof"]:
                if ssh_client._current_process:
                    try:
                        ssh_client._current_process.stdin.write_eof()
                        await conv.say("已发送EOF")
                    except Exception:
                        await conv.say("没有正在运行的命令")
                else:
                    await conv.say("没有正在运行的命令")
                continue

            if cmd.lower() in ["ctrl+l", "clear", "清屏"]:
                await conv.say("\n" * 50 + "屏幕已清除")
                continue

            interactive_programs = {
                "python3": "python3 -c",
                "python": "python -c",
                "node": "node -e",
                "bash": "bash -c",
                "sh": "sh -c",
                "ruby": "ruby -e",
                "perl": "perl -e",
                "php": "php -r",
                "lua": "lua -e",
                "mysql": "mysql -e",
                "redis-cli": "redis-cli",
                "psql": "psql -c",
            }

            cmd_parts = cmd.split()
            cmd_name = cmd_parts[0] if cmd_parts else ""
            cmd_args = cmd_parts[1:] if len(cmd_parts) > 1 else []

            if cmd_name in interactive_programs and not any(
                arg in ["-c", "-e", "--command", "-c", "--eval"] for arg in cmd_args
            ):
                await conv.say(
                    f"检测到交互式程序: {cmd_name}\n"
                    f"\n"
                    f"示例用法:\n"
                    f"  {cmd_name} -c \"print('hello')\"\n"
                    f"  {cmd_name} -c \"import os; os.listdir('.')\"\n"
                    f"\n"
                    f"或者使用快捷命令:\n"
                    f"  py <代码>       执行Python代码\n"
                    f"  node <代码>     执行Node代码\n"
                    f"  bash <命令>     执行Bash命令"
                )
                continue

            if cmd_name == "py" and cmd_args:
                python_cmd = f"python3 -c \"{' '.join(cmd_args)}\""
                result = await ssh_client.exec_command(python_cmd, timeout=timeout)
            elif cmd_name == "node" and cmd_args:
                node_cmd = f"node -e \"{' '.join(cmd_args)}\""
                result = await ssh_client.exec_command(node_cmd, timeout=timeout)
            elif cmd_name == "bash" and cmd_args:
                bash_cmd = f"bash -c \"{' '.join(cmd_args)}\""
                result = await ssh_client.exec_command(bash_cmd, timeout=timeout)
            else:
                result = await ssh_client.exec_command(cmd, timeout=timeout)

            templates = ServerTemplates.build_exec_result(machine["name"], cmd, result)
            platform = event.get_platform()

            sent = False
            try:
                supported_methods = sdk.adapter.list_sends(platform)
                if "Html" in supported_methods:
                    await conv.say(templates["html"], method="Html")
                    sent = True
                elif "Markdown" in supported_methods:
                    await conv.say(templates["markdown"], method="Markdown")
                    sent = True
            except Exception:
                pass

            if not sent:
                try:
                    await conv.say(templates["text"])
                except Exception:
                    pass

        if ssh_client:
            await ssh_client.close()

    def _create_ssh_client(self, machine: dict) -> SSHClient:
        auth_type = machine.get("auth_type", "password")

        if auth_type == "key":
            private_key = machine.get("private_key", "")
            key_path = None
            if private_key and not private_key.startswith("/"):
                import tempfile
                import os
                fd, key_path = tempfile.mkstemp(suffix=".pem", prefix="myserver_")
                with os.fdopen(fd, 'w') as f:
                    f.write(private_key)
                os.chmod(key_path, 0o600)

            return SSHClient(
                host=machine["ip"],
                port=machine["port"],
                username=machine["username"],
                key_path=key_path or machine.get("key_path", ""),
            )
        else:
            return SSHClient(
                host=machine["ip"],
                port=machine["port"],
                username=machine["username"],
                password=machine.get("password", ""),
            )

    async def _get_machine_status(self, machine: dict, timeout: int = 10) -> dict:
        status = {"online": False, "sysinfo": {}}

        try:
            async def _check():
                ssh_client = self._create_ssh_client(machine)
                await ssh_client.connect()
                alive = await ssh_client.check_alive()

                if alive:
                    status["online"] = True
                    sysinfo = await ssh_client.get_system_info()
                    status["sysinfo"] = sysinfo

                await ssh_client.close()
                return status

            return await asyncio.wait_for(_check(), timeout=timeout)
        except asyncio.TimeoutError:
            status["online"] = False
            status["error"] = "连接超时"
            return status
        except Exception as e:
            status["online"] = False
            status["error"] = str(e)
            return status

    def get_all_machines(self):
        return self.machine_storage.get_all_machines()

    def get_machine(self, name: str):
        return self.machine_storage.get_machine(name)

    def save_machine(self, machine: dict):
        return self.machine_storage.save_machine(machine)

    def delete_machine(self, name: str):
        return self.machine_storage.delete_machine(name)

    def _register_routes(self):
        r = self.sdk.router
        mn = "MyServer"

        r.register_http_route(mn, "/api/machines", handler=self._api_machines, methods=["GET"])
        r.register_http_route(mn, "/api/machines", handler=self._api_machine_add, methods=["POST"])
        r.register_http_route(mn, "/api/machines/{name}", handler=self._api_machine_delete, methods=["DELETE"])
        r.register_http_route(mn, "/api/machines/{name}/status", handler=self._api_machine_status, methods=["GET"])
        r.register_http_route(mn, "/api/machines/{name}/exec", handler=self._api_machine_exec, methods=["POST"])
        r.register_websocket(mn, "/ws/terminal", handler=self._ws_terminal, auth_handler=self._ws_auth)

    def _unregister_routes(self):
        r = self.sdk.router
        mn = "MyServer"
        for p in ["/api/machines", "/api/machines/{name}", "/api/machines/{name}/status", "/api/machines/{name}/exec"]:
            try:
                r.unregister_http_route(mn, p)
            except Exception:
                pass
        try:
            r.unregister_websocket(mn, "/ws/terminal")
        except Exception:
            pass

    async def _ws_auth(self, websocket: WebSocket) -> bool:
        token = websocket.query_params.get("token", "")
        if not token:
            return False
        try:
            if hasattr(self.sdk, 'Dashboard') and self.sdk.Dashboard:
                return self.sdk.Dashboard.verify_token(token)
        except Exception:
            pass
        return False

    def _verify_token(self, request: Request) -> bool:
        try:
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                token = auth[7:]
            else:
                token = request.query_params.get("token")

            if not token:
                return False

            if hasattr(self.sdk, 'Dashboard') and self.sdk.Dashboard:
                return self.sdk.Dashboard.verify_token(token)
        except Exception:
            pass
        return False

    async def _api_machines(self, request: Request) -> JSONResponse:
        if not self._verify_token(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        machines = self.machine_storage.get_all_machines()
        for m in machines:
            m.pop("password", None)
            m.pop("private_key", None)
        return JSONResponse({"machines": machines})

    async def _api_machine_add(self, request: Request) -> JSONResponse:
        if not self._verify_token(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        body = await request.json()
        name = body.get("name", "").strip()
        ip = body.get("ip", "").strip()
        port = body.get("port", 22)
        username = body.get("username", "").strip()
        auth_type = body.get("auth_type", "password")
        password = body.get("password", "")
        private_key = body.get("private_key", "")

        if not name or not ip or not username:
            return JSONResponse({"error": "Missing required fields"}, status_code=400)

        if self.machine_storage.machine_exists(name):
            return JSONResponse({"error": "Server already exists"}, status_code=400)

        machine = {
            "name": name,
            "ip": ip,
            "port": int(port) if port else 22,
            "username": username,
            "auth_type": auth_type,
            "password": password if auth_type == "password" else "",
            "private_key": private_key if auth_type == "key" else "",
            "tags": [],
            "notes": "",
        }

        if self.machine_storage.save_machine(machine):
            return JSONResponse({"success": True})
        else:
            return JSONResponse({"error": "Failed to save"}, status_code=500)

    async def _api_machine_delete(self, request: Request) -> JSONResponse:
        if not self._verify_token(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        name = request.path_params.get("name", "")
        if not name:
            return JSONResponse({"error": "Name required"}, status_code=400)

        if self.machine_storage.delete_machine(name):
            return JSONResponse({"success": True})
        else:
            return JSONResponse({"error": "Server not found"}, status_code=404)

    async def _api_machine_status(self, request: Request) -> JSONResponse:
        if not self._verify_token(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        name = request.path_params.get("name", "")
        machine = self.machine_storage.get_machine(name)
        if not machine:
            return JSONResponse({"error": "Server not found"}, status_code=404)

        status = await self._get_machine_status(machine)
        return JSONResponse({"status": status})

    async def _api_machine_exec(self, request: Request) -> JSONResponse:
        if not self._verify_token(request):
            return JSONResponse({"error": "Unauthorized"}, status_code=401)

        name = request.path_params.get("name", "")
        machine = self.machine_storage.get_machine(name)
        if not machine:
            return JSONResponse({"error": "Server not found"}, status_code=404)

        body = await request.json()
        cmd = body.get("command", "")
        if not cmd:
            return JSONResponse({"error": "Command required"}, status_code=400)

        try:
            ssh_client = self._create_ssh_client(machine)
            await ssh_client.connect()
            result = await ssh_client.exec_command(cmd, timeout=30, use_pty=False)
            await ssh_client.close()
            return JSONResponse({"result": result})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def _ws_terminal(self, websocket: WebSocket):
        session_id = None
        ssh_client = None
        shell = None

        try:
            init_msg = await asyncio.wait_for(websocket.receive_json(), timeout=30)
            server_name = init_msg.get("server", "")

            if not server_name:
                await websocket.send_json({"type": "error", "message": "未指定服务器"})
                return

            machine = self.machine_storage.get_machine(server_name)
            if not machine:
                await websocket.send_json({"type": "error", "message": f"服务器 {server_name} 不存在"})
                return

            import uuid
            session_id = str(uuid.uuid4())

            ssh_client = self._create_ssh_client(machine)
            await ssh_client.connect()

            cols = init_msg.get("cols", 80)
            rows = init_msg.get("rows", 24)

            shell = await ssh_client._conn.create_process(
                term_type="xterm-256color",
                term_size=(cols, rows),
                encoding="utf-8"
            )

            self._ws_sessions[session_id] = {
                "ssh_client": ssh_client,
                "shell": shell,
                "machine": machine
            }

            await websocket.send_json({
                "type": "connected",
                "server": server_name,
                "session": session_id
            })

            async def read_output():
                try:
                    while True:
                        try:
                            data = await asyncio.wait_for(shell.stdout.read(4096), timeout=0.1)
                            if data:
                                await websocket.send_json({"type": "output", "data": data})
                        except asyncio.TimeoutError:
                            continue
                        except Exception as e:
                            break
                except Exception:
                    pass

            read_task = asyncio.create_task(read_output())

            try:
                while True:
                    try:
                        msg = await asyncio.wait_for(websocket.receive_json(), timeout=30)
                    except asyncio.TimeoutError:
                        await websocket.send_json({"type": "ping"})
                        continue

                    msg_type = msg.get("type")

                    if msg_type == "input":
                        data = msg.get("data", "")
                        shell.stdin.write(data)
                        await shell.stdin.drain()

                    elif msg_type == "resize":
                        new_cols = msg.get("cols", 80)
                        new_rows = msg.get("rows", 24)
                        try:
                            await shell.change_terminal_size(new_cols, new_rows)
                        except Exception:
                            pass

                    elif msg_type == "pong":
                        continue

            except WebSocketDisconnect:
                pass
            finally:
                read_task.cancel()
                try:
                    await read_task
                except (asyncio.CancelledError, Exception):
                    pass

        except WebSocketDisconnect:
            pass
        except asyncio.TimeoutError:
            try:
                await websocket.send_json({"type": "error", "message": "连接超时"})
            except Exception:
                pass
        except Exception as e:
            self.logger.error(f"WebSocket terminal error: {e}")
            try:
                await websocket.send_json({"type": "error", "message": str(e)})
            except Exception:
                pass
        finally:
            if session_id and session_id in self._ws_sessions:
                del self._ws_sessions[session_id]
            if ssh_client:
                try:
                    await ssh_client.close()
                except Exception:
                    pass

    def _register_dashboard_view(self):
        try:
            if not hasattr(self.sdk, 'Dashboard') or not self.sdk.Dashboard:
                return

            self.sdk.Dashboard.register_view(
                id="MyServer",
                title="我的服务器",
                title_en="My Server",
                icon_svg='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><circle cx="6" cy="6" r="1"/><circle cx="6" cy="18" r="1"/><line x1="10" y1="6" x2="18" y2="6"/><line x1="10" y1="18" x2="18" y2="18"/></svg>',
                html_content=self._get_dashboard_html(),
                js_content=self._get_dashboard_js(),
                css_content=self._get_dashboard_css(),
                loader="loadMyServerView",
                group="group_tools",
            )
            self.logger.info("Dashboard view registered")
        except Exception as e:
            self.logger.warning(f"Failed to register Dashboard view: {e}")

    def _get_dashboard_html(self):
        return '''
            <h1 class="page-title">我的服务器</h1>
            <p style="color:var(--tx-s);margin-bottom:16px">管理和监控你的服务器</p>

            <div class="grid-3" style="margin-bottom:16px">
                <div class="card">
                    <div class="card-header">服务器总数</div>
                    <div class="card-body">
                        <div id="myserver-total" style="font-size:32px;font-weight:bold;color:var(--accent)">0</div>
                    </div>
                </div>
                <div class="card">
                    <div class="card-header">在线</div>
                    <div class="card-body">
                        <div id="myserver-online" style="font-size:32px;font-weight:bold;color:var(--ok-c)">0</div>
                    </div>
                </div>
                <div class="card">
                    <div class="card-header">离线</div>
                    <div class="card-body">
                        <div id="myserver-offline" style="font-size:32px;font-weight:bold;color:var(--er-c)">0</div>
                    </div>
                </div>
            </div>

            <div class="card" style="margin-bottom:16px">
                <div class="card-header">
                    服务器列表
                    <div style="float:right;display:flex;gap:8px">
                        <button class="btn btn-primary" onclick="myserverShowAdd()">添加服务器</button>
                        <button class="btn btn-secondary" onclick="myserverRefresh()">刷新</button>
                    </div>
                </div>
                <div class="card-body">
                    <div id="myserver-list">加载中...</div>
                </div>
            </div>

            <div id="myserver-add-section" class="card" style="margin-bottom:16px;display:none">
                <div class="card-header">
                    添加服务器
                    <button class="btn btn-secondary" onclick="myserverHideAdd()" style="float:right">取消</button>
                </div>
                <div class="card-body">
                    <div style="display:grid;gap:12px;max-width:400px">
                        <div>
                            <label style="display:block;margin-bottom:4px;font-size:13px;color:var(--tx-s)">服务器名称</label>
                            <input id="myserver-add-name" type="text" placeholder="my-server" style="width:100%;padding:8px;border:1px solid var(--bd);border-radius:4px;background:var(--bg-p);color:var(--tx-p)">
                        </div>
                        <div>
                            <label style="display:block;margin-bottom:4px;font-size:13px;color:var(--tx-s)">IP地址</label>
                            <input id="myserver-add-ip" type="text" placeholder="1.2.3.4" style="width:100%;padding:8px;border:1px solid var(--bd);border-radius:4px;background:var(--bg-p);color:var(--tx-p)">
                        </div>
                        <div>
                            <label style="display:block;margin-bottom:4px;font-size:13px;color:var(--tx-s)">SSH端口</label>
                            <input id="myserver-add-port" type="text" placeholder="22" value="22" style="width:100%;padding:8px;border:1px solid var(--bd);border-radius:4px;background:var(--bg-p);color:var(--tx-p)">
                        </div>
                        <div>
                            <label style="display:block;margin-bottom:4px;font-size:13px;color:var(--tx-s)">用户名</label>
                            <input id="myserver-add-username" type="text" placeholder="root" style="width:100%;padding:8px;border:1px solid var(--bd);border-radius:4px;background:var(--bg-p);color:var(--tx-p)">
                        </div>
                        <div>
                            <label style="display:block;margin-bottom:4px;font-size:13px;color:var(--tx-s)">认证方式</label>
                            <select id="myserver-add-auth" style="width:100%;padding:8px;border:1px solid var(--bd);border-radius:4px;background:var(--bg-p);color:var(--tx-p)" onchange="myserverToggleAuth()">
                                <option value="password">密码</option>
                                <option value="key">私钥</option>
                            </select>
                        </div>
                        <div id="myserver-add-password-group">
                            <label style="display:block;margin-bottom:4px;font-size:13px;color:var(--tx-s)">密码</label>
                            <input id="myserver-add-password" type="password" style="width:100%;padding:8px;border:1px solid var(--bd);border-radius:4px;background:var(--bg-p);color:var(--tx-p)">
                        </div>
                        <div id="myserver-add-key-group" style="display:none">
                            <label style="display:block;margin-bottom:4px;font-size:13px;color:var(--tx-s)">私钥内容</label>
                            <textarea id="myserver-add-key" rows="6" placeholder="-----BEGIN OPENSSH PRIVATE KEY-----" style="width:100%;padding:8px;border:1px solid var(--bd);border-radius:4px;background:var(--bg-p);color:var(--tx-p);font-family:monospace;font-size:12px"></textarea>
                        </div>
                        <div>
                            <button class="btn btn-primary" onclick="myserverAddServer()" style="width:100%">添加</button>
                        </div>
                    </div>
                </div>
            </div>

            <div id="myserver-terminal-section" class="card" style="display:none">
                <div class="card-header">
                    <span id="myserver-terminal-title">终端</span>
                    <span id="myserver-terminal-status" style="margin-left:8px;font-size:12px"></span>
                    <button class="btn btn-secondary" onclick="myserverCloseTerminal()" style="float:right">关闭</button>
                </div>
                <div class="card-body" style="padding:0">
                    <div id="myserver-terminal-container" style="height:400px;background:#1a1b26"></div>
                </div>
            </div>
        '''

    def _get_dashboard_css(self):
        return '''
            #myserver-terminal-container .xterm { padding: 4px; }
            #myserver-terminal-container .xterm-viewport::-webkit-scrollbar { width: 8px; }
            #myserver-terminal-container .xterm-viewport::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.2); border-radius: 4px; }

            .myserver-card {
                padding: 16px;
                border: 1px solid var(--bd);
                border-radius: 8px;
                margin-bottom: 12px;
                background: var(--bg-p);
                transition: box-shadow 0.2s;
            }
            .myserver-card:hover {
                box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            }
            .myserver-card-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 12px;
            }
            .myserver-card-name {
                font-weight: 600;
                font-size: 15px;
                color: var(--tx-p);
            }
            .myserver-card-status {
                font-size: 12px;
                padding: 3px 10px;
                border-radius: 12px;
                font-weight: 500;
            }
            .myserver-card-status.online {
                background: rgba(158,206,106,0.15);
                color: var(--ok-c);
            }
            .myserver-card-status.offline {
                background: rgba(247,118,142,0.15);
                color: var(--er-c);
            }
            .myserver-card-actions {
                display: flex;
                gap: 8px;
                margin-top: 12px;
            }

            .myserver-stats {
                display: grid;
                grid-template-columns: repeat(6, 1fr);
                gap: 8px;
                margin-bottom: 12px;
            }
            .myserver-stat {
                padding: 10px;
                background: var(--bg-s);
                border-radius: 6px;
                text-align: center;
            }
            .myserver-stat-label {
                font-size: 11px;
                color: var(--tx-s);
                margin-bottom: 4px;
            }
            .myserver-stat-value {
                font-size: 13px;
                font-weight: 600;
                color: var(--tx-p);
            }
            .myserver-stat-sub {
                font-size: 10px;
                color: var(--tx-t);
                margin-top: 2px;
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
            }

            @media (max-width: 768px) {
                .myserver-stats {
                    grid-template-columns: repeat(3, 1fr);
                }
            }

            .myserver-add-section input,
            .myserver-add-section select,
            .myserver-add-section textarea {
                transition: border-color 0.2s;
            }
            .myserver-add-section input:focus,
            .myserver-add-section select:focus,
            .myserver-add-section textarea:focus {
                border-color: var(--accent);
                outline: none;
            }
        '''

    def _get_dashboard_js(self):
        return '''
            let myserverCurrentServer = "";
            let myserverTerm = null;
            let myserverWs = null;
            let myserverFitAddon = null;
            let myserverDetailCache = {};

            async function loadMyServerView() {
                await myserverRefresh();
                myserverLoadXterm();
            }

            async function myserverLoadXterm() {
                if (window.Terminal) return;

                var loadScript = function(src) {
                    return new Promise(function(resolve, reject) {
                        var script = document.createElement('script');
                        script.src = src;
                        script.onload = resolve;
                        script.onerror = reject;
                        document.head.appendChild(script);
                    });
                };

                var loadCss = function(href) {
                    if (document.querySelector('link[href="' + href + '"]')) return;
                    var link = document.createElement('link');
                    link.rel = 'stylesheet';
                    link.href = href;
                    document.head.appendChild(link);
                };

                loadCss('https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/css/xterm.min.css');

                try {
                    await loadScript('https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/lib/xterm.min.js');
                    await loadScript('https://cdn.jsdelivr.net/npm/@xterm/addon-fit@0.10.0/lib/addon-fit.min.js');
                } catch (e) {
                    console.error('Failed to load xterm:', e);
                }
            }

            function myserverRenderCard(m, detail) {
                var statusClass = m.status ? 'online' : 'offline';
                var statusText = m.status ? '在线' : '离线';

                var html = '<div class="myserver-card" id="myserver-card-' + m.name + '">';
                html += '<div class="myserver-card-header">';
                html += '<span class="myserver-card-name">' + m.name + '</span>';
                html += '<span class="myserver-card-status ' + statusClass + '">' + statusText + '</span>';
                html += '</div>';

                if (detail && detail.online && detail.sysinfo) {
                    var sys = detail.sysinfo;
                    html += '<div class="myserver-stats">';
                    html += '<div class="myserver-stat"><div class="myserver-stat-label">CPU</div><div class="myserver-stat-value">' + (sys.cpu_cores || '?') + ' 核</div>' + (sys.cpu_model ? '<div class="myserver-stat-sub">' + sys.cpu_model + '</div>' : '') + '</div>';
                    html += '<div class="myserver-stat"><div class="myserver-stat-label">内存</div><div class="myserver-stat-value">' + (sys.memory || '?') + '</div></div>';
                    html += '<div class="myserver-stat"><div class="myserver-stat-label">磁盘</div><div class="myserver-stat-value">' + (sys.disk || '?') + '</div></div>';
                    html += '<div class="myserver-stat"><div class="myserver-stat-label">负载</div><div class="myserver-stat-value">' + (sys.load || '?') + '</div></div>';
                    html += '<div class="myserver-stat"><div class="myserver-stat-label">内核</div><div class="myserver-stat-value">' + (sys.kernel || '?') + '</div></div>';
                    html += '<div class="myserver-stat"><div class="myserver-stat-label">运行</div><div class="myserver-stat-value">' + (sys.uptime || '?') + '</div></div>';
                    html += '</div>';
                } else if (detail && !detail.online) {
                    html += '<div style="color:var(--er-c);font-size:13px;margin-bottom:8px">离线</div>';
                } else {
                    html += '<div style="color:var(--tx-s);font-size:13px;margin-bottom:8px">获取信息中...</div>';
                }

                html += '<div class="myserver-card-actions">';
                html += '<button class="btn btn-primary" onclick="myserverOpenTerminal(\\'' + m.name + '\\')">终端</button>';
                html += '<button class="btn btn-danger" onclick="myserverDeleteServer(\\'' + m.name + '\\')">删除</button>';
                html += '</div>';
                html += '</div>';

                return html;
            }

            async function myserverRefresh() {
                var el = document.getElementById('myserver-list');
                if (!el) return;

                try {
                    var token = localStorage.getItem('__ep_tk__');
                    var resp = await fetch('/MyServer/api/machines', {
                        headers: { 'Authorization': 'Bearer ' + token }
                    });
                    var data = await resp.json();
                    var machines = data.machines || [];

                    document.getElementById('myserver-total').textContent = machines.length;
                    document.getElementById('myserver-online').textContent = machines.filter(m => m.status).length;
                    document.getElementById('myserver-offline').textContent = machines.filter(m => !m.status).length;

                    if (machines.length === 0) {
                        el.innerHTML = '<div style="color:var(--tx-s);text-align:center;padding:40px">暂无服务器，点击上方"添加服务器"开始</div>';
                        return;
                    }

                    var html = '';
                    machines.forEach(function(m) {
                        var detail = myserverDetailCache[m.name] || null;
                        html += myserverRenderCard(m, detail);
                    });
                    el.innerHTML = html;

                    for (var i = 0; i < machines.length; i++) {
                        myserverFetchDetail(machines[i].name);
                    }
                } catch (e) {
                    el.textContent = '加载失败: ' + e.message;
                }
            }

            async function myserverFetchDetail(name) {
                try {
                    var token = localStorage.getItem('__ep_tk__');
                    var resp = await fetch('/MyServer/api/machines/' + encodeURIComponent(name) + '/status', {
                        headers: { 'Authorization': 'Bearer ' + token }
                    });
                    var data = await resp.json();
                    if (data.status) {
                        myserverDetailCache[name] = data.status;
                        myserverUpdateCard(name, data.status);
                    }
                } catch (e) {
                    console.error('Failed to fetch detail for ' + name + ':', e);
                }
            }

            function myserverUpdateCard(name, status) {
                var card = document.getElementById('myserver-card-' + name);
                if (!card) return;

                var machine = { name: name, status: status.online };
                var newHtml = myserverRenderCard(machine, status);
                var tempDiv = document.createElement('div');
                tempDiv.innerHTML = newHtml;
                var newCard = tempDiv.firstChild;
                card.replaceWith(newCard);
            }

            function myserverShowAdd() {
                document.getElementById('myserver-add-section').style.display = 'block';
                document.getElementById('myserver-add-name').focus();
            }

            function myserverHideAdd() {
                document.getElementById('myserver-add-section').style.display = 'none';
                document.getElementById('myserver-add-name').value = '';
                document.getElementById('myserver-add-ip').value = '';
                document.getElementById('myserver-add-port').value = '22';
                document.getElementById('myserver-add-username').value = '';
                document.getElementById('myserver-add-password').value = '';
                document.getElementById('myserver-add-key').value = '';
            }

            function myserverToggleAuth() {
                var auth = document.getElementById('myserver-add-auth').value;
                document.getElementById('myserver-add-password-group').style.display = auth === 'password' ? 'block' : 'none';
                document.getElementById('myserver-add-key-group').style.display = auth === 'key' ? 'block' : 'none';
            }

            async function myserverAddServer() {
                var name = document.getElementById('myserver-add-name').value.trim();
                var ip = document.getElementById('myserver-add-ip').value.trim();
                var port = document.getElementById('myserver-add-port').value.trim() || '22';
                var username = document.getElementById('myserver-add-username').value.trim();
                var auth = document.getElementById('myserver-add-auth').value;
                var password = document.getElementById('myserver-add-password').value;
                var key = document.getElementById('myserver-add-key').value;

                if (!name || !ip || !username) {
                    alert('请填写必要信息');
                    return;
                }

                try {
                    var token = localStorage.getItem('__ep_tk__');
                    var resp = await fetch('/MyServer/api/machines', {
                        method: 'POST',
                        headers: {
                            'Authorization': 'Bearer ' + token,
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({
                            name: name,
                            ip: ip,
                            port: parseInt(port),
                            username: username,
                            auth_type: auth,
                            password: password,
                            private_key: key
                        })
                    });

                    var data = await resp.json();
                    if (data.success) {
                        myserverHideAdd();
                        await myserverRefresh();
                    } else {
                        alert('添加失败: ' + (data.error || '未知错误'));
                    }
                } catch (e) {
                    alert('添加失败: ' + e.message);
                }
            }

            async function myserverDeleteServer(name) {
                if (!confirm('确认删除服务器 ' + name + '？此操作不可撤销。')) return;

                try {
                    var token = localStorage.getItem('__ep_tk__');
                    var resp = await fetch('/MyServer/api/machines/' + encodeURIComponent(name), {
                        method: 'DELETE',
                        headers: { 'Authorization': 'Bearer ' + token }
                    });

                    var data = await resp.json();
                    if (data.success) {
                        delete myserverDetailCache[name];
                        await myserverRefresh();
                    } else {
                        alert('删除失败: ' + (data.error || '未知错误'));
                    }
                } catch (e) {
                    alert('删除失败: ' + e.message);
                }
            }

            async function myserverOpenTerminal(name) {
                if (myserverWs) {
                    myserverCloseTerminal();
                }

                myserverCurrentServer = name;
                var section = document.getElementById('myserver-terminal-section');
                var title = document.getElementById('myserver-terminal-title');
                var status = document.getElementById('myserver-terminal-status');
                var container = document.getElementById('myserver-terminal-container');

                title.textContent = name + ' - 终端';
                status.textContent = '连接中...';
                status.style.color = 'var(--tx-s)';
                section.style.display = 'block';

                container.innerHTML = '';

                if (!window.Terminal) {
                    await myserverLoadXterm();
                }

                if (!window.Terminal) {
                    container.innerHTML = '<div style="padding:20px;color:var(--er-c)">加载终端组件失败</div>';
                    return;
                }

                myserverTerm = new Terminal({
                    theme: {
                        background: '#1a1b26',
                        foreground: '#c0caf5',
                        cursor: '#c0caf5',
                        cursorAccent: '#1a1b26',
                        selectionBackground: 'rgba(51, 70, 124, 0.5)',
                        selectionForeground: '#c0caf5',
                        black: '#15161e',
                        red: '#f7768e',
                        green: '#9ece6a',
                        yellow: '#e0af68',
                        blue: '#7aa2f7',
                        magenta: '#bb9af7',
                        cyan: '#7dcfff',
                        white: '#a9b1d6',
                        brightBlack: '#414868',
                        brightRed: '#f7768e',
                        brightGreen: '#9ece6a',
                        brightYellow: '#e0af68',
                        brightBlue: '#7aa2f7',
                        brightMagenta: '#bb9af7',
                        brightCyan: '#7dcfff',
                        brightWhite: '#c0caf5'
                    },
                    fontFamily: "'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace",
                    fontSize: 14,
                    lineHeight: 1.3,
                    cursorBlink: true,
                    cursorStyle: 'bar',
                    cursorWidth: 2,
                    scrollback: 10000,
                    tabStopWidth: 4,
                    allowProposedApi: true,
                    convertEol: true
                });

                myserverFitAddon = new FitAddon.FitAddon();
                myserverTerm.loadAddon(myserverFitAddon);

                myserverTerm.open(container);

                setTimeout(function() {
                    myserverFitAddon.fit();
                    myserverConnectWs(name);
                }, 150);
            }

            function myserverConnectWs(name) {
                var status = document.getElementById('myserver-terminal-status');
                var token = localStorage.getItem('__ep_tk__');
                var protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
                var wsUrl = protocol + '//' + location.host + '/MyServer/ws/terminal?token=' + encodeURIComponent(token);

                myserverWs = new WebSocket(wsUrl);

                myserverWs.onopen = function() {
                    myserverWs.send(JSON.stringify({
                        server: name,
                        cols: myserverTerm.cols,
                        rows: myserverTerm.rows
                    }));
                };

                myserverWs.onmessage = function(event) {
                    var msg = JSON.parse(event.data);

                    if (msg.type === 'connected') {
                        status.textContent = '已连接';
                        status.style.color = 'var(--ok-c)';
                        myserverTerm.focus();
                    } else if (msg.type === 'output') {
                        myserverTerm.write(msg.data);
                    } else if (msg.type === 'error') {
                        status.textContent = msg.message;
                        status.style.color = 'var(--er-c)';
                    } else if (msg.type === 'ping') {
                        if (myserverWs && myserverWs.readyState === WebSocket.OPEN) {
                            myserverWs.send(JSON.stringify({ type: 'pong' }));
                        }
                    }
                };

                myserverWs.onclose = function() {
                    status.textContent = '已断开';
                    status.style.color = 'var(--er-c)';
                };

                myserverWs.onerror = function() {
                    status.textContent = '连接错误';
                    status.style.color = 'var(--er-c)';
                };

                myserverTerm.onData(function(data) {
                    if (myserverWs && myserverWs.readyState === WebSocket.OPEN) {
                        myserverWs.send(JSON.stringify({ type: 'input', data: data }));
                    }
                });

                myserverTerm.onResize(function(size) {
                    if (myserverWs && myserverWs.readyState === WebSocket.OPEN) {
                        myserverWs.send(JSON.stringify({ type: 'resize', cols: size.cols, rows: size.rows }));
                    }
                });
            }

            function myserverCloseTerminal() {
                if (myserverWs) {
                    myserverWs.close();
                    myserverWs = null;
                }
                if (myserverTerm) {
                    myserverTerm.dispose();
                    myserverTerm = null;
                }
                myserverFitAddon = null;
                myserverCurrentServer = "";
                document.getElementById('myserver-terminal-section').style.display = 'none';
            }

            document.addEventListener('DOMContentLoaded', function() {
                window.addEventListener('resize', function() {
                    if (myserverFitAddon && myserverTerm) {
                        myserverFitAddon.fit();
                    }
                });
            });
        '''
