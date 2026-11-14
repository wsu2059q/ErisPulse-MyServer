"""MyServer 双语文案（zh-CN / en）。"""

from __future__ import annotations

DOMAIN = "MyServer"

STRINGS: dict[str, dict[str, str]] = {
    # ---- 生命周期 ----
    "loaded": {
        "zh-CN": "MyServer 2.0 已加载：{machines} 台机器，监控间隔 {interval} 秒",
        "en": "MyServer 2.0 loaded: {machines} machine(s), monitor interval {interval}s",
    },
    "dashboard_registered": {
        "zh-CN": "Dashboard 控制台已注册（/MyServer/app）",
        "en": "Dashboard console registered (/MyServer/app)",
    },
    "dashboard_unavailable": {
        "zh-CN": "ErisPulse-Dashboard 不在位，控制台跳过（聊天命令与 AI 工具不受影响）",
        "en": "ErisPulse-Dashboard absent; console skipped (chat commands and AI tools unaffected)",
    },
    "cron_registered": {
        "zh-CN": "监控定时任务已注册：每 {interval} 秒采集一轮",
        "en": "Monitor task registered: every {interval}s",
    },
    "cron_existing": {
        "zh-CN": "已有监控定时任务，跳过重复注册",
        "en": "Existing monitor task found; registration skipped",
    },
    # ---- 机器管理 ----
    "machine_added": {
        "zh-CN": "已添加机器 {name}（{host}），连接测试{result}",
        "en": "Machine {name} ({host}) added; connection test {result}",
    },
    "machine_test_ok": {
        "zh-CN": "通过",
        "en": "passed",
    },
    "machine_test_fail": {
        "zh-CN": "失败：{error}",
        "en": "failed: {error}",
    },
    "machine_removed": {
        "zh-CN": "已删除机器 {name}",
        "en": "Machine {name} removed",
    },
    "machine_not_found": {
        "zh-CN": "机器 {name} 不存在。可用：{names}",
        "en": "Machine {name} not found. Available: {names}",
    },
    "machine_empty": {
        "zh-CN": "还没有机器。用 server.add 或 Dashboard 添加。",
        "en": "No machines yet. Add one via server.add or the dashboard.",
    },
    "machine_name_taken": {
        "zh-CN": "机器名 {name} 已存在",
        "en": "Machine name {name} already exists",
    },
    # ---- 执行 ----
    "exec_done": {
        "zh-CN": "[{machine}] $ {command}\n{output}",
        "en": "[{machine}] $ {command}\n{output}",
    },
    "exec_failed": {
        "zh-CN": "[{machine}] 执行失败：{error}",
        "en": "[{machine}] exec failed: {error}",
    },
    "exec_timeout": {
        "zh-CN": "命令超时（{timeout} 秒），进程已终止",
        "en": "Command timed out after {timeout}s; process terminated",
    },
    # ---- 危险命令 ----
    "danger_confirm_required": {
        "zh-CN": "⚠️ 危险命令（{reason}），已拦截等待确认。\n命令：{command}\n120 秒内回复 server confirm {token} 执行，忽略即放弃。",
        "en": "⚠️ Dangerous command ({reason}); held for confirmation.\nCommand: {command}\nReply `server confirm {token}` within 120s to run, or ignore to abort.",
    },
    "danger_token_expired": {
        "zh-CN": "确认令牌无效或已过期（令牌单次有效，120 秒过期）",
        "en": "Confirm token invalid or expired (single-use, 120s TTL)",
    },
    "danger_confirmed": {
        "zh-CN": "已确认，执行中……",
        "en": "Confirmed; running…",
    },
    "danger_warn": {
        "zh-CN": "⚠️ 注意：{reason}",
        "en": "⚠️ Caution: {reason}",
    },
    # ---- 会话 ----
    "session_opened": {
        "zh-CN": "会话 {session} 已开启（{mode}）：后续消息直接发进去，exit 脱离（远端进程不中断）",
        "en": "Session {session} opened ({mode}); subsequent messages go straight in, `exit` detaches (remote process keeps running)",
    },
    "session_mode_tmux": {
        "zh-CN": "tmux 托管，重启/断线不丢",
        "en": "tmux-backed, survives restarts and disconnects",
    },
    "session_mode_local": {
        "zh-CN": "本机 PTY（远端无 tmux，进程随会话结束终止）",
        "en": "local PTY (no tmux on remote; process dies with session)",
    },
    "session_closed": {
        "zh-CN": "已脱离 {session}（tmux 会话仍在远端运行，session attach 可回来）",
        "en": "Detached from {session} (tmux session still running remotely; `session attach` to return)",
    },
    "session_not_found": {
        "zh-CN": "会话 {session} 不存在",
        "en": "Session {session} not found",
    },
    "session_limit": {
        "zh-CN": "会话数已达上限 {limit}，先关闭一些",
        "en": "Session limit {limit} reached; close some first",
    },
    "tmux_missing_ask": {
        "zh-CN": "这台机器没装 tmux（会话托管依赖它，断线不丢现场）。直接回车安装（默认），回复 n 跳过（本次会话不持久）：",
        "en": "tmux is not installed on this machine (session hosting depends on it). Press Enter to install (default), or reply n to skip (this session won't persist):",
    },
    "tmux_installing": {
        "zh-CN": "正在安装 tmux（约 1-2 分钟）……",
        "en": "Installing tmux (1-2 minutes)…",
    },
    "tmux_install_ok": {
        "zh-CN": "tmux 安装完成，会话已托管。",
        "en": "tmux installed; session is now hosted.",
    },
    "tmux_install_failed": {
        "zh-CN": "tmux 安装失败，本次会话不持久。\n{error}",
        "en": "tmux install failed; this session won't persist.\n{error}",
    },
    "tmux_unavailable": {
        "zh-CN": "[tmux 不可用：本会话不持久]",
        "en": "[tmux unavailable: this session won't persist]",
    },
    # ---- 权限 ----
    "needs_admin": {
        "zh-CN": "该操作仅管理员可用",
        "en": "Admin only",
    },
    # ---- 监控告警 ----
    "alert_offline": {
        "zh-CN": "🔴 服务器 {name} 离线",
        "en": "🔴 Server {name} offline",
    },
    "alert_online": {
        "zh-CN": "🟢 服务器 {name} 恢复在线（{summary}）",
        "en": "🟢 Server {name} back online ({summary})",
    },
    "alert_threshold": {
        "zh-CN": "📈 {name} {metric} {value}，超过阈值 {threshold}",
        "en": "📈 {name} {metric} at {value}, over threshold {threshold}",
    },
    "alert_recovered": {
        "zh-CN": "📉 {name} {metric} 回落到 {value}",
        "en": "📉 {name} {metric} recovered to {value}",
    },
    "alert_scheduled_fail": {
        "zh-CN": "⏰ {name} 定时命令失败：{command}\n{error}",
        "en": "⏰ {name} scheduled command failed: {command}\n{error}",
    },
    "alert_expiry_soon": {
        "zh-CN": "📅 服务器 {name} 将在 {days} 天后到期（{date}），记得续费或迁移。",
        "en": "📅 Server {name} expires in {days} day(s) ({date}); renew or migrate soon.",
    },
    "alert_expiry_today": {
        "zh-CN": "📅 服务器 {name} 今天到期（{date}）！",
        "en": "📅 Server {name} expires TODAY ({date})!",
    },
    "alert_expiry_overdue": {
        "zh-CN": "📅 服务器 {name} 已过期 {days} 天（{date}），数据可能随时丢失。",
        "en": "📅 Server {name} expired {days} day(s) ago ({date}); data may be lost at any time.",
    },
    # ---- 上传下载 ----
    "upload_done": {
        "zh-CN": "已上传 {local} → {machine}:{remote}（{size}）",
        "en": "Uploaded {local} → {machine}:{remote} ({size})",
    },
    "download_done": {
        "zh-CN": "已下载 {machine}:{remote} → {local}（{size}）",
        "en": "Downloaded {machine}:{remote} → {local} ({size})",
    },
    "transfer_too_large": {
        "zh-CN": "文件超过上限 {limit} MB",
        "en": "File exceeds the {limit} MB limit",
    },
    # ---- 命令菜单 ----
    "menu_title": {
        "zh-CN": "🖥 MyServer 机房\n{fleet}\n\nserver.list — 机器列表\nserver.status <名> — 实时状态\nserver.exec <名> — 进入终端会话\nserver.add — 添加机器\nserver.alerts — 最近告警\n\n提示：装了 QvQChat 时，直接用自然语言让 AI 查状态、跑命令。",
        "en": "🖥 MyServer fleet\n{fleet}\n\nserver.list — machine list\nserver.status <name> — live status\nserver.exec <name> — terminal session\nserver.add — add a machine\nserver.alerts — recent alerts\n\nTip: with QvQChat installed, just ask the AI in plain language.",
    },
    "menu_fleet_line": {
        "zh-CN": "机器 {total} 台 · 在线 {online} · 离线 {offline}",
        "en": "{total} machine(s) · {online} online · {offline} offline",
    },
    "cmd_done": {
        "zh-CN": "完成。",
        "en": "Done.",
    },
}


