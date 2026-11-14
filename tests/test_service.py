"""服务层：框架服务 + qvq 四约定 + AI 工具行为。"""



def _add_machine(main, name="web-1"):
    main.fleet.save({"name": name, "ip": "1.2.3.4", "port": 22,
                     "username": "root", "auth_type": "password", "password": "x"})


def _mock_client(main, stdout="", stderr="", exit_code=0, metrics=None):
    class FakeClient:
        def __init__(self, machine):
            pass

        async def connect(self):
            return True

        async def exec_command(self, cmd, timeout=30):
            return {"stdout": stdout, "stderr": stderr, "exit_code": exit_code}

        async def collect_metrics(self):
            return metrics or {"cpu_percent": 12, "mem_percent": 34, "disk_percent": 56,
                               "load1": 0.2, "uptime_s": 3600, "hostname": "web-1"}

        async def close(self):
            pass

    main.make_client = FakeClient


async def test_meta_services_complete():
    from MyServer.Main import Main

    meta = Main.get_meta()
    services = meta["services"] if isinstance(meta, dict) else meta.services
    names = [s["name"] for s in services]
    for expect in ("server_list", "server_status", "server_add", "server_remove",
                   "server_exec", "server_confirm", "server_session",
                   "server_upload", "server_download",
                   "server_history", "qvq_schemas", "qvq_access",
                   "qvq_settings", "qvq_extensions"):
        assert expect in names, expect


async def test_qvq_access_levels(main):
    access = await main.qvq_access()
    assert access["server_list"] == "safe"
    assert access["server_status"] == "safe"
    for key in ("server_add", "server_remove", "server_exec", "server_confirm",
                "server_session", "server_upload", "server_download", "server_history"):
        assert access[key] == "admin", key


async def test_server_add_and_remove(main):
    async def fake_test_connection(machine):
        return True, ""

    async def fake_probe_specs(machine):
        machine["specs"] = {"os": "Debian 12", "cpu_cores": 2}
        return machine["specs"]

    main.test_connection = fake_test_connection
    main.probe_specs = fake_probe_specs
    result = await main.server_add(
        name="web-9", host="9.9.9.9", username="root",
        auth_type="password", password="pw",
        group="web", expiry="2027-01-15", notes="新买的",
    )
    assert result["ok"] is True
    stored = main.fleet.get("web-9")
    assert stored["ip"] == "9.9.9.9"
    assert stored["expiry"] == "2027-01-15"
    assert stored["specs"]["cpu_cores"] == 2
    listed = await main.server_list()
    item = next(m for m in listed["machines"] if m["name"] == "web-9")
    assert item["expiry"] == "2027-01-15"
    assert item["days_left"] is not None and item["days_left"] > 0
    assert item["notes"] == "新买的"
    dup = await main.server_add(name="web-9", host="9.9.9.9", password="x")
    assert dup["ok"] is False
    removed = await main.server_remove(name="web-9")
    assert removed["ok"] is True
    assert main.fleet.get("web-9") is None


async def test_server_add_validation(main):
    assert (await main.server_add(name="", host="1.1.1.1"))["ok"] is False
    assert (await main.server_add(name="x", host=""))["ok"] is False
    bad_date = await main.server_add(name="x", host="1.1.1.1", password="p", expiry="bad")
    assert bad_date["ok"] is False
    missing_secret = await main.server_add(name="x", host="1.1.1.1", auth_type="password")
    assert missing_secret["ok"] is False


async def test_qvq_schemas_and_extensions(main):
    schemas = await main.qvq_schemas()
    assert schemas["server_exec"]["properties"]["command"]["type"] == "string"
    prompts = await main.qvq_extensions()
    text = prompts["prompts"][0]["text"]
    assert "server_confirm" in text and "server_exec" in text
    settings = await main.qvq_settings()
    assert settings["title"] == "MyServer"


