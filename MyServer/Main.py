"""MyServer 主模块：生命周期装配、权限判定、告警推送。"""

from __future__ import annotations

import asyncio

try:
    from ErisPulse import sdk
except ImportError:  # 独立运行/测试环境兜底
    sdk = None

try:
    from ErisPulse.Core.Bases import BaseModule
except ImportError:  # pragma: no cover
    BaseModule = object  # type: ignore[assignment, misc]

try:
    from ErisPulse.Core.Bases import ModuleMeta
except ImportError:  # pragma: no cover
    ModuleMeta = None

try:
    from ErisPulse.loaders import ModuleLoadStrategy
except ImportError:  # pragma: no cover
    ModuleLoadStrategy = None

from . import texts
from .audit import AuditLog
from .commands import register_commands
from .Config import MyServerConfig
from .files import FileOps
from .fleet import Fleet
from .monitor import Monitor
from .ops import ServerOps
from .safety import ConfirmGate, grade
from .service import EXTENSION_PROMPTS, ACCESS, SCHEMAS, SERVICES, ServiceMixin
from .sessions import SessionManager
from .ssh import SSHClient

__version__ = "2.0.0"


class _NullLogger:
    """sdk.logger 不可用时的静默兜底。"""

    def debug(self, *a, **k):
        pass

    info = warning = error = debug


