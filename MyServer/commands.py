"""聊天命令菜单：/server 入口与 server.* 子命令（纯 ErisPulse 用户入口）。

交互终端会话走 event.conversation 驱动：消息 → send-keys → capture 回显；
``` 围栏进入脚本模式；exit 脱离（tmux 会话远端保活）。
"""

from __future__ import annotations

from ErisPulse.Core.Event import command

from . import texts
from .ops import output_view
from .utils import truncate_output


def register_commands(main) -> None:
    """注册全部命令（on_load 调用）。"""
    menu = Menu(main)

    @command("server", help="服务器管理")
    async def server_handler(event):
        await menu.show_menu(event)

    @command("server.list", help="机器列表", hidden=True)
    async def server_list(event):
        await menu.show_list(event)

    @command("server.status", help="机器状态", hidden=True)
    async def server_status(event):
        await menu.show_status(event)

    @command("server.add", help="添加机器", hidden=True)
    async def server_add(event):
        await menu.show_add(event)

    @command("server.exec", help="终端会话", hidden=True)
    async def server_exec(event):
        await menu.show_exec(event)

    @command("server.alerts", help="最近告警", hidden=True)
    async def server_alerts(event):
        await menu.show_alerts(event)

    @command("server.confirm", help="确认危险命令", hidden=True)
    async def server_confirm(event):
        await menu.show_confirm(event)


