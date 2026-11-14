"""i18n 资产一致性：字典 JSON 可解析、zh/en 键集一致、面板引用键全部存在。"""

from __future__ import annotations

import json
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "MyServer" / "dashboard" / "static"


LANGS = ("zh", "zh-TW", "en", "ja", "ru")


def _load_dict() -> dict:
    text = (STATIC / "i18n.js").read_text(encoding="utf-8")
    head = text.split("window.MSI18N")[0]
    start = head.index("{", head.index("__MS_I18N__"))
    return json.loads(head[start:head.rindex("}") + 1])


def test_all_lang_key_parity():
    data = _load_dict()
    assert sorted(data.keys()) == sorted(LANGS)
    base = set(data["zh"])
    for lang in LANGS[1:]:
        assert set(data[lang]) == base, f"{lang} key drift: {set(data[lang]) ^ base}"


def test_html_referenced_keys_exist():
    data = _load_dict()
    html = "".join(
        (STATIC / name).read_text(encoding="utf-8") for name in ("index.html", "public.html"))
    keys = set(re.findall(r'data-i18n(?:-placeholder|-title)?="([^"]+)"', html))
    missing = keys - set(data["zh"])
    assert not missing, missing


def test_js_referenced_keys_exist():
    data = _load_dict()
    js = "\n".join(
        (STATIC / name).read_text(encoding="utf-8") for name in ("app.js", "ui.js", "public.js"))
    keys = set(re.findall(r'\bt\("(\w+)"', js)) | set(re.findall(r'\btf\("(\w+)"', js))
    missing = keys - set(data["zh"])
    assert not missing, missing
