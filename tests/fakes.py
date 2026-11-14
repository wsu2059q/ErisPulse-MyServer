"""测试公共夹具：伪 SDK / 伪存储 / 伪 Main。"""

from __future__ import annotations



from MyServer.Config import MyServerConfig
from MyServer.Main import Main


class FakeStorage:
    """sdk.storage 的内存实现（get/set/delete + 表 API）。"""

    def __init__(self):
        self._kv: dict = {}
        self._tables: dict[str, list] = {}
        self._seq: dict[str, int] = {}

    def get(self, key, default=None):
        return self._kv.get(key, default)

    def set(self, key, value):
        self._kv[key] = value

    def delete(self, key):
        self._kv.pop(key, None)

    def HasTable(self, name):
        return name in self._tables

    def CreateTable(self, name, schema):
        self._tables.setdefault(name, [])

    def Table(self, name):
        return _TableHandle(self._tables.setdefault(name, []), self._seq, name)


class _TableHandle:
    def __init__(self, rows, seq, name):
        self._rows = rows
        self._seq = seq
        self._name = name
        self._cols = ()
        self._where = None

    def Insert(self, row: dict):
        self._seq[self._name] = self._seq.get(self._name, 0) + 1
        row = dict(row)
        row.setdefault("id", self._seq[self._name])
        self._rows.append(row)
        return self

    def Select(self, *cols):
        handle = _TableHandle(self._rows, self._seq, self._name)
        handle._rows = self._rows
        handle._cols = cols
        return handle

    def ToDict(self):
        self._as_dict = True
        return self

    def Where(self, clause, *params):
        self._where = (clause, params)
        return self

    def OrderBy(self, col, desc=False):
        self._order = ("desc" if desc else "asc", col)
        return self

    def Limit(self, n):
        self._limit = n
        return self

    def Delete(self):
        handle = _TableHandle(self._rows, self._seq, self._name)
        handle._rows = self._rows
        handle._delete = True
        return handle

    def Execute(self):
        if getattr(self, "_delete", False):
            if self._where:
                clause, params = self._where
                self._rows[:] = [r for r in self._rows if not _match(r, clause, params)]
            else:
                self._rows.clear()
            return
        rows = self._rows
        if self._where:
            clause, params = self._where
            rows = [r for r in rows if _match(r, clause, params)]
        if getattr(self, "_order", None):
            direction, col = self._order
            rows = sorted(rows, key=lambda r: r.get(col, 0), reverse=(direction == "desc"))
        limit = getattr(self, "_limit", None)
        if limit is not None:
            rows = rows[:limit]
        if self._cols and "*" not in self._cols:
            rows = [{c: r.get(c) for c in self._cols} for r in rows]
        return [dict(r) for r in rows]


def _match(row, clause, params):
    """极简 SQL where 匹配（覆盖测试用到的 = / > / AND 形态）。"""
    import re

    parts = re.split(r"\s+AND\s+", clause, flags=re.IGNORECASE)
    values = list(params)
    result = True
    used = 0
    for part in parts:
        m = re.match(r"(\w+)\s*(=|>|<)\s*\?", part.strip())
        if m:
            col, op = m.group(1), m.group(2)
            value = values[used]
            used += 1
            actual = row.get(col)
            if op == "=":
                result = result and actual == value
            elif op == ">":
                result = result and (actual or 0) > value
            elif op == "<":
                result = result and (actual or 0) < value
        else:
            m2 = re.match(r"(\w+)\s*(=|>|<)\s*(\S+)", part.strip())
            if m2:
                col, op, literal = m2.group(1), m2.group(2), m2.group(3).strip("'\"")
                actual = row.get(col)
                if op == "=":
                    result = result and str(actual) == literal
    return result


class FakeConfigManager:
    def __init__(self):
        self.sets = []

    def getConfig(self, section):
        return None

    def setConfig(self, section, data, **_):
        self.sets.append((section, data))


class FakeLogger:
    def debug(self, *a, **k):
        pass

    info = warning = error = debug


class FakeDashboard:
    """宿主 Dashboard 视窗注册与令牌校验替身。"""

    def __init__(self):
        self.views = {}
        self.tokens = {"host-token"}

    def register_view(self, **kwargs):
        self.views[kwargs.get("id")] = kwargs
        return True

    def unregister_view(self, view_id):
        self.views.pop(view_id, None)
        return True

    def verify_token(self, token):
        return token in self.tokens

    def verify_request(self, request):
        return False


class FakeSDK:
    def __init__(self):
        self.storage = FakeStorage()
        self.config = FakeConfigManager()
        self.logger = FakeLogger()
        self.cron = FakeCron()
        self.Cron = self.cron
        self.adapter = FakeAdapterManager()
        self.Dashboard = FakeDashboard()
        self.router = FakeRouter()


class FakeCron:
    def __init__(self):
        self.handlers = []
        self.tasks = []

    def on_trigger(self, handler):
        self.handlers.append(handler)

    def list_tasks(self, source=""):
        return []

    def interval(self, seconds, source="", data=None):
        self.tasks.append({"seconds": seconds, "source": source, "data": data})


class FakeAdapterManager:
    def __init__(self):
        self.sent = []

    def list_running(self):
        return ["onebot11"]

    def get(self, name):
        manager = self

        class _Adapter:
            class Send:
                @staticmethod
                def To(target_type, target_id):
                    return _Chain()

            Send = Send()

        class _Chain:
            async def Text(self, text):
                manager.sent.append((name, text))

        return _Adapter()


class FakeRouter:
    def __init__(self):
        self.http_routes = []
        self.ws_routes = []

    def register_http_route(self, module, path, handler, methods=None, **_):
        self.http_routes.append((module, path, handler, methods))

    def unregister_http_route(self, module, path):
        self.http_routes = [r for r in self.http_routes if r[1] != path]

    def register_websocket(self, module, path, handler=None, auth_handler=None, **_):
        self.ws_routes.append((module, path, handler, auth_handler))

    def unregister_websocket(self, module, path):
        self.ws_routes = [r for r in self.ws_routes if r[1] != path]


def make_main(**cfg_overrides) -> Main:
    """无 SSH 依赖的 Main（机器注册表/审计/安全闸可用，连接类操作需 mock）。"""
    main = Main()
    main.sdk = FakeSDK()
    main.logger = main.sdk.logger
    main.fleet = __import__("MyServer.fleet", fromlist=["Fleet"]).Fleet(main.sdk.storage)
    main.audit = __import__("MyServer.audit", fromlist=["AuditLog"]).AuditLog(main.sdk.storage)
    cfg = MyServerConfig()
    for key, value in cfg_overrides.items():
        setattr(cfg, key, value)
    main._cfg = cfg
    main.sessions.max_sessions = cfg.max_sessions
    main.sessions.prefer_tmux = cfg.prefer_tmux
    return main
