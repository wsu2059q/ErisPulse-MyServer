from typing import Dict, List


class ServerTemplates:
    PRIMARY_COLOR = "#4a9eff"
    SECONDARY_COLOR = "#666"
    SUCCESS_COLOR = "#52c41a"
    ERROR_COLOR = "#ff4d4f"
    BORDER_COLOR = "rgba(0,0,0,0.06)"

    @classmethod
    def build_help(cls) -> Dict[str, str]:
        return {
            "html": cls._build_help_html(),
            "markdown": cls._build_help_markdown(),
            "text": cls._build_help_text()
        }

    @classmethod
    def build_machine_list(cls, machines: list) -> Dict[str, str]:
        return {
            "html": cls._build_list_html(machines),
            "markdown": cls._build_list_markdown(machines),
            "text": cls._build_list_text(machines)
        }

    @classmethod
    def build_all_machines_detail(cls, machines: list) -> Dict[str, str]:
        return {
            "html": cls._build_all_detail_html(machines),
            "markdown": cls._build_all_detail_markdown(machines),
            "text": cls._build_all_detail_text(machines)
        }

    @classmethod
    def build_machine_detail(cls, machine: dict, status: dict) -> Dict[str, str]:
        return {
            "html": cls._build_detail_html(machine, status),
            "markdown": cls._build_detail_markdown(machine, status),
            "text": cls._build_detail_text(machine, status)
        }

    @classmethod
    def build_exec_result(cls, machine_name: str, cmd: str, result: dict) -> Dict[str, str]:
        return {
            "html": cls._build_exec_html(machine_name, cmd, result),
            "markdown": cls._build_exec_markdown(machine_name, cmd, result),
            "text": cls._build_exec_text(machine_name, cmd, result)
        }

    @classmethod
    def _build_help_html(cls) -> str:
        return (
            f'<div style="padding:12px;">'
            f'<div style="font-weight:bold;font-size:16px;margin-bottom:16px;">MyServer 服务器管理</div>'
            f'<div style="margin-bottom:12px;">'
            f'<div><code>/server</code> 查看服务器列表</div>'
            f'<div><code>/server info</code> 查看所有服务器状态</div>'
            f'<div><code>/server add</code> 添加服务器</div>'
            f'<div><code>/server rm [名称]</code> 删除服务器</div>'
            f'<div><code>/server exec [名称]</code> 进入终端</div>'
            f'</div>'
            f'</div>'
        )

    @classmethod
    def _build_help_markdown(cls) -> str:
        return (
            "**MyServer 服务器管理**\n"
            "\n"
            "`/server` 查看服务器列表\n"
            "`/server info` 查看所有服务器状态\n"
            "`/server add` 添加服务器\n"
            "`/server rm [名称]` 删除服务器\n"
            "`/server exec [名称]` 进入终端"
        )

    @classmethod
    def _build_help_text(cls) -> str:
        return (
            "MyServer 服务器管理\n"
            "\n"
            "/server           查看服务器列表\n"
            "/server info      查看所有服务器状态\n"
            "/server add       添加服务器\n"
            "/server rm [名称]  删除服务器\n"
            "/server exec [名称] 进入终端"
        )

    @classmethod
    def _build_list_html(cls, machines: list) -> str:
        rows = ""
        for i, m in enumerate(machines, 1):
            is_online = m.get("status") or m.get("status") == "online"
            status_html = (
                f'<span style="color:{cls.SUCCESS_COLOR}">[在线]</span>'
                if is_online
                else f'<span style="color:{cls.ERROR_COLOR}">[离线]</span>'
            )
            tags_html = ""
            if m.get("tags"):
                tags = " ".join(
                    f'<code style="font-size:11px;background:rgba(0,0,0,0.04);padding:1px 5px;border-radius:3px;">{t}</code>'
                    for t in m["tags"]
                )
                tags_html = f' {tags}'

            rows += (
                f'<div style="margin-bottom:6px;">'
                f'{i}. {status_html} <b>{m["name"]}</b>{tags_html}'
                f'</div>'
            )

        return (
            f'<div style="padding:12px;">'
            f'<div style="font-weight:bold;font-size:15px;margin-bottom:12px;">服务器列表</div>'
            f'{rows}'
            f'<div style="margin-top:12px;color:{cls.SECONDARY_COLOR};">共 {len(machines)} 台服务器</div>'
            f'</div>'
        )

    @classmethod
    def _build_list_markdown(cls, machines: list) -> str:
        lines = ["**服务器列表**", ""]
        for i, m in enumerate(machines, 1):
            is_online = m.get("status") or m.get("status") == "online"
            status = "[在线]" if is_online else "[离线]"
            tags = ""
            if m.get("tags"):
                tags = " " + " ".join(f"`{t}`" for t in m["tags"])
            lines.append(f"{i}. {status} **{m['name']}**{tags}")
        lines.extend(["", f"共 {len(machines)} 台服务器"])
        return "\n".join(lines)

    @classmethod
    def _build_list_text(cls, machines: list) -> str:
        lines = ["服务器列表", ""]
        for i, m in enumerate(machines, 1):
            is_online = m.get("status") or m.get("status") == "online"
            status = "[在线]" if is_online else "[离线]"
            tags = ""
            if m.get("tags"):
                tags = " [" + ", ".join(m["tags"]) + "]"
            lines.append(f"{i}. {status} {m['name']}{tags}")
        lines.extend(["", f"共 {len(machines)} 台服务器"])
        return "\n".join(lines)

    @classmethod
    def _build_all_detail_html(cls, machines: list) -> str:
        rows = ""
        for m in machines:
            status = m.get("status_data", {})
            is_online = status.get("online", False)
            status_html = (
                f'<span style="color:{cls.SUCCESS_COLOR}">在线</span>'
                if is_online
                else f'<span style="color:{cls.ERROR_COLOR}">离线</span>'
            )

            sysinfo = status.get("sysinfo", {})
            sys_html = ""
            if is_online and sysinfo:
                cpu_info = sysinfo.get("cpu_cores", "未知")
                cpu_model = sysinfo.get("cpu_model", "")
                cpu_display = f"{cpu_info} 核 ({cpu_model})" if cpu_model else f"{cpu_info} 核"

                sys_html = (
                    f'<div style="margin-top:8px;padding:8px;background:rgba(0,0,0,0.02);border-radius:4px;font-size:13px;">'
                    f'<div>CPU: {cpu_display}</div>'
                    f'<div>内存: {sysinfo.get("memory", "未知")} | 磁盘: {sysinfo.get("disk", "未知")}</div>'
                    f'<div>负载: {sysinfo.get("load", "未知")}</div>'
                    f'<div>运行: {sysinfo.get("uptime", "未知")}</div>'
                    f'</div>'
                )

            rows += (
                f'<div style="margin-bottom:12px;padding:12px;border:1px solid {cls.BORDER_COLOR};border-radius:6px;">'
                f'<div style="display:flex;justify-content:space-between;align-items:center;">'
                f'<div><b>{m["name"]}</b></div>'
                f'<div>{status_html}</div>'
                f'</div>'
                f'{sys_html}'
                f'</div>'
            )

        return (
            f'<div style="padding:12px;">'
            f'<div style="font-weight:bold;font-size:15px;margin-bottom:12px;">服务器状态总览</div>'
            f'{rows}'
            f'<div style="margin-top:8px;color:{cls.SECONDARY_COLOR};font-size:12px;">共 {len(machines)} 台服务器</div>'
            f'</div>'
        )

    @classmethod
    def _build_all_detail_markdown(cls, machines: list) -> str:
        lines = ["**服务器状态总览**", ""]

        for m in machines:
            status = m.get("status_data", {})
            is_online = status.get("online", False)
            status_text = "在线" if is_online else "离线"

            lines.append(f"**{m['name']}** - {status_text}")

            sysinfo = status.get("sysinfo", {})
            if is_online and sysinfo:
                cpu_info = sysinfo.get("cpu_cores", "未知")
                cpu_model = sysinfo.get("cpu_model", "")
                cpu_display = f"{cpu_info} 核 ({cpu_model})" if cpu_model else f"{cpu_info} 核"

                lines.append(f"  CPU: {cpu_display} | 内存: {sysinfo.get('memory', '未知')} | 磁盘: {sysinfo.get('disk', '未知')}")
                lines.append(f"  负载: {sysinfo.get('load', '未知')} | 运行: {sysinfo.get('uptime', '未知')}")

            lines.append("")

        lines.append(f"共 {len(machines)} 台服务器")
        return "\n".join(lines)

    @classmethod
    def _build_all_detail_text(cls, machines: list) -> str:
        lines = ["服务器状态总览", ""]

        for m in machines:
            status = m.get("status_data", {})
            is_online = status.get("online", False)
            status_text = "在线" if is_online else "离线"

            lines.append(f"{m['name']} - {status_text}")

            sysinfo = status.get("sysinfo", {})
            if is_online and sysinfo:
                cpu_info = sysinfo.get("cpu_cores", "未知")
                cpu_model = sysinfo.get("cpu_model", "")
                cpu_display = f"{cpu_info} 核 ({cpu_model})" if cpu_model else f"{cpu_info} 核"

                lines.append(f"  CPU: {cpu_display}")
                lines.append(f"  内存: {sysinfo.get('memory', '未知')}")
                lines.append(f"  磁盘: {sysinfo.get('disk', '未知')}")
                lines.append(f"  负载: {sysinfo.get('load', '未知')}")
                lines.append(f"  运行: {sysinfo.get('uptime', '未知')}")

            lines.append("")

        lines.append(f"共 {len(machines)} 台服务器")
        return "\n".join(lines)

    @classmethod
    def _build_detail_html(cls, machine: dict, status: dict) -> str:
        is_online = status.get("online", False)
        status_text = (
            f'<span style="color:{cls.SUCCESS_COLOR}">在线</span>'
            if is_online
            else f'<span style="color:{cls.ERROR_COLOR}">离线</span>'
        )

        sysinfo = status.get("sysinfo", {})
        sys_rows = ""
        if is_online and sysinfo:
            cpu_info = sysinfo.get("cpu_cores", "未知")
            cpu_model = sysinfo.get("cpu_model", "")
            if cpu_model:
                cpu_display = f"{cpu_info} 核 ({cpu_model})"
            else:
                cpu_display = f"{cpu_info} 核"

            sys_rows = (
                f'<hr style="margin:12px 0;border:none;border-top:1px solid {cls.BORDER_COLOR};">'
                f'<div style="font-weight:bold;margin-bottom:8px;">系统信息</div>'
                f'<div style="padding:8px;background:rgba(0,0,0,0.02);border-radius:4px;">'
                f'<div>系统: {sysinfo.get("os", "未知")}</div>'
                f'<div>内核: {sysinfo.get("kernel", "未知")}</div>'
                f'<div>运行时间: {sysinfo.get("uptime", "未知")}</div>'
                f'<div>CPU: {cpu_display}</div>'
                f'<div>内存: {sysinfo.get("memory", "未知")}</div>'
                f'<div>磁盘: {sysinfo.get("disk", "未知")}</div>'
                f'<div>负载: {sysinfo.get("load", "未知")}</div>'
                f'</div>'
            )

        tags_html = ""
        if machine.get("tags"):
            tags = " ".join(
                f'<code style="font-size:11px;background:rgba(0,0,0,0.04);padding:1px 5px;border-radius:3px;">{t}</code>'
                for t in machine["tags"]
            )
            tags_html = f'<div style="margin-top:8px;">标签: {tags}</div>'

        notes_html = ""
        if machine.get("notes"):
            notes_html = f'<div style="margin-top:8px;color:{cls.SECONDARY_COLOR};">备注: {machine["notes"]}</div>'

        return (
            f'<div style="padding:12px;">'
            f'<div style="font-weight:bold;font-size:15px;margin-bottom:12px;">{machine["name"]}</div>'
            f'<div><b>地址:</b> {machine["ip"]}:{machine["port"]}</div>'
            f'<div><b>用户:</b> {machine["username"]}</div>'
            f'<div><b>状态:</b> {status_text}</div>'
            f'{sys_rows}'
            f'{tags_html}'
            f'{notes_html}'
            f'</div>'
        )

    @classmethod
    def _build_detail_markdown(cls, machine: dict, status: dict) -> str:
        is_online = status.get("online", False)
        status_text = "**在线**" if is_online else "**离线**"

        lines = [
            f"**{machine['name']}**",
            "",
            f"地址: {machine['ip']}:{machine['port']}",
            f"用户: {machine['username']}",
            f"状态: {status_text}",
        ]

        sysinfo = status.get("sysinfo", {})
        if is_online and sysinfo:
            cpu_info = sysinfo.get("cpu_cores", "未知")
            cpu_model = sysinfo.get("cpu_model", "")
            if cpu_model:
                cpu_display = f"{cpu_info} 核 ({cpu_model})"
            else:
                cpu_display = f"{cpu_info} 核"

            lines.extend([
                "",
                "**系统信息**",
                f"系统: {sysinfo.get('os', '未知')}",
                f"内核: {sysinfo.get('kernel', '未知')}",
                f"运行时间: {sysinfo.get('uptime', '未知')}",
                f"CPU: {cpu_display}",
                f"内存: {sysinfo.get('memory', '未知')}",
                f"磁盘: {sysinfo.get('disk', '未知')}",
                f"负载: {sysinfo.get('load', '未知')}",
            ])

        if machine.get("tags"):
            lines.extend(["", f"标签: {' | '.join(machine['tags'])}"])

        if machine.get("notes"):
            lines.extend(["", f"> {machine['notes']}"])

        return "\n".join(lines)

    @classmethod
    def _build_detail_text(cls, machine: dict, status: dict) -> str:
        is_online = status.get("online", False)
        status_text = "在线" if is_online else "离线"

        lines = [
            f"{machine['name']}",
            "",
            f"地址: {machine['ip']}:{machine['port']}",
            f"用户: {machine['username']}",
            f"状态: {status_text}",
        ]

        sysinfo = status.get("sysinfo", {})
        if is_online and sysinfo:
            cpu_info = sysinfo.get("cpu_cores", "未知")
            cpu_model = sysinfo.get("cpu_model", "")
            if cpu_model:
                cpu_display = f"{cpu_info} 核 ({cpu_model})"
            else:
                cpu_display = f"{cpu_info} 核"

            lines.extend([
                "",
                "系统信息:",
                f"  系统: {sysinfo.get('os', '未知')}",
                f"  内核: {sysinfo.get('kernel', '未知')}",
                f"  运行时间: {sysinfo.get('uptime', '未知')}",
                f"  CPU: {cpu_display}",
                f"  内存: {sysinfo.get('memory', '未知')}",
                f"  磁盘: {sysinfo.get('disk', '未知')}",
                f"  负载: {sysinfo.get('load', '未知')}",
            ])

        if machine.get("tags"):
            lines.extend(["", f"标签: {', '.join(machine['tags'])}"])

        if machine.get("notes"):
            lines.extend(["", machine["notes"]])

        return "\n".join(lines)

    @classmethod
    def _build_exec_html(cls, machine_name: str, cmd: str, result: dict) -> str:
        exit_code = result.get("exit_code", -1)
        stdout = result.get("stdout", "").rstrip()
        stderr = result.get("stderr", "").rstrip()

        exit_color = cls.SUCCESS_COLOR if exit_code == 0 else cls.ERROR_COLOR

        output_html = ""
        if stdout:
            escaped = stdout.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            output_html = (
                f'<div style="padding:8px;background:rgba(0,0,0,0.03);'
                f'border-radius:4px;font-family:monospace;white-space:pre-wrap;word-break:break-all;">'
                f'{escaped}</div>'
            )

        stderr_html = ""
        if stderr:
            escaped = stderr.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            stderr_html = (
                f'<div style="margin-top:4px;color:{cls.ERROR_COLOR};padding:8px;'
                f'background:rgba(255,77,79,0.05);border-radius:4px;font-family:monospace;'
                f'white-space:pre-wrap;word-break:break-all;">'
                f'{escaped}</div>'
            )

        if not stdout and not stderr:
            output_html = (
                f'<div style="padding:8px;color:{cls.SECONDARY_COLOR};font-style:italic;">'
                f'(无输出)</div>'
            )

        exit_html = ""
        if exit_code != 0:
            exit_html = f'<div style="font-size:12px;color:{exit_color};margin-top:4px;">exit {exit_code}</div>'

        return (
            f'<div style="padding:8px 0;">'
            f'<div style="font-weight:bold;color:{cls.PRIMARY_COLOR};font-family:monospace;">$ {cmd}</div>'
            f'{output_html}'
            f'{stderr_html}'
            f'{exit_html}'
            f'</div>'
        )

    @classmethod
    def _build_exec_markdown(cls, machine_name: str, cmd: str, result: dict) -> str:
        exit_code = result.get("exit_code", -1)
        stdout = result.get("stdout", "").rstrip()
        stderr = result.get("stderr", "").rstrip()

        lines = [f"$ {cmd}"]

        if stdout:
            lines.extend(["", stdout])

        if stderr:
            lines.extend(["", f"[stderr]", stderr])

        if not stdout and not stderr:
            lines.append("(无输出)")

        if exit_code != 0:
            lines.append(f"exit {exit_code}")

        return "\n".join(lines)

    @classmethod
    def _build_exec_text(cls, machine_name: str, cmd: str, result: dict) -> str:
        exit_code = result.get("exit_code", -1)
        stdout = result.get("stdout", "").rstrip()
        stderr = result.get("stderr", "").rstrip()

        lines = [f"$ {cmd}", ""]

        if stdout:
            lines.append(stdout)

        if stderr:
            lines.extend(["[stderr]", stderr])

        if not stdout and not stderr:
            lines.append("(无输出)")

        if exit_code != 0:
            lines.append(f"exit {exit_code}")

        return "\n".join(lines)
