"""Dashboard 集成：视窗注册、路由、双令牌鉴权、WS 终端。"""

from __future__ import annotations

import asyncio
import json
import shlex
import secrets
import time
from typing import Any

try:
    from fastapi import Request, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse, JSONResponse, Response
except Exception:  # pragma: no cover - 测试环境兜底
    Request = WebSocket = WebSocketDisconnect = object  # type: ignore[assignment, misc]
    HTMLResponse = JSONResponse = Response = None  # type: ignore[assignment, misc]

from .. import texts
from .page import public_html, view_html

VIEW_ID = "MyServer"
OWN_TOKEN_KEY = "MyServer:auth_token"
_GEO_CACHE: dict[str, tuple[float, str]] = {}

# 公开页可配置的字段（public_fields 白名单）
PUBLIC_FIELD_KEYS = ("cpu", "mem", "disk", "load", "uptime", "events")
VIEW_TITLES = {
    "zh": "MyServer",
    "zh-TW": "MyServer",
    "en": "MyServer",
    "ja": "MyServer",
    "ru": "MyServer",
}
ICON_SVG = (
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"'
    ' stroke-width="1.6"><rect x="3" y="4" width="18" height="7" rx="2"/>'
    '<rect x="3" y="13" width="18" height="7" rx="2"/>'
    '<circle cx="7.2" cy="7.5" r="1" fill="currentColor" stroke="none"/>'
    '<circle cx="7.2" cy="16.5" r="1" fill="currentColor" stroke="none"/></svg>'
)

STATIC_FILES = {
    "vendor/xterm.js": ("application/javascript", "vendor/xterm.js"),
    "vendor/xterm.css": ("text/css", "vendor/xterm.css"),
    "vendor/fit.js": ("application/javascript", "vendor/fit.js"),
    "app.css": ("text/css", "app.css"),
    "app.js": ("application/javascript", "app.js"),
    "ui.js": ("application/javascript", "ui.js"),
    "public.css": ("text/css", "public.css"),
    "public.js": ("application/javascript", "public.js"),
}


