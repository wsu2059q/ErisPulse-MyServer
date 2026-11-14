"""通用工具：打码、时长/体积格式化、输出截断、名字净化。"""

from __future__ import annotations

import re


def mask_ip(ip: str) -> str:
    """
    IP 打码。

    :param ip: [str] IP 或 host:port 文本
    :return: [str] 打码后的文本
    """
    ip = str(ip or "")
    if not ip:
        return "****"
    parts = ip.split(".")
    if len(parts) == 4:
        return ".".join(parts[:2]) + ".****"
    if ip.startswith("[") and "]" in ip:
        return "[****]"
    if ":" in ip and not ip.startswith("["):
        try:
            host, port = ip.rsplit(":", 1)
            return mask_ip(host) + f":{port}"
        except ValueError:
            pass
    if len(ip) > 8:
        return ip[:8] + "****"
    return "****"


def format_duration(seconds: float) -> str:
    """
    秒数转人类可读时长。

    :param seconds: [float] 秒数
    :return: [str] 形如 3d12h / 2h30m / 5m30s / 40s
    """
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60}s"
    if seconds < 86400:
        return f"{seconds // 3600}h{seconds % 3600 // 60}m"
    return f"{seconds // 86400}d{seconds % 86400 // 3600}h"


def format_size(num_bytes: float) -> str:
    """
    字节数转人类可读体积。

    :param num_bytes: [float] 字节数
    :return: [str] 形如 1.5GB / 320MB / 12KB
    """
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num_bytes) < 1024 or unit == "TB":
            return f"{num_bytes:.1f}{unit}" if unit != "B" else f"{int(num_bytes)}B"
        num_bytes /= 1024
    return f"{num_bytes:.1f}TB"


def truncate_output(text: str, max_lines: int = 50, max_chars: int = 4000) -> str:
    """
    输出截断，保留尾部。

    :param text: [str] 原始输出
    :param max_lines: [int] 行数上限 (默认: 50)
    :param max_chars: [int] 字符数上限 (默认: 4000)
    :return: [str] 截断后的文本
    """
    if not text:
        return ""
    lines = text.splitlines()
    truncated = False
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
        truncated = True
    result = "\n".join(lines)
    if len(result) > max_chars:
        result = result[-max_chars:]
        truncated = True
    if truncated:
        result = "... (输出已截断，仅显示尾部)\n" + result
    return result


def safe_session_name(name: str) -> str:
    """
    会话名净化，供 tmux 会话名使用。

    :param name: [str] 原始名字
    :return: [str] 只含字母数字下划线连字符的名字，最长 48 字符
    """
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", str(name or "").strip())
    return cleaned[:48] or "default"


def is_valid_cron_expr(expr: str) -> bool:
    """
    校验五段式 cron 表达式。

    :param expr: [str] cron 表达式
    :return: [bool] 是否为五段
    """
    return len(str(expr or "").strip().split()) == 5
