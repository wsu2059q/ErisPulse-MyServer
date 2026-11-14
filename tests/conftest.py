"""pytest 配置：测试目录入 sys.path、async 用例支持、公共夹具。"""

import asyncio
import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from fakes import make_main  # noqa: E402


@pytest.fixture
def main():
    return make_main()


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    """async test 函数转同步执行（不依赖 pytest-asyncio）。"""
    testfunc = pyfuncitem.obj
    if inspect.iscoroutinefunction(testfunc):
        params = list(inspect.signature(testfunc).parameters)
        kwargs = {name: pyfuncitem.funcargs[name]
                  for name in pyfuncitem.fixturenames
                  if name in params and name in pyfuncitem.funcargs}
        _run(testfunc(**kwargs))
        return True
    return None
