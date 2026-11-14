"""Dashboard 集成：鉴权、路由注册/反注册、页面拼装、公开页开关。"""

from MyServer.dashboard import DashboardIntegration
from MyServer.dashboard.page import public_html, view_html


def _dash(main):
    return DashboardIntegration(main)


def test_setup_registers_routes_and_teardown_cleans(main):
    dash = _dash(main)
    assert dash.setup() is True
    paths = [r[1] for r in main.sdk.router.http_routes]
    assert "/app" in paths and "/api/overview" in paths and "/public" in paths
    assert main.sdk.router.ws_routes and main.sdk.router.ws_routes[0][1] == "/ws/terminal"
    assert main.sdk.Dashboard.views.get("MyServer")
    dash.teardown()
    assert main.sdk.router.http_routes == []
    assert main.sdk.router.ws_routes == []
    assert "MyServer" not in main.sdk.Dashboard.views


def test_setup_without_host_returns_false():
    from fakes import make_main

    main = make_main()
    main.sdk.router = None
    assert _dash(main).setup() is False


def test_view_html_assembles_static():
    import re

    html = view_html()
    assert "MyServer" in html
    assert "ms-glow ms-glow-a" in html
    # CSS/JS 已内联（占位符消失）
    assert "/*__I18N_JS__*/" not in html
    assert "/*__APP_CSS__*/" not in html
    assert "/*__APP_JS__*/" not in html
    assert ".ms-card" in html
    # 侧边栏布局 + 设置页 + 组件库（xterm 按需懒加载，不在首屏阻塞）
    assert "ms-sidebar" in html
    assert 'id="tab-settings"' in html
    assert "window.MS" in html
    assert "ensureXterm" in html
    # JS 直取的所有 DOM id 必须在页面里存在（防止启动即 null 崩溃）；取最后一个 script 块（app.js）
    # term-session / files-path 由 MS.input 动态创建后挂载，不在静态 HTML
    ids = set(re.findall(r'\$\("([a-zA-Z][\w-]*)"\)', html.split("<script>\n")[-1]))
    missing = [i for i in sorted(ids)
               if f'id="{i}"' not in html
               and not i.startswith(("cf-", "pf-", "mf-"))
               and i not in ("term-session", "files-path")]
    assert missing == [], missing


async def test_config_roundtrip(main):
    dash = _dash(main)
    dash.setup()
    current = await dash._api_config_get(None)
    assert current["check_interval"] == main.cfg.check_interval

    class FakeRequest:
        async def json(self):
            return {"check_interval": 120, "public_page": True, "cpu_threshold": "85"}

    result = await dash._api_config_save(FakeRequest())
    assert result["updated"] == 3
    assert main.cfg.check_interval == 120
    assert main.cfg.public_page is True
    assert main.cfg.cpu_threshold == 85
    # 持久化进框架配置
    stored = main.sdk.config.sets
    assert stored and stored[-1][0] == "MyServer"


async def test_config_rejects_bad_value(main):
    dash = _dash(main)

    class FakeRequest:
        async def json(self):
            return {"check_interval": "not-a-number"}


    result = await dash._api_config_save(FakeRequest())
    assert getattr(result, "status_code", None) == 400


def test_public_html_assembles_static():
    html = public_html()
    assert "api/public/overview" in html
    assert "/*__PUBLIC_CSS__*/" not in html
    assert "/*__PUBLIC_JS__*/" not in html


async def test_public_endpoint_disabled_returns_404(main):
    dash = _dash(main)
    assert main.cfg.public_page is False
    response = await dash._api_public_overview(None)
    assert response.status_code == 404


async def test_public_endpoint_enabled_returns_sanitized(main):
    _add = main.fleet.save({"name": "web-1", "ip": "1.2.3.4", "port": 22,
                            "username": "root", "auth_type": "password",
                            "password": "secret", "group": "web"})
    main.fleet.save_status("web-1", {"online": True, "metrics": {"cpu_percent": 11}})
    main._cfg.public_page = True
    dash = _dash(main)
    data = await dash._api_public_overview(None)
    assert data["stats"] == {"total": 1, "online": 1}
    machine = data["machines"][0]
    assert machine["name"] == "web-1"
    assert machine["cpu"] == 11
    # 默认不展示 host，永不展示凭据
    assert "host" not in machine
    assert "password" not in str(data)


async def test_public_endpoint_shows_masked_host(main):
    main.fleet.save({"name": "web-1", "ip": "1.2.3.4", "port": 22,
                     "username": "root", "auth_type": "password", "password": "x"})
    main.fleet.save_status("web-1", {"online": True, "metrics": {}})
    main._cfg.public_page = True
    main._cfg.public_show_host = True
    data = await _dash(main)._api_public_overview(None)
    assert data["machines"][0]["host"] == "1.2.****"


def test_own_token_persisted(main):
    dash = _dash(main)
    token = dash._own_token()
    assert token
    assert main.sdk.storage.get("MyServer:auth_token") == token
    assert dash._own_token() == token


async def test_guard_rejects_without_token(main):
    dash = _dash(main)
    dash.setup()

    class FakeRequest:
        headers = {}
        query_params = {}

    wrapped = dash._guard(dash._api_overview)
    response = await wrapped(FakeRequest())
    assert response.status_code == 401


async def test_guard_accepts_own_token(main):
    dash = _dash(main)
    main.fleet.save({"name": "web-1", "ip": "1.2.3.4", "username": "root"})
    token = dash._own_token()

    class FakeRequest:
        headers = {}
        query_params = {"token": token}

    wrapped = dash._guard(dash._api_overview)
    response = await wrapped(FakeRequest())
    assert isinstance(response, dict)
    assert "stats" in response


def _add(machine_body):
    pass
