"""监控：指标落库查询、滞回阈值、告警冷却、Cron 注册。"""

import asyncio


from MyServer.monitor import Monitor


def _add_machine(main, name="web-1"):
    main.fleet.save({"name": name, "ip": "1.2.3.4", "port": 22,
                     "username": "root", "auth_type": "password", "password": "x"})


def _patch_collect(monkeypatch, metrics=None, offline=False, error="timeout"):
    """替换单台探测：直接喂指标或离线（用例结束自动还原）。"""
    metric_keys = ("cpu_percent", "mem_percent", "disk_percent", "load1")

    async def fake_check_one(self, machine):
        name = machine["name"]
        if offline:
            status = {"online": False, "metrics": {}, "error": error}
        else:
            status = {"online": True, "metrics": dict(metrics or {}), "error": ""}
        was = self._alert_state.get(name)
        self._alert_state[name] = status["online"]
        if was is not None and was != status["online"]:
            message = "back online" if status["online"] else "went offline"
            await self._fire(name, "online" if status["online"] else "offline", message)
        if status["online"]:
            for key in metric_keys:
                value = status["metrics"].get(key)
                if value is not None:
                    self.record_metric(name, key, value)
            self._check_thresholds(name, status["metrics"])
        self.main.fleet.save_status(name, status)
        return status

    monkeypatch.setattr(Monitor, "check_one", fake_check_one)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_setup_registers_cron(main):
    monitor = Monitor(main)
    _run(monitor.setup())
    assert main.sdk.cron.handlers
    assert main.sdk.cron.tasks[0]["seconds"] == main.cfg.check_interval
    assert main.sdk.cron.tasks[0]["data"]["action"] == "health_check"


def test_check_one_online_records_metrics(main, monkeypatch):
    _add_machine(main)
    monitor = Monitor(main)
    _patch_collect(monkeypatch, {"cpu_percent": 30, "mem_percent": 40, "disk_percent": 50})
    _run(monitor.check_all())
    points = monitor.get_metrics("web-1", "cpu_percent", hours=1)
    assert points and points[-1][0] == 30
    assert main.fleet.status("web-1")["online"] is True


def test_threshold_alert_and_recovery(main, monkeypatch):
    _add_machine(main)
    monitor = Monitor(main)
    monitor._alert_state["web-1"] = True
    _patch_collect(monkeypatch, {"cpu_percent": 95})
    _run(monitor.check_all())
    assert monitor._metric_state["web-1"]["cpu_percent"] == "alerting"
    _patch_collect(monkeypatch, {"cpu_percent": 78})
    _run(monitor.check_all())
    assert monitor._metric_state["web-1"]["cpu_percent"] == "ok"
    types = [a["alert_type"] for a in monitor.recent_alerts(10)]
    assert "cpu_percent" in types
    assert "cpu_percent_recovered" in types


def test_alert_cooldown_suppresses(main, monkeypatch):
    _add_machine(main)
    main._cfg.cpu_threshold = 50
    monitor = Monitor(main)
    monitor._alert_state["web-1"] = True
    _patch_collect(monkeypatch, {"cpu_percent": 90})
    _run(monitor.check_all())
    first = len(monitor.recent_alerts(50))
    monitor._metric_state["web-1"]["cpu_percent"] = "ok"
    _patch_collect(monkeypatch, {"cpu_percent": 95})
    _run(monitor.check_all())
    assert len(monitor.recent_alerts(50)) == first


def test_offline_transition_alert(main, monkeypatch):
    _add_machine(main)
    monitor = Monitor(main)
    monitor._alert_state["web-1"] = True
    _patch_collect(monkeypatch, offline=True)
    _run(monitor.check_all())
    types = [a["alert_type"] for a in monitor.recent_alerts(10)]
    assert "offline" in types
    assert main.fleet.status("web-1")["online"] is False


def test_expiry_reminder_and_daily_cooldown(main, monkeypatch):
    from datetime import date, timedelta

    expiry = (date.today() + timedelta(days=3)).isoformat()
    main.fleet.save({"name": "web-1", "ip": "1.1.1.1", "expiry": expiry})
    monitor = Monitor(main)
    monitor._alert_state["web-1"] = True
    _patch_collect(monkeypatch, {"cpu_percent": 10})
    _run(monitor.check_all())
    types = [a["alert_type"] for a in monitor.recent_alerts(10)]
    assert "expiry" in types
    # 同一天第二次检查不重复提醒
    _run(monitor.check_all())
    expiry_alerts = [a for a in monitor.recent_alerts(10) if a["alert_type"] == "expiry"]
    assert len(expiry_alerts) == 1


def test_expiry_outside_window_silent(main, monkeypatch):
    from datetime import date, timedelta

    expiry = (date.today() + timedelta(days=90)).isoformat()
    main.fleet.save({"name": "web-1", "ip": "1.1.1.1", "expiry": expiry})
    monitor = Monitor(main)
    monitor._alert_state["web-1"] = True
    _patch_collect(monkeypatch, {"cpu_percent": 10})
    _run(monitor.check_all())
    types = [a["alert_type"] for a in monitor.recent_alerts(10)]
    assert "expiry" not in types


def test_expiry_disabled(main, monkeypatch):
    from datetime import date, timedelta

    main._cfg.expiry_remind_days = 0
    expiry = (date.today() + timedelta(days=3)).isoformat()
    main.fleet.save({"name": "web-1", "ip": "1.1.1.1", "expiry": expiry})
    monitor = Monitor(main)
    monitor._alert_state["web-1"] = True
    _patch_collect(monkeypatch, {"cpu_percent": 10})
    _run(monitor.check_all())
    types = [a["alert_type"] for a in monitor.recent_alerts(10)]
    assert "expiry" not in types


def test_audit_record_and_tail(main):
    main.audit.record("web-1", "test", "exec", "ls -la", "ok")
    main.audit.record("db-1", "test", "exec", "df -h", "warn")
    rows = main.audit.tail()
    assert len(rows) == 2
    rows = main.audit.tail("web-1")
    assert rows and rows[0]["machine"] == "web-1"
    assert rows[0]["digest"]
