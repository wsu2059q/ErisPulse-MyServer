"""机器注册表：增删改查、凭据剥离、分组、批量目标解析。"""

from MyServer.fleet import Fleet


def _fleet():
    from fakes import FakeStorage

    return Fleet(FakeStorage())


def test_save_get_delete_roundtrip():
    fleet = _fleet()
    assert fleet.save({"name": "web-1", "ip": "1.2.3.4", "port": 22,
                       "username": "root", "auth_type": "password", "password": "pw"})
    machine = fleet.get("web-1")
    assert machine["ip"] == "1.2.3.4"
    assert machine["added_at"] > 0
    assert fleet.names() == ["web-1"]
    assert fleet.delete("web-1")
    assert fleet.get("web-1") is None
    assert fleet.names() == []
    assert not fleet.delete("web-1")


def test_save_requires_name():
    fleet = _fleet()
    assert not fleet.save({"ip": "1.2.3.4"})
    assert not fleet.save({"name": "  ", "ip": "1.2.3.4"})


def test_redact_strips_secrets():
    fleet = _fleet()
    fleet.save({"name": "web-1", "ip": "1.2.3.4", "port": 22, "username": "root",
                "auth_type": "key", "private_key": "-----BEGIN KEY-----", "password": ""})
    view = fleet.redact(fleet.get("web-1"))
    assert view["private_key"] == "****"
    # 原始数据不动
    assert fleet.get("web-1")["private_key"].startswith("-----BEGIN")


def test_groups_and_resolve_targets():
    fleet = _fleet()
    fleet.save({"name": "web-1", "ip": "1.1.1.1", "group": "web"})
    fleet.save({"name": "web-2", "ip": "1.1.1.2", "group": "web"})
    fleet.save({"name": "db-1", "ip": "2.2.2.2"})
    assert fleet.groups()["web"] == ["web-1", "web-2"]
    assert fleet.resolve_targets("group:web") == ["web-1", "web-2"]
    assert fleet.resolve_targets("web-1, db-1") == ["web-1", "db-1"]
    assert fleet.resolve_targets("web-1,web-1,ghost") == ["web-1"]


def test_status_and_stats():
    fleet = _fleet()
    fleet.save({"name": "web-1", "ip": "1.1.1.1"})
    fleet.save({"name": "db-1", "ip": "2.2.2.2"})
    fleet.save_status("web-1", {"online": True, "metrics": {"cpu_percent": 10}})
    machines = fleet.all()
    online = {m["name"]: m["online"] for m in machines}
    assert online == {"web-1": True, "db-1": False}
    stats = fleet.stats()
    assert stats == {"total": 2, "online": 1, "offline": 1}
    assert fleet.status("web-1")["metrics"]["cpu_percent"] == 10
