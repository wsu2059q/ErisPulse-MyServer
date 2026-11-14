"""MyServer 声明式配置。"""

from __future__ import annotations

from dataclasses import dataclass, field

try:  # 独立运行/测试环境没有 ErisPulse 时仍可实例化配置
    from ErisPulse.Core.Bases import BaseConfig
except Exception:  # pragma: no cover - 环境兜底
    BaseConfig = object  # type: ignore[assignment, misc]


def _desc(key: str, text: str, group: str, order: int, widget: str = "text",
          options: list | None = None) -> dict:
    ui: dict = {"widget": widget, "group": group, "order": order}
    if options is not None:
        ui["options"] = options
    return {"description": {"i18n": f"MyServer.{key}", "default": text}, "ui": ui}


@dataclass
class MyServerConfig(BaseConfig):
    # ---- 执行 ----
    exec_timeout: int = field(
        default=60,
        metadata=_desc("exec_timeout", "命令执行默认超时（秒）", "exec", 1, "number"),
    )
    admin_users: list[str] = field(
        default_factory=list,
        metadata=_desc("admin_users", "管理员名单（platform:user_id 或裸 user_id）；留空 = 仅框架主人。执行/上传等敏感操作仅管理员可用", "exec", 2, "lines"),
    )
    max_sessions: int = field(
        default=8,
        metadata=_desc("max_sessions", "同时托管的终端会话上限", "exec", 3, "number"),
    )
    allow_paste_keys: bool = field(
        default=True,
        metadata=_desc("allow_paste_keys", "允许粘贴私钥内容（自动落临时文件 0600，连接结束即删）；关闭后只接受服务器上的密钥路径", "exec", 4, "switch"),
    )
    prefer_tmux: bool = field(
        default=True,
        metadata=_desc("prefer_tmux", "会话优先跑在远端 tmux 里（重启/断线不丢现场）；远端无 tmux 时自动降级本机 PTY", "exec", 5, "switch"),
    )

    # ---- 监控 ----
    check_interval: int = field(
        default=60,
        metadata=_desc("check_interval", "监控采集间隔（秒）：每轮对全部机器做一次单往返指标采集", "monitor", 1, "number"),
    )
    monitor_enabled: bool = field(
        default=True,
        metadata=_desc("monitor_enabled", "开启定时监控与上下线/阈值告警", "monitor", 2, "switch"),
    )
    alert_targets: list[str] = field(
        default_factory=list,
        metadata=_desc("alert_targets", "告警推送目标（platform:type:id，如 onebot11:group:123456）；留空 = 广播到所有运行中适配器", "monitor", 3, "lines"),
    )
    alert_cooldown_min: int = field(
        default=30,
        metadata=_desc("alert_cooldown_min", "同一机器同一告警类型的冷却（分钟）：防告警风暴", "monitor", 4, "number"),
    )
    history_retention_days: int = field(
        default=7,
        metadata=_desc("history_retention_days", "指标历史保留天数（超期清理）", "monitor", 5, "number"),
    )
    expiry_remind_days: int = field(
        default=7,
        metadata=_desc("expiry_remind_days", "到期提醒窗口（天）：机器到期前 N 天开始每天推送一次提醒，0 关闭", "monitor", 6, "number"),
    )

    # ---- 阈值（滞回：触发值 > 阈值，恢复值 = 阈值 - 10） ----
    cpu_threshold: int = field(
        default=90,
        metadata=_desc("cpu_threshold", "CPU 占用告警阈值（%，恢复值自动减 10）", "thresholds", 1, "number"),
    )
    mem_threshold: int = field(
        default=90,
        metadata=_desc("mem_threshold", "内存占用告警阈值（%，恢复值自动减 10）", "thresholds", 2, "number"),
    )
    disk_threshold: int = field(
        default=90,
        metadata=_desc("disk_threshold", "磁盘占用告警阈值（%，恢复值自动减 10）", "thresholds", 3, "number"),
    )
    load_factor: float = field(
        default=2.0,
        metadata=_desc("load_factor", "负载告警倍数：load1 超过 CPU 核数 × 该倍数时告警", "thresholds", 4, "number"),
    )

    # ---- 传输 ----
    transfer_max_mb: int = field(
        default=100,
        metadata=_desc("transfer_max_mb", "SFTP 上传/下载单文件体积上限（MB）", "transfer", 1, "number"),
    )

    # ---- 公开状态页 ----
    public_page: bool = field(
        default=False,
        metadata=_desc("public_page", "公开状态页（/MyServer/public，免鉴权探针页，展示机器在线与指标缓存）", "public", 1, "switch"),
    )
    public_title: str = field(
        default="Server Status",
        metadata=_desc("public_title", "公开状态页标题", "public", 2),
    )
    public_show_host: bool = field(
        default=False,
        metadata=_desc("public_show_host", "公开页展示打码后的主机地址（默认只显示机器名）", "public", 3, "switch"),
    )
    public_refresh_seconds: int = field(
        default=30,
        metadata=_desc("public_refresh_seconds", "公开页自动刷新间隔（秒，0 = 仅手动刷新）；读取监控缓存，不触发实时探测", "public", 4, "number"),
    )
    public_history_points: int = field(
        default=40,
        metadata=_desc("public_history_points", "公开页每台机器的历史格子数（每格 = 一次监控检查的在线/离线）", "public", 5, "number"),
    )
    public_geo: bool = field(
        default=False,
        metadata=_desc("public_geo", "公开页自动查询机器所属国家（经 ipapi.co 外部接口，结果缓存 24 小时；隐私敏感场景保持关闭）", "public", 6, "switch"),
    )
    public_fields: list[str] = field(
        default_factory=lambda: ["cpu", "mem", "disk", "load", "uptime", "history", "events"],
        metadata=_desc("public_fields", "公开页展示的字段（cpu/mem/disk/load/uptime/history/events），列表外的字段不展示；全部清空 = 只显示机器名与在线状态", "public", 7, "lines"),
    )