class DashboardIntegration:
    """控制台装配（setup/teardown 成对）。"""

    def __init__(self, main):
        self.main = main
        self.logger = main.logger

    def _host(self):
        """{!--< internal-use >!--} 宿主 Dashboard 服务。"""
        return getattr(getattr(self.main, "sdk", None), "Dashboard", None)

    def _router(self):
        """{!--< internal-use >!--} 框架路由。"""
        return getattr(getattr(self.main, "sdk", None), "router", None)

    def _own_token(self) -> str:
        """{!--< internal-use >!--} 自管令牌（storage 持久化）。"""
        storage = self.main.sdk.storage
        token = storage.get(OWN_TOKEN_KEY)
        if not token:
            token = secrets.token_urlsafe(24)
            storage.set(OWN_TOKEN_KEY, token)
            self.logger.warning(f"MyServer dashboard token generated: {token[:6]}…（完整值在 storage/{OWN_TOKEN_KEY}）")
        return token

    def _extract_token(self, request) -> str:
        """{!--< internal-use >!--} Bearer 头优先，?token= 兜底。"""
        try:
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                return auth[7:].strip()
            return str(request.query_params.get("token", ""))
        except Exception:
            return ""

    def _authorized(self, request) -> bool:
        """{!--< internal-use >!--} 宿主令牌优先，自管令牌兜底。"""
        provided = self._extract_token(request)
        if not provided:
            return False
        host = self._host()
        if host is not None:
            try:
                if host.verify_request(request):
                    return True
                if host.verify_token(provided):
                    return True
            except Exception:
                pass
        return secrets.compare_digest(provided, self._own_token())

    def _guard(self, handler):
        """{!--< internal-use >!--} 鉴权包装。"""

        async def wrapped(request):
            if not self._authorized(request):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            return await handler(request)

        return wrapped

    # ==================== 装配 ====================

    def setup(self) -> bool:
        """
        注册视窗与全部路由。

        :return: [bool] 宿主在位且装配成功
        """
        host = self._host()
        router = self._router()
        if host is None or router is None:
            return False
        try:
            host.register_view(
                id=VIEW_ID,
                title=VIEW_TITLES["zh"],
                titles=VIEW_TITLES,
                icon_svg=ICON_SVG,
                iframe_url="/MyServer/app",
                group="qvq",
                group_title="QvQ 生态",
                group_title_en="QvQ Ecosystem",
            )
        except Exception as e:
            self.logger.warning(f"register_view failed: {e}")
            return False

        routes = [
            ("/app", self._page, ["GET"], False),
            ("/public", self._public_page, ["GET"], False),
            ("/res/app.css", self._static("app.css"), ["GET"], False),
            ("/res/app.js", self._static("app.js"), ["GET"], False),
            ("/res/ui.js", self._static("ui.js"), ["GET"], False),
            ("/res/vendor/xterm.js", self._static("vendor/xterm.js"), ["GET"], False),
            ("/res/vendor/xterm.css", self._static("vendor/xterm.css"), ["GET"], False),
            ("/res/vendor/fit.js", self._static("vendor/fit.js"), ["GET"], False),
            ("/res/public.css", self._static("public.css"), ["GET"], False),
            ("/res/public.js", self._static("public.js"), ["GET"], False),
            ("/api/public/overview", self._api_public_overview, ["GET"], False),
            ("/api/overview", self._api_overview, ["GET"], True),
            ("/api/machines", self._api_machines, ["GET"], True),
            ("/api/machines", self._api_machine_add, ["POST"], True),
            ("/api/machines/{name}", self._api_machine_update, ["PUT"], True),
            ("/api/machines/{name}", self._api_machine_delete, ["DELETE"], True),
            ("/api/status/{name}", self._api_status, ["GET"], True),
            ("/api/check/{name}", self._api_check, ["POST"], True),
            ("/api/exec", self._api_exec, ["POST"], True),
            ("/api/confirm", self._api_confirm, ["POST"], True),
            ("/api/alerts", self._api_alerts, ["GET"], True),
            ("/api/metrics", self._api_metrics, ["GET"], True),
            ("/api/files", self._api_files, ["GET"], True),
            ("/api/files/upload", self._api_files_upload, ["POST"], True),
            ("/api/files/fetch", self._api_files_fetch, ["POST"], True),
            ("/api/files/read", self._api_files_read, ["POST"], True),
            ("/api/files/write", self._api_files_write, ["POST"], True),
            ("/api/files/mkdir", self._api_files_mkdir, ["POST"], True),
            ("/api/files/delete", self._api_files_delete, ["POST"], True),
            ("/api/files/rename", self._api_files_rename, ["POST"], True),
            ("/api/sessions", self._api_sessions, ["GET"], True),
            ("/api/sessions/close", self._api_sessions_close, ["POST"], True),
            ("/api/history", self._api_history, ["GET"], True),
            ("/api/config", self._api_config_get, ["GET"], True),
            ("/api/config", self._api_config_save, ["POST"], True),
        ]
        for path, handler, methods, guarded in routes:
            try:
                router.register_http_route("MyServer", path,
                                           self._guard(handler) if guarded else handler,
                                           methods=methods)
            except Exception as e:
                self.logger.warning(f"route {path} failed: {e}")
        try:
            router.register_websocket("MyServer", "/ws/terminal",
                                      handler=self._ws_terminal,
                                      auth_handler=self._ws_auth)
        except Exception as e:
            self.logger.warning(f"ws route failed: {e}")
        return True

    def teardown(self) -> None:
        """反注册视窗与路由（宿主持久化注册表，on_unload 必须调用）。"""
        router = self._router()
        if router is not None:
            routes_teardown = [
                ("/app",), ("/public",),
                ("/res/app.css",), ("/res/app.js",), ("/res/ui.js",),
                ("/res/vendor/xterm.js",), ("/res/vendor/xterm.css",), ("/res/vendor/fit.js",),
                ("/res/public.css",), ("/res/public.js",),
                ("/api/public/overview",),
                ("/api/overview",),
                ("/api/machines",),
                ("/api/machines/{name}",),
                ("/api/status/{name}",),
                ("/api/check/{name}",),
                ("/api/exec",),
                ("/api/confirm",),
                ("/api/alerts",),
                ("/api/metrics",),
                ("/api/files",),
                ("/api/files/upload",),
                ("/api/files/fetch",),
                ("/api/files/read",),
                ("/api/files/write",),
                ("/api/files/mkdir",),
                ("/api/files/delete",),
                ("/api/files/rename",),
                ("/api/sessions",),
                ("/api/sessions/close",),
                ("/api/history",),
                ("/api/config",),
            ]
            for (path,) in routes_teardown:
                try:
                    router.unregister_http_route("MyServer", path)
                except Exception:
                    pass
            try:
                router.unregister_websocket("MyServer", "/ws/terminal")
            except Exception:
                pass
        host = self._host()
        if host is not None:
            try:
                host.unregister_view(VIEW_ID)
            except Exception:
                pass

    # ==================== 页面与静态资源 ====================

    async def _page(self, request):
        """{!--< internal-use >!--} 控制台整页。"""
        return HTMLResponse(view_html())

    async def _public_page(self, request):
        """{!--< internal-use >!--} 公开状态页（开关关闭返回 404）。"""
        if not bool(self.main.cfg.public_page):
            return JSONResponse({"error": "not found"}, status_code=404)
        return HTMLResponse(public_html())

    async def _api_public_overview(self, request):
        """{!--< internal-use >!--} 公开页数据：只读监控缓存，不触发 SSH 探测。"""
        if not bool(self.main.cfg.public_page):
            return JSONResponse({"error": "not found"}, status_code=404)
        cfg = self.main.cfg
        show_host = bool(cfg.public_show_host)
        points = max(5, min(int(cfg.public_history_points or 40), 200))
        fields = [f for f in (cfg.public_fields or []) if f in PUBLIC_FIELD_KEYS]
        show = lambda key: key in fields  # noqa: E731
        machines = []
        for m in self.main.fleet.all():
            cached = self.main.fleet.status(m["name"])
            metrics = cached.get("metrics") or {}
            from ..ssh import summary_line as _summary_line

            item = {
                "name": m["name"],
                "group": m.get("group", ""),
                "online": bool(cached.get("online", False)),
                "checked_at": cached.get("checked_at", 0),
                "summary": _summary_line(metrics) if metrics else "",
            }
            if show("cpu"):
                item["cpu"] = metrics.get("cpu_percent")
            if show("mem"):
                item["mem"] = metrics.get("mem_percent")
                item["mem_text"] = (
                    f"{metrics.get('mem_used_text', '')}/{metrics.get('mem_total_text', '')}".strip("/")
                    if metrics.get("mem_total_text") else ""
                )
            if show("disk"):
                item["disk"] = metrics.get("disk_percent")
                item["disk_text"] = (
                    f"{metrics.get('disk_used_text', '')}/{metrics.get('disk_total_text', '')}".strip("/")
                    if metrics.get("disk_total_text") else ""
                )
            if show("load"):
                item["load1"] = metrics.get("load1")
            if show("uptime"):
                item["uptime_s"] = metrics.get("uptime_s")
            if show_host:
                from ..utils import mask_ip

                item["host"] = mask_ip(m.get("ip", ""))
            if bool(cfg.public_geo):
                item["country_code"] = await self._country_code_of(str(m.get("ip") or ""))
            machines.append(item)
        alerts = [
            {"machine": a.get("machine_name"), "type": a.get("alert_type"),
             "time": a.get("timestamp")}
            for a in self.main.monitor.recent_alerts(10)
        ] if show("events") else []
        return {
            "title": str(cfg.public_title or "Server Status"),
            "refresh": int(cfg.public_refresh_seconds),
            "fields": fields,
            "points": points,
            "stats": {
                "total": len(machines),
                "online": sum(1 for m in machines if m["online"]),
            },
            "machines": machines,
            "alerts": alerts,
        }

    async def _country_code_of(self, ip: str) -> str:
        """{!--< internal-use >!--} IP 国家码查询（外部接口，24 小时内存缓存；失败返回空）。"""
        ip = str(ip or "").strip()
        if not ip or ip.startswith(("127.", "10.", "192.168.", "172.")) \
                or (ip.startswith("[") and "]" in ip):
            return ""
        hit = _GEO_CACHE.get(ip)
        now = time.time()
        if hit and now - hit[0] < 86400:
            return hit[1]
        code = ""
        try:
            def fetch() -> str:
                import urllib.request

                with urllib.request.urlopen(
                        f"https://ipapi.co/{ip}/country_code/", timeout=3) as response:
                    return response.read().decode("utf-8", "ignore").strip().upper()

            candidate = await asyncio.to_thread(fetch)
            if len(candidate) == 2 and candidate.isalpha():
                code = candidate
        except Exception:
            code = ""
        _GEO_CACHE[ip] = (now, code)
        return code

    def _static(self, name: str):
        """{!--< internal-use >!--} 静态字节代理。"""
        mime, rel = STATIC_FILES[name]

        async def handler(request):
            from importlib import resources

            try:
                data = resources.files("MyServer.dashboard").joinpath(f"static/{rel}").read_bytes()
            except Exception:
                return JSONResponse({"error": "not found"}, status_code=404)
            return Response(data, media_type=mime,
                            headers={"Cache-Control": "max-age=3600"})

        return handler

    # ==================== 数据 API ====================

    async def _api_overview(self, request):
        """{!--< internal-use >!--} 概览聚合；缓存过期时现场补采一次。"""
        await self._refresh_stale()
        stats = self.main.fleet.stats()
        machines = self.main.fleet.all()
        for m in machines:
            cached = self.main.fleet.status(m["name"])
            m["metrics"] = cached.get("metrics") or {}
            m["status"] = {"error": cached.get("error", "")}
            m["specs"] = cached.get("specs") or m.get("specs") or {}
        return {
            "stats": stats,
            "machines": machines,
            "alerts": self.main.monitor.recent_alerts(10),
            "sessions": self.main.sessions.list(),
            "pending_confirms": self.main.gate.pending_count,
        }

    async def _refresh_stale(self) -> None:
        """{!--< internal-use >!--} 缓存过期时补采：从未采集过的现场等到结果，其余后台刷新。"""
        interval = max(5, int(self.main.cfg.check_interval))
        now = time.time()
        never: list[dict] = []
        stale: list[dict] = []
        for machine in self.main.fleet.all(include_secrets=True):
            checked = float(self.main.fleet.status(machine["name"]).get("checked_at") or 0)
            if now - checked <= interval:
                continue
            (never if not checked else stale).append(machine)
        if never:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*(self.main.monitor.check_one(m) for m in never),
                                   return_exceptions=True),
                    timeout=6,
                )
            except Exception:
                pass
        if stale:
            self.main.spawn(self._check_many(stale))

    async def _check_many(self, machines: list[dict]) -> None:
        """{!--< internal-use >!--} 后台批量补采（异常逐台吞掉）。"""
        await asyncio.gather(*(self.main.monitor.check_one(m) for m in machines),
                             return_exceptions=True)

    async def _api_machines(self, request):
        """{!--< internal-use >!--} 机器清单（已剥凭据）。"""
        return {"machines": self.main.fleet.all()}

    async def _api_machine_add(self, request):
        """{!--< internal-use >!--} 新增机器并测连。"""
        body = await _json(request)
        machine = _machine_from_body(body)
        if machine is None:
            return JSONResponse({"error": "name/ip/username required"}, status_code=400)
        if self.main.fleet.get(machine["name"]) is not None:
            return JSONResponse({"error": f"name taken: {machine['name']}"}, status_code=409)
        self.main.fleet.save(machine)
        ok, error = await self.main.test_connection(machine)
        if not ok:
            self.main.fleet.delete(machine["name"])
            return JSONResponse({"error": f"connection failed: {error}"}, status_code=400)
        specs = await self.main.probe_specs(machine)
        return {"ok": True, "machine": self.main.fleet.redact(machine), "specs": specs}

    async def _api_machine_update(self, request):
        """{!--< internal-use >!--} 更新机器。"""
        name = request.path_params.get("name", "")
        current = self.main.fleet.get(name)
        if current is None:
            return JSONResponse({"error": "machine not found"}, status_code=404)
        body = await _json(request)
        updates = _machine_from_body(body, base=current)
        if updates is None:
            return JSONResponse({"error": "invalid body"}, status_code=400)
        updates["name"] = name
        self.main.fleet.save(updates)
        return {"ok": True}

    async def _api_machine_delete(self, request):
        """{!--< internal-use >!--} 删除机器。"""
        name = request.path_params.get("name", "")
        removed = self.main.fleet.delete(name)
        return {"ok": removed}

    async def _api_status(self, request):
        """{!--< internal-use >!--} 实时状态。"""
        name = request.path_params.get("name", "")
        return await self.main.ops.status(name)

    async def _api_check(self, request):
        """{!--< internal-use >!--} 立即检测一次（监控页「检测」按钮）。"""
        name = request.path_params.get("name", "")
        machine = self.main.fleet.get(name)
        if machine is None:
            return JSONResponse({"ok": False, "error": "machine not found"}, status_code=404)
        return await self.main.monitor.check_one(machine)

    async def _api_exec(self, request):
        """{!--< internal-use >!--} 执行命令（危险命令返回确认要求）。"""
        body = await _json(request)
        result = await self.main.ops.exec(str(body.get("name", "")),
                                          str(body.get("command", "")),
                                          actor="dashboard",
                                          timeout=int(body.get("timeout") or 0) or None)
        return result

    async def _api_confirm(self, request):
        """{!--< internal-use >!--} 确认执行。"""
        body = await _json(request)
        name = str(body.get("name", ""))
        command = self.main.gate.consume(name, str(body.get("token", "")))
        if command is None:
            return JSONResponse({"ok": False, "error": "token invalid or expired"}, status_code=400)
        result = await self.main.ops.exec(name, command, actor="dashboard:confirmed",
                                          confirmed=True)
        return result

    async def _api_alerts(self, request):
        """{!--< internal-use >!--} 最近告警。"""
        limit = int(request.query_params.get("limit", 50))
        return {"alerts": self.main.monitor.recent_alerts(limit)}

    async def _api_metrics(self, request):
        """{!--< internal-use >!--} 指标历史。"""
        machine = request.query_params.get("machine", "")
        metric = request.query_params.get("metric", "cpu_percent")
        hours = int(request.query_params.get("hours", 24))
        points = self.main.monitor.get_metrics(machine, metric, hours)
        return {"points": points}

    async def _api_files(self, request):
        """{!--< internal-use >!--} 远端目录列表。"""
        machine = request.query_params.get("machine", "")
        path = request.query_params.get("path", ".")
        try:
            entries = await self.main.files_ops.list_dir(machine, path)
            return {"ok": True, "path": path, "entries": entries}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    async def _api_files_upload(self, request):
        """{!--< internal-use >!--} base64 内容上传（浏览器读文件转 b64）。"""
        body = await _json(request)
        import base64
        import os
        import tempfile

        raw = str(body.get("content_b64", ""))
        if not raw:
            return JSONResponse({"error": "content_b64 required"}, status_code=400)
        fd, local_path = tempfile.mkstemp(prefix="myserver_up_")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(base64.b64decode(raw))
            info = await self.main.files_ops.upload(str(body.get("name", "")), local_path,
                                                    str(body.get("remote_path", "")),
                                                    actor="dashboard")
            return {"ok": True, **info}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        finally:
            try:
                os.unlink(local_path)
            except Exception:
                pass

    async def _api_files_fetch(self, request):
        """{!--< internal-use >!--} 远端文件内容回传（base64，浏览器保存）。"""
        body = await _json(request)
        import base64
        import os
        import tempfile

        fd, local_path = tempfile.mkstemp(prefix="myserver_dl_")
        try:
            await self.main.files_ops.download(str(body.get("name", "")),
                                               str(body.get("remote_path", "")),
                                               local_path, actor="dashboard")
            with open(local_path, "rb") as f:
                data = f.read()
            return {"ok": True, "content_b64": base64.b64encode(data).decode(),
                    "size": len(data)}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        finally:
            try:
                os.unlink(local_path)
            except Exception:
                pass

    async def _api_files_read(self, request):
        """{!--< internal-use >!--} 读取远端文本文件（在线编辑）。"""
        body = await _json(request)
        try:
            text = await self.main.files_ops.read_file(str(body.get("name", "")),
                                                       str(body.get("path", "")),
                                                       actor="dashboard")
            return {"ok": True, "path": body.get("path"), "text": text}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    async def _api_files_write(self, request):
        """{!--< internal-use >!--} 写回远端文本文件。"""
        body = await _json(request)
        try:
            info = await self.main.files_ops.write_file(str(body.get("name", "")),
                                                        str(body.get("path", "")),
                                                        str(body.get("text", "")),
                                                        actor="dashboard")
            return {"ok": True, **info}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    async def _api_files_mkdir(self, request):
        """{!--< internal-use >!--} 新建目录。"""
        body = await _json(request)
        parent = str(body.get("path", "")).rstrip("/") or "/"
        target = f"{parent}/{str(body.get('name', '')).strip()}"
        try:
            await self.main.files_ops.mkdir(str(body.get("machine", "")), target,
                                            actor="dashboard")
            return {"ok": True}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    async def _api_files_delete(self, request):
        """{!--< internal-use >!--} 删除文件/目录。"""
        body = await _json(request)
        try:
            await self.main.files_ops.delete(str(body.get("machine", "")),
                                             str(body.get("path", "")),
                                             bool(body.get("is_dir")),
                                             actor="dashboard")
            return {"ok": True}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    async def _api_files_rename(self, request):
        """{!--< internal-use >!--} 重命名（同目录内）。"""
        body = await _json(request)
        parent = str(body.get("path", "")).rsplit("/", 1)[0] or "/"
        old_name = str(body.get("path", "")).rsplit("/", 1)[-1]
        new_name = str(body.get("name", "")).strip()
        if not new_name or "/" in new_name:
            return JSONResponse({"ok": False, "error": "invalid name"}, status_code=400)
        try:
            await self.main.files_ops.rename(str(body.get("machine", "")),
                                             old_name and f"{parent}/{old_name}",
                                             f"{parent}/{new_name}",
                                             actor="dashboard")
            return {"ok": True}
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    async def _api_sessions(self, request):
        """{!--< internal-use >!--} 会话清单。"""
        return {"sessions": self.main.sessions.list()}

    async def _api_sessions_close(self, request):
        """{!--< internal-use >!--} 关闭会话。"""
        body = await _json(request)
        closed = await self.main.sessions.close(str(body.get("name", "")),
                                                str(body.get("session", "")))
        return {"ok": closed}

    async def _api_history(self, request):
        """{!--< internal-use >!--} 审计清单。"""
        machine = request.query_params.get("machine", "")
        limit = int(request.query_params.get("limit", 50))
        return {"items": self.main.audit.tail(machine, limit)}

    # ---- 设置 ----

    # 控制台可编辑的字段白名单（类型在 _coerce_config_value 里收口）
    CONFIG_FIELDS: dict[str, type] = {
        "exec_timeout": int, "max_sessions": int, "allow_paste_keys": bool,
        "prefer_tmux": bool, "check_interval": int, "monitor_enabled": bool,
        "alert_cooldown_min": int, "history_retention_days": int,
        "expiry_remind_days": int,
        "cpu_threshold": int, "mem_threshold": int, "disk_threshold": int,
        "load_factor": float, "transfer_max_mb": int,
        "public_page": bool, "public_title": str, "public_show_host": bool,
        "public_refresh_seconds": int, "public_history_points": int, "public_geo": bool,
        "public_fields": list,
    }

    async def _api_config_get(self, request):
        """{!--< internal-use >!--} 当前配置（白名单字段）。"""
        cfg = self.main.cfg
        return {key: getattr(cfg, key) for key in self.CONFIG_FIELDS}

    async def _api_config_save(self, request):
        """{!--< internal-use >!--} 保存配置：白名单收口 → sdk.config → 热更新内存。"""
        body = await _json(request)
        cfg = self.main.cfg
        updates: dict = {}
        for key, field_type in self.CONFIG_FIELDS.items():
            if key not in body:
                continue
            try:
                updates[key] = _coerce_value(body[key], field_type)
            except (TypeError, ValueError):
                return JSONResponse({"error": f"invalid value for {key}"}, status_code=400)
        if not updates:
            return {"ok": True, "updated": 0}
        try:
            current = self.main.sdk.config.getConfig("MyServer") or {}
        except Exception:
            current = {}
        if not isinstance(current, dict):
            current = {}
        current.update(updates)
        try:
            self.main.sdk.config.setConfig("MyServer", current)
        except Exception as e:
            return JSONResponse({"error": f"persist failed: {e}"}, status_code=500)
        for key, value in updates.items():
            setattr(cfg, key, value)
        self.main.sessions.max_sessions = max(1, int(cfg.max_sessions))
        self.main.sessions.prefer_tmux = bool(cfg.prefer_tmux)
        self.main.audit.record("", "dashboard", "config_save",
                               ",".join(sorted(updates)))
        return {"ok": True, "updated": len(updates)}

    # ==================== WS 终端 ====================

    async def _ws_auth(self, websocket) -> bool:
        """{!--< internal-use >!--} WS 鉴权：宿主令牌或自管令牌。"""
        try:
            token = str(websocket.query_params.get("token", ""))
            machine = str(websocket.query_params.get("machine", ""))
            if not token or not machine:
                return False
            if self.main.fleet.get(machine) is None:
                return False
            host = self._host()
            if host is not None:
                try:
                    if host.verify_token(token):
                        return True
                except Exception:
                    pass
            return secrets.compare_digest(token, self._own_token())
        except Exception:
            return False

    async def _ws_terminal(self, websocket):
        """{!--< internal-use >!--} 终端主循环：独立 SSH 进程 attach tmux 会话。"""
        machine_name = str(websocket.query_params.get("machine", ""))
        session_name = str(websocket.query_params.get("session", "main"))
        machine = self.main.fleet.get(machine_name)
        if machine is None:
            await websocket.close(code=4404)
            return
        from ..utils import safe_session_name
        from ..sessions import INSTALL_TMUX_CMD

        tmux_name = f"myserver_{safe_session_name(session_name)}"
        client = self.main.make_client(machine)
        process = None
        read_task = None
        try:
            await client.connect()
            probe = await client.exec_command("command -v tmux", timeout=5)
            has_tmux = probe.get("exit_code") == 0
            if not has_tmux:
                # 询问是否安装（前端弹确认，默认安装；90 秒未答复按跳过）
                await websocket.send_text(json.dumps({"mstype": "confirm"}, ensure_ascii=False))
                decision = "skip"
                try:
                    while True:
                        message = await asyncio.wait_for(websocket.receive_text(), timeout=90)
                        if not message.startswith('{"mstype"'):
                            continue
                        if '"install_tmux"' in message:
                            decision = "install"
                            break
                        if '"skip"' in message:
                            break
                except asyncio.TimeoutError:
                    pass
                if decision == "install":
                    await websocket.send_text(json.dumps(
                        {"mstype": "log", "text": texts.t("tmux_installing")}, ensure_ascii=False))
                    install = await client.exec_command(INSTALL_TMUX_CMD, timeout=300)
                    ok = install.get("exit_code") == 0
                    tail = (install.get("stderr") or install.get("stdout") or "")[-400:]
                    await websocket.send_text(json.dumps(
                        {"mstype": "log",
                         "text": texts.t("tmux_install_ok") if ok
                         else texts.t("tmux_install_failed", error=tail)},
                        ensure_ascii=False))
                    probe = await client.exec_command("command -v tmux", timeout=5)
                    has_tmux = probe.get("exit_code") == 0
            if has_tmux:
                # status off：隐藏 tmux 底部状态条
                command = f"tmux new -A -s {shlex.quote(tmux_name)} \\; set-option status off"
            else:
                command = "bash -l"
                await websocket.send_text(json.dumps(
                    {"mstype": "log", "text": texts.t("tmux_unavailable")}, ensure_ascii=False))
            process = await client._conn.create_process(
                command, term_type="xterm-256color", term_size=(120, 30))

            async def pump():
                """{!--< internal-use >!--} 远端输出 → WS。"""
                try:
                    while True:
                        data = await process.stdout.read(4096)
                        if not data:
                            break
                        await websocket.send_text(data)
                except Exception:
                    pass

            read_task = asyncio.ensure_future(pump())
            self.main.audit.record(machine_name, "dashboard", "terminal_attach", tmux_name)
            while True:
                message = await websocket.receive_text()
                if message.startswith('{"type":"resize"'):
                    import json as _json

                    try:
                        size = _json.loads(message)
                        await process.change_terminal_size(
                            max(2, int(size.get("cols", 120))), max(2, int(size.get("rows", 30))))
                    except Exception:
                        pass
                    continue
                if process.stdin:
                    process.stdin.write(message)
                    await process.stdin.drain()
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            if read_task is not None:
                read_task.cancel()
            if process is not None:
                try:
                    process.terminate()
                except Exception:
                    pass
            await client.close()
            self.main.audit.record(machine_name, "dashboard", "terminal_detach", tmux_name)


