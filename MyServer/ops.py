"""核心操作编排：exec / 确认 / 会话 / 状态。

聊天命令、Dashboard API、AI 工具三端共用；危险分级与审计在此统一收口。
"""

from __future__ import annotations

from . import safety, texts
from .sessions import SessionManager
from .utils import truncate_output


class ServerOps:
    """服务器操作编排层。"""

    def __init__(self, main):
        self.main = main

    async def exec(self, machine_name: str, command: str, actor: str = "",
                   timeout: int | None = None, confirmed: bool = False) -> dict:
        """
        执行命令：confirm 级拦截返回确认令牌；warn 级放行附警告。

        :param machine_name: [str] 机器名
        :param command: [str] 命令文本
        :param actor: [str] 操作者标识（审计用）
        :param timeout: [int | None] 超时秒数，None 用配置默认
        :param confirmed: [bool] 已持有效确认令牌放行的命令，跳过二次拦截
        :return: [dict] {"ok", "stdout", "stderr", "exit_code", "level", "reason",
                 "needs_confirm", "token"(仅拦截时), "warning"(仅 warn 时)}
        """
        machine = self.main.fleet.get(str(machine_name or ""))
        if machine is None:
            return {"ok": False, "error": texts.t("machine_not_found",
                                                  name=machine_name, names=", ".join(self.main.fleet.names()))}
        command = str(command or "").strip()
        if not command:
            return {"ok": False, "error": "empty command"}
        timeout = int(timeout or self.main.cfg.exec_timeout)

        verdict = safety.grade(command)
        if verdict["level"] == "confirm" and not confirmed:
            token = self.main.gate.issue(machine_name, command)
            self.main.audit.record(machine_name, actor, "exec_blocked", command, "confirm")
            return {
                "ok": False, "needs_confirm": True, "token": token["token"],
                "level": "confirm", "reason": verdict["reason"],
                "message": texts.t("danger_confirm_required", reason=verdict["reason"],
                                   command=command, token=token["token"]),
            }

        client = self.main.make_client(machine)
        try:
            await client.connect()
            result = await client.exec_command(command, timeout=timeout)
        except ConnectionError as e:
            return {"ok": False, "level": verdict["level"], "error": str(e)}
        finally:
            await client.close()

        self.main.audit.record(machine_name, actor, "exec", command, verdict["level"])
        result.update({
            "ok": result.get("exit_code") == 0,
            "level": verdict["level"],
            "reason": verdict["reason"],
        })
        if verdict["level"] == "warn":
            result["warning"] = texts.t("danger_warn", reason=verdict["reason"])
        if result.get("timed_out"):
            result["stderr"] = texts.t("exec_timeout", timeout=timeout)
        return result

    def confirm(self, machine_name: str, token: str, actor: str = "") -> str | None:
        """
        消费确认令牌，返回放行的命令；无效令牌返回 None。

        :param machine_name: [str] 机器名
        :param token: [str] 确认令牌
        :param actor: [str] 操作者标识
        :return: [str | None] 命令文本
        """
        return self.main.gate.consume(str(machine_name or ""), str(token or ""))

    async def status(self, machine_name: str) -> dict:
        """
        实时状态：现场采集一次，失败回退最近缓存。

        :param machine_name: [str] 机器名
        :return: [dict] {"ok", "online", "metrics", "summary", "error"}
        """
        machine = self.main.fleet.get(str(machine_name or ""))
        if machine is None:
            return {"ok": False, "error": texts.t("machine_not_found",
                                                  name=machine_name, names=", ".join(self.main.fleet.names()))}
        client = self.main.make_client(machine)
        try:
            await client.connect()
            metrics = await client.collect_metrics()
            await client.close()
            self.main.fleet.save_status(machine_name, {"online": True, "metrics": metrics})
            return {"ok": True, "online": True, "metrics": metrics,
                    "summary": _summary(metrics)}
        except Exception as e:
            cached = self.main.fleet.status(machine_name)
            return {"ok": True, "online": False, "metrics": cached.get("metrics", {}),
                    "summary": "", "error": str(e)}

    def sessions(self) -> SessionManager:
        """
        会话管理器。

        :return: [SessionManager] 进程内会话集合
        """
        return self.main.sessions


def _summary(metrics: dict) -> str:
    """{!--< internal-use >!--} 指标摘要。"""
    from .ssh import summary_line

    return summary_line(metrics)


def output_view(result: dict, machine: str, command: str) -> str:
    """
    执行结果转聊天可读文本。

    :param result: [dict] exec 返回
    :param machine: [str] 机器名
    :param command: [str] 命令文本
    :return: [str] 截断后的输出文本
    """
    if result.get("needs_confirm"):
        return result.get("message", "")
    if not result.get("ok") and result.get("error"):
        return texts.t("exec_failed", machine=machine, error=result["error"])
    output = truncate_output(result.get("stdout") or result.get("stderr") or "(无输出)")
    body = texts.t("exec_done", machine=machine, command=command, output=output)
    warning = result.get("warning")
    if warning:
        body = f"{warning}\n{body}"
    return body
