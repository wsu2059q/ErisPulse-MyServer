"""Dashboard 控制台与公开页整页拼装（静态资源内联为单 HTML）。"""

from __future__ import annotations

from importlib import resources

from .. import __version__


def _read_static(name: str) -> str:
    """{!--< internal-use >!--} 读包内静态文本。"""
    return resources.files("MyServer.dashboard").joinpath(f"static/{name}").read_text(encoding="utf-8")


def view_html() -> str:
    """
    拼装控制台整页。

    :return: [str] 完整 HTML 文本
    """
    html = _read_static("index.html")
    html = html.replace("/*__I18N_JS__*/", _read_static("i18n.js"))
    html = html.replace("/*__UI_JS__*/", _read_static("ui.js"))
    html = html.replace("/*__APP_CSS__*/", _read_static("app.css"))
    html = html.replace("/*__APP_JS__*/", _read_static("app.js"))
    html = html.replace("__MS_VERSION__", __version__)
    return html


def public_html() -> str:
    """
    拼装公开状态页。

    :return: [str] 完整 HTML 文本
    """
    html = _read_static("public.html")
    html = html.replace("/*__I18N_JS__*/", _read_static("i18n.js"))
    html = html.replace("/*__PUBLIC_CSS__*/", _read_static("public.css"))
    html = html.replace("/*__PUBLIC_JS__*/", _read_static("public.js"))
    return html