async def _json(request) -> dict:
    """{!--< internal-use >!--} 请求体 JSON 解析。"""
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _coerce_value(value, field_type: type):
    """{!--< internal-use >!--} 配置值类型收口。"""
    if field_type is bool:
        if isinstance(value, bool):
            return value
        raise ValueError("expected bool")
    if field_type is list:
        if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
            raise ValueError("expected list of strings")
        cleaned = [v for v in value if v in PUBLIC_FIELD_KEYS]
        return list(dict.fromkeys(cleaned))
    if field_type is int:
        return int(value)
    if field_type is float:
        return float(value)
    return str(value)


def _machine_from_body(body: dict, base: dict | None = None) -> dict | None:
    """{!--< internal-use >!--} 请求体 → 机器字典；base 提供增量更新底稿。"""
    machine: dict[str, Any] = dict(base or {})
    for key in ("name", "ip", "port", "username", "auth_type", "password",
                "private_key", "key_path", "group", "tags", "notes", "expiry"):
        if key in body and body[key] not in (None, ""):
            machine[key] = body[key]
    if base is None:
        machine.setdefault("port", 22)
        machine.setdefault("username", "root")
        machine.setdefault("auth_type", "password")
    if not str(machine.get("name") or "").strip() or not str(machine.get("ip") or "").strip():
        return None
    if machine.get("auth_type") not in ("password", "key"):
        machine["auth_type"] = "password"
    tags = machine.get("tags")
    if isinstance(tags, str):
        machine["tags"] = [t.strip() for t in tags.split(",") if t.strip()]
    return machine