DEFAULT_LANG = "zh-CN"
_lang = DEFAULT_LANG


def set_language(lang: str) -> None:
    """设置默认语言（zh-CN / en）。"""
    global _lang
    if lang in (DEFAULT_LANG, "en"):
        _lang = lang


def _by_lang() -> dict[str, dict[str, str]]:
    langs: dict[str, dict[str, str]] = {}
    for key, translations in STRINGS.items():
        for lang, text in translations.items():
            langs.setdefault(lang, {})[key] = text
    return langs


def register_texts() -> None:
    """把文案注册进 ErisPulse i18n（框架可用时）；失败静默（本地表兜底）。"""
    try:
        from ErisPulse.Core import i18n

        for lang, table in _by_lang().items():
            i18n.register(lang, {f"{DOMAIN}.{key}": text for key, text in table.items()}, domain=DOMAIN)
    except Exception:
        pass


def t(key: str, default: str | None = None, lang: str | None = None, **kwargs) -> str:
    """取文案并格式化占位符。

    优先走 ErisPulse i18n（已注册时），失败/未安装时退回本地 STRINGS。
    """
    table = STRINGS.get(key, {})
    text = None
    if default is None:
        default = table.get("en", key)
    try:
        from ErisPulse.Core import i18n

        text = i18n.t(f"{DOMAIN}.{key}", default=default, **kwargs)
    except Exception:
        text = None
    if not text or text == default:
        # i18n 未注册/不可用时回退本地表
        text = table.get(lang or _lang) or table.get(DEFAULT_LANG) or default
    if kwargs and "{" in text:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return text