class Main(BaseModule, ServiceMixin):
    """MyServer 2.0 主模块。"""

    ConfigClass = MyServerConfig

    def __init__(self):
        self.sdk = sdk
        self.logger = self._make_logger()
        self._cfg: MyServerConfig | None = None
        self.fleet = Fleet(getattr(self.sdk, "storage", None))
        self.audit = AuditLog(getattr(self.sdk, "storage", None))
        self.gate = ConfirmGate()
        self.sessions = SessionManager()
        self.ops = ServerOps(self)
        self.files_ops = FileOps(self)
        self.monitor = Monitor(self)
        self._dash = None

    # ==================== 元信息 ====================

    @staticmethod
    def get_meta():
        info = dict(
            name="MyServer",
            description="ErisPulse 服务器管理模块 2.0：聊天平台里的 AI 原生机房 —— SSH 会话托管、舰队监控告警、危险命令确认",
            version=__version__,
            group="工具",
            tags=["ssh", "server", "monitor", "terminal", "qvq"],
            services=[dict(s) for s in SERVICES],
            min_sdk_version="2.8.0",
        )
        if ModuleMeta is not None:
            try:
                return ModuleMeta(**info)
            except Exception:
                return info
        return info

    @staticmethod
    def get_load_strategy():
        strategy = dict(lazy_load=False, priority=40, depends=["Cron"])
        if ModuleLoadStrategy is not None:
            try:
                return ModuleLoadStrategy(**strategy)
            except Exception:
                pass
        return strategy

    # ==================== 配置 ====================

    @property
    def cfg(self) -> MyServerConfig:
        """生效配置（框架 ConfigClass 值优先，缺失时用本地实例）。"""
        if self._cfg is not None:
            return self._cfg
        try:
            data = self.sdk.config.getConfig("MyServer")
        except Exception:
            data = None
        if isinstance(data, dict) and data:
            try:
                self._cfg = MyServerConfig(**{
                    k: v for k, v in data.items() if k in MyServerConfig.__dataclass_fields__
                })
                return self._cfg
            except Exception:
                pass
        self._cfg = MyServerConfig()
        return self._cfg

    # ==================== 生命周期 ====================

    async def on_load(self, event) -> bool:
        """装载：文案注册、命令注册、监控启动、Dashboard 视窗。"""
        try:
            texts.register_texts()
        except Exception:
            pass
        register_commands(self)
        self.sessions.max_sessions = max(1, int(self.cfg.max_sessions))
        self.sessions.prefer_tmux = bool(self.cfg.prefer_tmux)
        if bool(self.cfg.monitor_enabled):
            await self.monitor.setup()
            # 启动即补采一轮，概览/选择器不必等到第一个 Cron 周期才有在线状态
            self.spawn(self.monitor.check_all())
        try:
            from .dashboard import DashboardIntegration

            self._dash = DashboardIntegration(self)
            if self._dash.setup():
                self.logger.info(texts.t("dashboard_registered"))
        except Exception as e:
            self.logger.warning(texts.t("dashboard_unavailable") + f": {e}")
        stats = self.fleet.stats()
        self.logger.info(texts.t("loaded", machines=stats["total"],
                                 interval=self.cfg.check_interval))
        return True

    async def on_unload(self, event) -> bool:
        """卸载：关会话、撤路由与视窗。"""
        if self._dash is not None:
            try:
                self._dash.teardown()
            except Exception:
                pass
            self._dash = None
        try:
            await self.sessions.close_all()
        except Exception:
            pass
        try:
            await self.files_ops.close_all()
        except Exception:
            pass
        return True

    # ==================== 基础设施 ====================

    def spawn(self, coro):
        """
        后台任务调度（对齐框架 Module.spawn）。

        :param coro: [Coroutine] 协程
        :return: [asyncio.Task] 任务
        """
        return asyncio.ensure_future(coro)

    def _make_logger(self):
        try:
            return sdk.logger.get_child("MyServer")
        except Exception:
            return _NullLogger()

    def make_client(self, machine: dict) -> SSHClient:
        """
        按机器字典构造 SSH 客户端。

        :param machine: [dict] 机器字典（含凭据）
        :return: [SSHClient] 未连接的客户端
        """
        auth_type = str(machine.get("auth_type") or "password")
        return SSHClient(
            host=str(machine.get("ip") or ""),
            port=int(machine.get("port") or 22),
            username=str(machine.get("username") or "root"),
            password=str(machine.get("password") or "") if auth_type == "password" else "",
            key_path=str(machine.get("key_path") or ""),
            private_key=str(machine.get("private_key") or "") if auth_type == "key" else "",
            allow_paste_keys=bool(self.cfg.allow_paste_keys),
        )

    def grade(self, command: str) -> dict:
        """
        危险分级代理。

        :param command: [str] 命令文本
        :return: [dict] {"level", "reason"}
        """
        return grade(command)

    # ==================== 权限 ====================

    def is_admin(self, actor: str) -> bool:
        """
        管理员判定：cfg.admin_users 命中或框架主人；名单为空时仅框架主人。

        :param actor: [str] chat:<platform>:<uid> 形态标识
        :return: [bool] 是否管理员
        """
        uid = actor.rsplit(":", 1)[-1]
        platform = actor.split(":")[1] if actor.count(":") >= 2 else ""
        configured = list(self.cfg.admin_users or [])
        if configured and uid in {str(u).strip() for u in configured}:
            return True
        try:
            from ErisPulse.Core import master

            is_master = getattr(master, "is_master", None)
            if callable(is_master):
                return bool(is_master(platform, uid))
        except Exception:
            pass
        return False

    # ==================== 推送 ====================

    async def push_message(self, text: str) -> None:
        """
        告警推送：配置目标逐个发送，否则广播全部运行中适配器。

        :param text: [str] 文本内容
        """
        adapter = getattr(self.sdk, "adapter", None)
        if adapter is None:
            return
        targets = [t.strip() for t in (self.cfg.alert_targets or []) if t.strip()]
        if targets:
            for spec in targets:
                try:
                    platform, target_type, target_id = spec.split(":", 2)
                    chain = adapter.get(platform).Send.To(target_type, target_id)
                    await chain.Text(text)
                except Exception as e:
                    self.logger.warning(f"alert push to {spec} failed: {e}")
            return
        for platform_name in adapter.list_running():
            try:
                await adapter.get(platform_name).Send.Text(text)
            except Exception as e:
                self.logger.warning(f"alert broadcast [{platform_name}] failed: {e}")

    async def test_connection(self, machine: dict) -> tuple[bool, str]:
        """
        连接测试。

        :param machine: [dict] 机器字典
        :return: [tuple[bool, str]] (成功, 失败原因)
        """
        client = self.make_client(machine)
        try:
            await client.connect()
            alive = await client.check_alive()
            return alive, "" if alive else "no response"
        except Exception as e:
            return False, str(e)
        finally:
            await client.close()

    async def probe_specs(self, machine: dict) -> dict:
        """
        采集机器静态配置快照并写回机器字典。

        :param machine: [dict] 机器字典（含凭据，需已注册）
        :return: [dict] specs（失败返回空字典）
        """
        client = self.make_client(machine)
        try:
            await client.connect()
            metrics = await client.collect_metrics()
        except Exception:
            return {}
        finally:
            await client.close()
        specs = {
            "hostname": metrics.get("hostname") or "",
            "os": metrics.get("os") or "",
            "kernel": metrics.get("kernel") or "",
            "cpu_cores": metrics.get("cpu_cores"),
            "mem_total": metrics.get("mem_total_text") or "",
            "disk_total": metrics.get("disk_total_text") or "",
        }
        machine["specs"] = specs
        self.fleet.save(machine)
        return specs


__all__ = ["Main", "__version__", "ACCESS", "EXTENSION_PROMPTS", "SCHEMAS", "SERVICES"]
