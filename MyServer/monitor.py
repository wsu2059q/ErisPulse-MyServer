"""监控：定时采集、阈值滞回告警、上下线通知、定时命令。

定时走 ErisPulse-Cron：一个 interval 任务按 check_interval 触发，
on_trigger 按 data.action 分发。
"""

from __future__ import annotations

import asyncio
import time

from .fleet import days_until
from .ssh import SSHClient, summary_line
from . import texts

METRICS_HISTORY_TABLE = "myserver_history"
ALERTS_TABLE = "myserver_alerts"

# 滞回恢复差值：触发超阈值，回落到阈值-该值才算恢复
HYSTERESIS = 10.0
_METRIC_KEYS = ("cpu_percent", "mem_percent", "disk_percent")


def _specs_of(metrics: dict) -> dict:
    """{!--< internal-use >!--} 从指标提取静态配置快照。"""
    return {
        "hostname": metrics.get("hostname") or "",
        "os": metrics.get("os") or "",
        "kernel": metrics.get("kernel") or "",
        "cpu_cores": metrics.get("cpu_cores"),
        "mem_total": metrics.get("mem_total_text") or "",
        "disk_total": metrics.get("disk_total_text") or "",
    }


class Monitor:
    """舰队监控器。"""

    def __init__(self, main):
        self.main = main
        self.logger = main.logger
        # state[machine][metric] = "alerting" | "ok"，上下线另用 online 表
        self._metric_state: dict[str, dict[str, str]] = {}
        self._alert_state: dict[str, bool] = {}
        self._cooldown: dict[tuple, float] = {}
        self._expiry_notified: set[tuple] = set()
        # name -> (ts, rx_bytes, tx_bytes)：网络速率用上次采样做差
        self._last_net: dict[str, tuple] = {}

    async def setup(self) -> None:
        """注册 Cron 采集任务（已存在则跳过）。"""
        cfg = self.main.cfg
        try:
            self.main.sdk.Cron.on_trigger(self._on_cron_trigger)
            existing = self.main.sdk.Cron.list_tasks(source="MyServer")
            if not existing:
                self.main.sdk.Cron.interval(
                    seconds=int(cfg.check_interval),
                    source="MyServer",
                    data={"__source": "MyServer", "action": "health_check"},
                )
                self.logger.info(texts.t("cron_registered", interval=cfg.check_interval))
            else:
                self.logger.info(texts.t("cron_existing"))
        except Exception as e:
            self.logger.warning(f"cron setup failed: {e}")

    async def _on_cron_trigger(self, info: dict) -> None:
        """{!--< internal-use >!--} Cron 分发入口。"""
        data = info.get("data", {}) if isinstance(info, dict) else {}
        if data.get("__source") != "MyServer":
            return
        action = data.get("action", "")
        if action == "health_check":
            await self.check_all()
        elif action == "scheduled_command":
            await self.run_scheduled(data)

    async def check_all(self) -> None:
        """采集全部机器：并发单台探测。"""
        machines = self.main.fleet.all(include_secrets=True)
        if machines:
            await asyncio.gather(*(self.check_one(m) for m in machines))
        self.check_expiries()
        try:
            self.main.safety_gate.sweep()
        except Exception:
            pass

    async def check_one(self, machine: dict) -> dict:
        """
        单台探测：连接 → 指标采集 → 历史落库 → 上下线与阈值判定。

        :param machine: [dict] 机器字典（含凭据）
        :return: [dict] {"online", "metrics", "error"}
        """
        name = str(machine.get("name") or "")
        status: dict = {"online": False, "metrics": {}, "error": ""}
        client = self.main.make_client(machine)
        try:
            await asyncio.wait_for(self._collect(name, client, status), timeout=20)
        except asyncio.TimeoutError:
            status["error"] = "timeout"
        except Exception as e:
            status["error"] = str(e)
        finally:
            await client.close()

        was_online = self._alert_state.get(name)
        is_online = status["online"]
        self.record_metric(name, "online", 1.0 if is_online else 0.0)
        self._alert_state[name] = is_online
        if was_online is not None and was_online != is_online:
            await self._fire(name, "online" if is_online else "offline",
                             texts.t("alert_online" if is_online else "alert_offline",
                                     name=name, summary=summary_line(status["metrics"])))
        if is_online:
            self._check_thresholds(name, status["metrics"])
        self.main.fleet.save_status(name, status)
        return status

    async def _collect(self, name: str, client: SSHClient, status: dict) -> None:
        """{!--< internal-use >!--} 连接并采指标、落历史。"""
        await client.connect()
        if not await client.check_alive():
            status["error"] = "no response"
            return
        status["online"] = True
        metrics = await client.collect_metrics()
        status["metrics"] = metrics
        status["specs"] = _specs_of(metrics)
        for key in _METRIC_KEYS + ("tcp",):
            value = metrics.get(key)
            if value is not None:
                self.record_metric(name, key, value)
        self._record_net_rates(name, metrics)
        self.record_metric(name, "uptime_s", metrics.get("uptime_s") or 0)

    def _record_net_rates(self, name: str, metrics: dict) -> None:
        """{!--< internal-use >!--} 网络速率：与上次累计量做差换算 KB/s；首采样只记基数。"""
        rx = metrics.get("net_rx_bytes")
        tx = metrics.get("net_tx_bytes")
        if rx is None or tx is None:
            return
        now = time.time()
        prev = self._last_net.get(name)
        if prev is not None:
            dt = now - prev[0]
            if dt > 0:
                self.record_metric(name, "net_rx_rate", max(0.0, (rx - prev[1]) / dt / 1024))
                self.record_metric(name, "net_tx_rate", max(0.0, (tx - prev[2]) / dt / 1024))
        self._last_net[name] = (now, rx, tx)

    # ---------- 阈值判定 ----------

    def _check_thresholds(self, name: str, metrics: dict) -> None:
        """{!--< internal-use >!--} 滞回阈值判定与告警触发。"""
        cfg = self.main.cfg
        thresholds = {
            "cpu_percent": (float(cfg.cpu_threshold), "{:.0f}%"),
            "mem_percent": (float(cfg.mem_threshold), "{:.0f}%"),
            "disk_percent": (float(cfg.disk_threshold), "{:.0f}%"),
        }
        cores = metrics.get("cpu_cores")
        if cores:
            thresholds["load1"] = (float(cores) * float(cfg.load_factor), "{:.2f}")
        state = self._metric_state.setdefault(name, {})
        for key, (threshold, _fmt) in thresholds.items():
            value = metrics.get(key)
            if value is None:
                continue
            current = state.get(key, "ok")
            if current != "alerting" and value > threshold:
                state[key] = "alerting"
                self._spawn_alert(name, key, value, threshold)
            elif current == "alerting" and value <= threshold - HYSTERESIS:
                state[key] = "ok"
                self._spawn_alert(name, f"{key}_recovered", value, threshold - HYSTERESIS)

    def _spawn_alert(self, name: str, key: str, value: float, threshold: float) -> None:
        """{!--< internal-use >!--} 冷却检查（恢复告警不吃冷却）+ 异步发送。"""
        recovered = key.endswith("_recovered")
        if not recovered:
            cooldown_min = max(1, int(self.main.cfg.alert_cooldown_min))
            now = time.time()
            cooldown_key = (name, key.split("_")[0])
            if now - self._cooldown.get(cooldown_key, 0) < cooldown_min * 60:
                return
            self._cooldown[cooldown_key] = now
        template = texts.t("alert_recovered" if recovered else "alert_threshold",
                           name=name, metric=key, value=value, threshold=threshold)
        self.main.spawn(self._fire(name, key, template))

    async def _fire(self, name: str, alert_type: str, message: str) -> None:
        """{!--< internal-use >!--} 告警落库并推送。"""
        self.record_alert(name, alert_type, message)
        try:
            await self.main.push_message(message)
        except Exception as e:
            self.logger.warning(f"alert push failed: {e}")

    # ---------- 到期提醒 ----------

    def check_expiries(self) -> None:
        """到期进入提醒窗口（expiry_remind_days）时推送告警；每台每天最多一次。"""
        remind_days = int(self.main.cfg.expiry_remind_days)
        if remind_days <= 0:
            return
        today = time.strftime("%Y-%m-%d")
        for machine in self.main.fleet.all(include_secrets=True):
            name = str(machine.get("name") or "")
            expiry = str(machine.get("expiry") or "").strip()
            days = days_until(expiry)
            if days is None or days > remind_days:
                continue
            key = (name, today)
            if key in self._expiry_notified:
                continue
            self._expiry_notified.add(key)
            if days == 0:
                message = texts.t("alert_expiry_today", name=name, date=expiry)
            elif days > 0:
                message = texts.t("alert_expiry_soon", name=name, days=days, date=expiry)
            else:
                message = texts.t("alert_expiry_overdue", name=name, days=-days, date=expiry)
            self.main.spawn(self._fire(name, "expiry", message))

    # ---------- 定时命令 ----------

    async def run_scheduled(self, data: dict) -> None:
        """
        执行定时命令，失败告警。

        :param data: [dict] {"machine_name", "command"}
        """
        name = str(data.get("machine_name") or "")
        command = str(data.get("command") or "")
        machine = self.main.fleet.get(name)
        if machine is None:
            self.logger.warning(f"scheduled task: machine {name} not found")
            return
        client = self.main.make_client(machine)
        try:
            await client.connect()
            result = await client.exec_command(command, timeout=int(self.main.cfg.exec_timeout))
            if result.get("exit_code", -1) != 0:
                raise RuntimeError(result.get("stderr") or f"exit {result.get('exit_code')}")
        except Exception as e:
            self.record_alert(name, "scheduled_command_failed", command)
            message = texts.t("alert_scheduled_fail", name=name, command=command, error=str(e))
            self.main.spawn(self._fire(name, "scheduled_command_failed", message))
        finally:
            await client.close()

    # ---------- 存储 ----------

    def record_metric(self, machine: str, metric: str, value: float) -> None:
        """
        指标历史落库。

        :param machine: [str] 机器名
        :param metric: [str] 指标名
        :param value: [float] 数值
        """
        try:
            if not self.main.sdk.storage.HasTable(METRICS_HISTORY_TABLE):
                self.main.sdk.storage.CreateTable(METRICS_HISTORY_TABLE, {
                    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                    "machine_name": "TEXT NOT NULL",
                    "metric_type": "TEXT NOT NULL",
                    "value": "REAL NOT NULL",
                    "timestamp": "REAL NOT NULL",
                })
            self.main.sdk.storage.Table(METRICS_HISTORY_TABLE).Insert({
                "machine_name": machine, "metric_type": metric,
                "value": float(value), "timestamp": time.time(),
            }).Execute()
        except Exception:
            pass

    def get_metrics(self, machine: str, metric: str, hours: int = 24) -> list:
        """
        指标历史查询。

        :param machine: [str] 机器名
        :param metric: [str] 指标名
        :param hours: [int] 回看小时数 (默认: 24)
        :return: [list] [(value, timestamp)]
        """
        try:
            cutoff = time.time() - hours * 3600
            rows = (self.main.sdk.storage.Table(METRICS_HISTORY_TABLE)
                    .Select("value", "timestamp").ToDict()
                    .Where("machine_name = ? AND metric_type = ? AND timestamp > ?",
                           machine, metric, cutoff)
                    .OrderBy("timestamp").Execute())
            return [(r["value"], r["timestamp"]) for r in rows] if rows else []
        except Exception:
            return []

    def record_alert(self, machine: str, alert_type: str, message: str) -> None:
        """
        告警落库。

        :param machine: [str] 机器名
        :param alert_type: [str] 告警类型
        :param message: [str] 文案
        """
        try:
            if not self.main.sdk.storage.HasTable(ALERTS_TABLE):
                self.main.sdk.storage.CreateTable(ALERTS_TABLE, {
                    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
                    "machine_name": "TEXT NOT NULL",
                    "alert_type": "TEXT NOT NULL",
                    "message": "TEXT",
                    "timestamp": "REAL NOT NULL",
                })
            self.main.sdk.storage.Table(ALERTS_TABLE).Insert({
                "machine_name": machine, "alert_type": alert_type,
                "message": message, "timestamp": time.time(),
            }).Execute()
        except Exception:
            pass

    def recent_alerts(self, limit: int = 50) -> list:
        """
        最近告警（新在前）。

        :param limit: [int] 条数上限 (默认: 50)
        :return: [list] 告警行
        """
        try:
            rows = (self.main.sdk.storage.Table(ALERTS_TABLE)
                    .Select("*").ToDict()
                    .OrderBy("timestamp", desc=True).Limit(int(limit)).Execute())
            return rows if rows else []
        except Exception:
            return []

    def cleanup(self) -> None:
        """按 history_retention_days 清理指标历史。"""
        try:
            cutoff = time.time() - int(self.main.cfg.history_retention_days) * 86400
            self.main.sdk.storage.Table(METRICS_HISTORY_TABLE).Delete().Where(
                "timestamp < ?", cutoff).Execute()
        except Exception:
            pass
