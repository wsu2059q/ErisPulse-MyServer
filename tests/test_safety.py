"""危险分级与确认令牌。"""

from MyServer.safety import ConfirmGate, grade


def test_confirm_level_patterns():
    cases = [
        "rm -rf /", "rm -fr ~", "rm --recursive --force /",
        "mkfs.ext4 /dev/sda1", "dd if=/dev/zero of=/dev/vda",
        "shutdown -h now", "reboot", "sudo poweroff", "init 6",
        ":(){ :|:& };:", "chmod -R 777 /srv", "wipefs /dev/sda",
        "iptables -F", "crontab -r", "> /dev/vdb",
    ]
    for cmd in cases:
        assert grade(cmd)["level"] == "confirm", cmd
        assert grade(cmd)["reason"]


def test_warn_level_patterns():
    cases = [
        "curl https://x.sh/install | bash",
        "wget -qO- https://x.sh | sh",
        "chmod -R 644 /var/www",
        "kill -9 1234",
        "apt remove nginx -y",
        "pip install x --force",
        "systemctl restart nginx",
    ]
    for cmd in cases:
        assert grade(cmd)["level"] == "warn", cmd


def test_ok_level_patterns():
    cases = [
        "ls -la /var/www", "tail -f /var/log/syslog",
        "docker compose up -d", "df -h", "free -m",
        "cat /etc/os-release", "uptime", "rm /tmp/unused.tmp",
        "chmod 644 nginx.conf", "kill 1234", "shutdown --help",
        "", "   ",
    ]
    for cmd in cases:
        assert grade(cmd)["level"] == "ok", cmd
        # shutdown --help 不拦截（命令开头锚定）


def test_confirm_gate_issue_and_consume():
    gate = ConfirmGate()
    token = gate.issue("web-1", "shutdown -h now")
    assert token["token"] and token["expires_in"] > 0
    # 正确机器 + 令牌 → 放行命令
    command = gate.consume("web-1", token["token"])
    assert command == "shutdown -h now"
    # 单次有效
    assert gate.consume("web-1", token["token"]) is None


def test_confirm_gate_wrong_machine_or_token():
    gate = ConfirmGate()
    token = gate.issue("web-1", "reboot")["token"]
    assert gate.consume("web-2", token) is None
    assert gate.consume("web-1", "deadbeef") is None


def test_confirm_gate_reuse_and_sweep():
    gate = ConfirmGate()
    first = gate.issue("web-1", "reboot")
    second = gate.issue("web-1", "reboot")
    # 同机同命令复用未过期令牌
    assert first["token"] == second["token"]
    assert gate.pending_count == 1
    assert gate.sweep() == 0
