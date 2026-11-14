"""SSH 层：指标解析、临时私钥、连接失败路径（asyncssh mock）。"""

import pytest

from MyServer.ssh import SSHClient, parse_metrics, summary_line


SAMPLE_OUTPUT = (
    '{"hostname":"web-1","os":"Debian GNU/Linux 12","kernel":"6.1.0-18-amd64",'
    '"uptime_s":259200,"cpu_cores":2,"cpu_percent":12.5,'
    '"mem_total_kb":2000000,"mem_avail_kb":1000000,'
    '"disk_kb":"40000000:10000000","load":"0.10 0.15 0.20"}'
)


def test_metrics_script_shape():
    """采集脚本必须是合法 sh 命令替换，且输出单行 JSON。"""
    from MyServer.ssh import METRICS_SCRIPT

    assert "$((." not in METRICS_SCRIPT  # 误写成算术展开会让整段脚本语法错误
    assert 'OS=$(. /etc/os-release' in METRICS_SCRIPT
    assert "${UPTIME:-null}" in METRICS_SCRIPT
    assert 'disk_kb' in METRICS_SCRIPT


def test_parse_metrics_full():
    metrics = parse_metrics(SAMPLE_OUTPUT + "\n")
    assert metrics["hostname"] == "web-1"
    assert metrics["cpu_percent"] == 12.5
    assert metrics["load1"] == 0.10
    assert metrics["mem_percent"] == 50.0
    assert metrics["disk_percent"] == 25.0
    assert metrics["uptime_s"] == 259200


def test_parse_metrics_missing_fields():
    metrics = parse_metrics("garbage\nno json here")
    assert metrics["cpu_percent"] is None
    assert metrics["mem_percent"] is None
    assert metrics["hostname"] == ""


def test_parse_metrics_tolerates_nulls():
    raw = '{"hostname":"x","cpu_percent":null,"load":"","disk_kb":"bad"}'
    metrics = parse_metrics(raw)
    assert metrics["cpu_percent"] is None
    assert metrics["load1"] is None
    assert metrics["disk_percent"] is None


def test_summary_line():
    metrics = parse_metrics(SAMPLE_OUTPUT)
    line = summary_line(metrics)
    assert "CPU 12%" in line and "MEM 50%" in line and "up 3d" in line
    assert summary_line({}) == "online"


def test_write_temp_key_and_close():
    import os

    client = SSHClient("1.2.3.4", private_key="-----BEGIN TEST KEY-----\nabc\n")
    path = client._write_temp_key(client.private_key)
    try:
        assert os.path.isfile(path)
        with open(path) as f:
            content = f.read()
        assert content.endswith("\n")
        mode = os.stat(path).st_mode & 0o777
        if os.name != "nt":  # Windows chmod 只切只读位，不表示 POSIX 权限
            assert mode == 0o600
    finally:
        import asyncio

        asyncio.get_event_loop_policy().new_event_loop().run_until_complete(client.close())
    assert not os.path.isfile(path)
    assert client._temp_key_path is None


def test_paste_key_disabled():
    client = SSHClient("1.2.3.4", private_key="abc", allow_paste_keys=False)
    import asyncio

    async def _call():
        with pytest.raises(ConnectionError):
            await client.connect()

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(_call())


def test_exec_without_connection():
    """connect 失败时 exec_command 不再二次 connect（抛 ConnectionError 由上层接）。"""
    import asyncio

    client = SSHClient("127.0.0.1", port=1, username="x", password="bad")

    async def _call():
        with pytest.raises(ConnectionError):
            await client.exec_command("echo hi")

    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(_call())


def test_metrics_script_roundtrip(monkeypatch):
    """collect_metrics：mock 掉 exec_command，验证脚本→解析链路。"""
    import asyncio

    client = SSHClient("1.2.3.4")

    async def fake_exec(cmd, timeout=30):
        return {"stdout": SAMPLE_OUTPUT, "stderr": "", "exit_code": 0}

    monkeypatch.setattr(client, "exec_command", fake_exec)
    metrics = asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        client.collect_metrics())
    assert metrics["hostname"] == "web-1"