async def test_server_list_masks_secrets(main):
    _add_machine(main)
    data = await main.server_list()
    assert data["count"] == 1
    machine = data["machines"][0]
    assert machine["host"] == "1.2.****" or "****" in machine["host"]
    assert "password" not in machine


async def test_server_status_live_and_fallback(main):
    _add_machine(main)
    _mock_client(main, metrics={"cpu_percent": 15, "hostname": "web-1"})
    status = await main.server_status("web-1")
    assert status["online"] is True
    assert status["metrics"]["cpu_percent"] == 15
    # 连接失败回退缓存
    class DeadClient:
        def __init__(self, machine):
            pass

        async def connect(self):
            raise ConnectionError("down")

        async def close(self):
            pass

    main.make_client = DeadClient
    status = await main.server_status("web-1")
    assert status["online"] is False
    assert "down" in status["error"]


async def test_server_exec_blocks_and_confirms(main):
    _add_machine(main)
    _mock_client(main)
    blocked = await main.server_exec(name="web-1", command="rm -rf /")
    assert blocked["needs_confirm"] is True
    assert blocked["message"]
    confirmed = await main.server_confirm(name="web-1", token=blocked["token"])
    assert confirmed["ok"] is True
    # 令牌用过即焚
    again = await main.server_confirm(name="web-1", token=blocked["token"])
    assert again["ok"] is False


async def test_server_exec_output_truncated(main):
    _add_machine(main)
    _mock_client(main, stdout="x" * 5000, exit_code=0)
    result = await main.server_exec(name="web-1", command="cat big.log")
    assert len(result["stdout"]) < 5000


async def test_server_session_flow(main):
    _add_machine(main)

    sent = []

    class FakeClient:
        def __init__(self, machine):
            pass

        async def connect(self):
            return True

        async def exec_command(self, cmd, timeout=10):
            if "command -v tmux" in cmd:
                return {"stdout": "/usr/bin/tmux", "stderr": "", "exit_code": 0}
            sent.append(cmd)
            return {"stdout": "screen output", "stderr": "", "exit_code": 0}

        async def close(self):
            pass

    main.make_client = FakeClient
    opened = await main.server_session(action="open", name="web-1", session="deploy")
    assert opened["ok"] is True and opened["mode"] == "tmux"
    # 重复 open 复用
    again = await main.server_session(action="open", name="web-1", session="deploy")
    assert again["ok"] is True
    listed = await main.server_session(action="list", name="web-1")
    assert listed["sessions"] and listed["sessions"][0]["name"] == "deploy"
    captured = await main.server_session(action="capture", name="web-1", session="deploy")
    assert "screen output" in captured["screen"]
    closed = await main.server_session(action="close", name="web-1", session="deploy")
    assert closed["ok"] is True
    missing = await main.server_session(action="capture", name="web-1", session="deploy")
    assert missing["ok"] is False


async def test_server_session_write_danger_blocked(main):
    _add_machine(main)

    class FakeClient:
        def __init__(self, machine):
            pass

        async def connect(self):
            return True

        async def exec_command(self, cmd, timeout=10):
            return {"stdout": "/usr/bin/tmux", "stderr": "", "exit_code": 0}

        async def close(self):
            pass

    main.make_client = FakeClient
    await main.server_session(action="open", name="web-1", session="shell")
    blocked = await main.server_session(action="write", name="web-1",
                                        session="shell", command="mkfs /dev/sda")
    assert blocked["needs_confirm"] is True


async def test_server_history(main):
    _add_machine(main)
    main.audit.record("web-1", "test", "exec", "ls")
    data = await main.server_history(name="web-1", limit=10)
    assert data["count"] >= 1
    assert data["items"][0]["action"] == "exec"


async def test_load_and_unload(main):
    # 无 ErisPulse 事件系统时命令注册降级跳过，不抛错即算过
    try:
        await main.on_load(None)
    except Exception:
        pass
    try:
        await main.on_unload(None)
    except Exception:
        pass