class Menu:
    """命令实现集（依赖宿主 Main）。"""

    def __init__(self, main):
        self.main = main

    # ---- 展示类 ----

    async def show_menu(self, event) -> None:
        """主菜单。"""
        stats = self.main.fleet.stats()
        await event.reply(texts.t("menu_title", fleet=texts.t(
            "menu_fleet_line", total=stats["total"],
            online=stats["online"], offline=stats["offline"])))

    async def show_list(self, event) -> None:
        """机器列表。"""
        machines = self.main.fleet.all()
        if not machines:
            await event.reply(texts.t("machine_empty"))
            return
        lines = []
        for m in machines:
            dot = "🟢" if m.get("online") else "🔴"
            lines.append(f"{dot} {m['name']}（{m.get('username', '')}@{m.get('ip', '')}）")
        await event.reply("\n".join(lines))

    async def show_status(self, event) -> None:
        """单机实时状态。"""
        name = self._arg(event)
        result = await self.main.ops.status(name)
        if not result.get("ok"):
            await event.reply(result.get("error", "unknown error"))
            return
        if not result.get("online"):
            await event.reply(f"🔴 {name}：{result.get('error', 'offline')}")
            return
        await event.reply(f"🟢 {name}\n{result.get('summary', '')}")

    async def show_alerts(self, event) -> None:
        """最近告警。"""
        alerts = self.main.monitor.recent_alerts(10)
        if not alerts:
            await event.reply(texts.t("cmd_done"))
            return
        lines = [f"[{a.get('alert_type', '')}] {a.get('message', '')}" for a in alerts]
        await event.reply(truncate_output("\n".join(lines), max_lines=15))

    async def show_confirm(self, event) -> None:
        """确认危险命令：server confirm <machine> <token>。"""
        parts = self._arg(event).split()
        if len(parts) < 2:
            await event.reply("用法：server confirm <机器名> <令牌>")
            return
        machine_name, token = parts[0], parts[1]
        command = self.main.ops.confirm(machine_name, token, actor=self._actor(event))
        if command is None:
            await event.reply(texts.t("danger_token_expired"))
            return
        await event.reply(texts.t("danger_confirmed"))
        result = await self.main.ops.exec(machine_name, command,
                                          actor=self._actor(event) + ":confirmed",
                                          confirmed=True)
        await event.reply(output_view(result, machine_name, command))

    # ---- 添加机器 ----

    async def show_add(self, event) -> None:
        """交互式添加机器：name / host / port / user / auth。"""
        if not self.main.is_admin(self._actor(event)):
            await event.reply(texts.t("needs_admin"))
            return
        conv = event.conversation(timeout=300)
        steps = [
            ("name", "机器名（唯一标识，如 web-1）："),
            ("ip", "主机地址："),
            ("port", "SSH 端口（回车 = 22）："),
            ("username", "用户名（回车 = root）："),
            ("auth_type", "认证方式 password / key（回车 = password）："),
        ]
        answers: dict = {}
        for key, prompt in steps:
            await conv.say(prompt)
            reply = await conv.wait()
            if reply is None:
                return
            text = reply.get_text().strip()
            if key == "port" and not text:
                text = "22"
            if key == "username" and not text:
                text = "root"
            if key == "auth_type" and not text:
                text = "password"
            answers[key] = text
        auth_type = answers["auth_type"].lower()
        if auth_type == "key":
            await conv.say("私钥路径（服务器上）或直接粘贴私钥内容，输入单独一行 END 结束：")
            chunks = []
            while True:
                reply = await conv.wait()
                if reply is None:
                    return
                text = reply.get_text()
                if text.strip() == "END":
                    break
                chunks.append(text)
            if not chunks:
                return
            secret = "\n".join(chunks)
            machine = {**answers, "auth_type": "key",
                       "private_key": secret if "\n" in secret or " KEY" in secret else "",
                       "key_path": "" if "\n" in secret or " KEY" in secret else secret}
        else:
            await conv.say("密码：")
            reply = await conv.wait()
            if reply is None:
                return
            machine = {**answers, "auth_type": "password", "password": reply.get_text().strip()}
        conv.close()

        if self.main.fleet.get(machine["name"]) is not None:
            await event.reply(texts.t("machine_name_taken", name=machine["name"]))
            return
        self.main.fleet.save(machine)
        ok, error = await self.main.test_connection(machine)
        await event.reply(texts.t("machine_added", name=machine["name"],
                                  host=f"{machine['username']}@{machine['ip']}",
                                  result=texts.t("machine_test_ok") if ok
                                  else texts.t("machine_test_fail", error=error)))
        if not ok:
            self.main.fleet.delete(machine["name"])

    # ---- 交互终端 ----

    async def show_exec(self, event) -> None:
        """进入交互终端会话：选机器 → 挂 tmux 会话。"""
        if not self.main.is_admin(self._actor(event)):
            await event.reply(texts.t("needs_admin"))
            return
        names = self.main.fleet.names()
        if not names:
            await event.reply(texts.t("machine_empty"))
            return
        arg = self._arg(event)
        if arg in names:
            machine_name = arg
        else:
            await event.reply("选择机器（回复名字）：" + "、".join(names))
            conv = event.conversation(timeout=60)
            reply = await conv.wait()
            conv.close()
            if reply is None:
                return
            machine_name = reply.get_text().strip()
        machine = self.main.fleet.get(machine_name)
        if machine is None:
            await event.reply(texts.t("machine_not_found", name=machine_name,
                                      names=", ".join(names)))
            return
        await self._terminal(event, machine_name, machine)

    async def _terminal(self, event, machine_name: str, machine: dict) -> None:
        """{!--< internal-use >!--} 会话主循环：消息 → send-keys → capture 回显。"""
        from .sessions import INSTALL_TMUX_CMD

        session_name = f"chat_{self._actor(event).rsplit(':', 1)[-1][:12]}"
        client = self.main.make_client(machine)
        conv = event.conversation(timeout=1800)
        try:
            await client.connect()
            probe = await client.exec_command("command -v tmux", timeout=5)
            if probe.get("exit_code") != 0:
                await conv.say(texts.t("tmux_missing_ask"))
                reply = await conv.wait()
                if reply is None:
                    await client.close()
                    return
                answer = reply.get_text().strip().lower()
                if answer in ("", "y", "yes", "是"):
                    await conv.say(texts.t("tmux_installing"))
                    install = await client.exec_command(INSTALL_TMUX_CMD, timeout=300)
                    if install.get("exit_code") == 0:
                        await conv.say(texts.t("tmux_install_ok"))
                    else:
                        from .utils import truncate_output

                        detail = install.get("stderr") or install.get("stdout") or ""
                        await conv.say(texts.t("tmux_install_failed",
                                               error=truncate_output(detail)))
            session = await self.main.sessions.open(machine_name, session_name, client)
        except Exception as e:
            await client.close()
            await event.reply(texts.t("exec_failed", machine=machine_name, error=str(e)))
            return
        mode_text = texts.t("session_mode_tmux" if session.mode == "tmux" else "session_mode_local")
        await conv.say(texts.t("session_opened", session=session_name, mode=mode_text))
        screen = await session.capture(30)
        if screen.strip():
            await conv.say(truncate_output(screen))
        script_mode = False
        script_lines: list[str] = []
        try:
            while conv.is_active:
                reply = await conv.wait()
                if reply is None:
                    break
                text = reply.get_text().strip()
                if not text:
                    continue
                if script_mode:
                    if text == "```":
                        script_mode = False
                        if script_lines:
                            await self._run_script(conv, session, "\n".join(script_lines))
                        else:
                            await conv.say("空脚本，已取消")
                        script_lines = []
                    else:
                        script_lines.append(reply.get_text())
                    continue
                if text == "```":
                    script_mode = True
                    script_lines = []
                    await conv.say("脚本模式：输入内容，``` 结束并发送")
                    continue
                if text in ("exit", "quit", "退出", "detach"):
                    break
                if text in ("screen", "刷屏", "capture"):
                    await conv.say(truncate_output(await session.capture(30)))
                    continue
                verdict = self.main.grade(text)
                if verdict["level"] == "confirm":
                    await conv.say(texts.t("danger_confirm_required",
                                           reason=verdict["reason"], command=text,
                                           token="(聊天会话内不支持确认，改用 server confirm 或 Dashboard）"))
                    continue
                await session.write(text)
                import asyncio

                await asyncio.sleep(0.6)
                await conv.say(truncate_output(await session.capture(40)))
        finally:
            conv.close()
            # 只脱离，不杀 tmux：本端 SSH 连接关闭，远端会话继续跑
            await client.close()
            await event.reply(texts.t("session_closed", session=session_name))

    async def _run_script(self, conv, session, script: str) -> None:
        """{!--< internal-use >!--} 围栏脚本：base64 过墙执行，绕开转义问题。"""
        import base64

        encoded = base64.b64encode(script.encode()).decode()
        await session.write(f"echo {encoded} | base64 -d | bash")
        import asyncio

        await asyncio.sleep(1.0)
        await conv.say(truncate_output(await session.capture(40)))

    # ---- 工具 ----

    def _arg(self, event) -> str:
        """{!--< internal-use >!--} 命令参数文本。"""
        text = str(event.get_alt_message() or "").strip()
        # 去掉命令前缀本身（"server.status web-1" → "web-1"）
        for token in text.split(maxsplit=1)[1:]:
            return token.strip()
        return ""

    def _actor(self, event) -> str:
        """{!--< internal-use >!--} 操作者标识。"""
        try:
            return f"chat:{event.get_platform()}:{event.get_user_id()}"
        except Exception:
            return "chat:unknown"

    def grade(self, command: str) -> dict:
        """{!--< internal-use >!--} 危险分级代理。"""
        from .safety import grade

        return grade(command)
