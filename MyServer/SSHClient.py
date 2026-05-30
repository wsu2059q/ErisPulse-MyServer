import asyncio
from typing import Optional


class SSHClient:
    def __init__(self, host: str, port: int, username: str, password: str = "", key_path: str = ""):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.key_path = key_path
        self._conn = None
        self._current_process = None

    async def connect(self) -> bool:
        try:
            import asyncssh

            kwargs = {
                "host": self.host,
                "port": self.port,
                "username": self.username,
                "known_hosts": None,
            }

            if self.key_path:
                kwargs["client_keys"] = [self.key_path]
            elif self.password:
                kwargs["password"] = self.password

            self._conn = await asyncssh.connect(**kwargs)
            return True
        except Exception as e:
            raise ConnectionError(f"SSH连接失败: {e}")

    async def exec_command(self, cmd: str, timeout: int = 30, use_pty: bool = True) -> dict:
        if not self._conn:
            await self.connect()

        try:
            if use_pty:
                process = await self._conn.create_process(
                    cmd,
                    term_type="xterm",
                    term_size=(80, 24)
                )
                self._current_process = process

                try:
                    # 先读取输出，再等待进程结束
                    stdout_data = []
                    stderr_data = []

                    async def read_stdout():
                        try:
                            async for line in process.stdout:
                                stdout_data.append(line)
                        except Exception:
                            pass

                    async def read_stderr():
                        try:
                            async for line in process.stderr:
                                stderr_data.append(line)
                        except Exception:
                            pass

                    await asyncio.gather(
                        read_stdout(),
                        read_stderr(),
                        asyncio.wait_for(process.wait(), timeout=timeout)
                    )

                    return {
                        "stdout": "".join(stdout_data),
                        "stderr": "".join(stderr_data),
                        "exit_code": process.exit_status or 0
                    }
                except asyncio.TimeoutError:
                    process.terminate()
                    return {
                        "stdout": "".join(stdout_data),
                        "stderr": "命令执行超时",
                        "exit_code": -1
                    }
                finally:
                    self._current_process = None
            else:
                result = await asyncio.wait_for(
                    self._conn.run(cmd),
                    timeout=timeout
                )
                return {
                    "stdout": result.stdout or "",
                    "stderr": result.stderr or "",
                    "exit_code": result.exit_status
                }

        except asyncio.TimeoutError:
            return {
                "stdout": "",
                "stderr": "命令执行超时",
                "exit_code": -1
            }
        except Exception as e:
            self._current_process = None
            return {
                "stdout": "",
                "stderr": f"执行错误: {e}",
                "exit_code": -1
            }

    async def check_alive(self) -> bool:
        try:
            result = await self.exec_command("echo ok", timeout=10)
            return result.get("exit_code") == 0
        except Exception:
            return False

    async def get_system_info(self) -> dict:
        commands = {
            "hostname": "hostname",
            "os": "cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d'\"' -f2 || uname -s",
            "kernel": "uname -r",
            "uptime": "uptime -p 2>/dev/null | sed 's/up //' || uptime | sed 's/.*up /up /' | sed 's/,.*//'",
            "cpu_cores": "nproc",
            "cpu_model": "cat /proc/cpuinfo 2>/dev/null | grep 'model name' | head -1 | cut -d: -f2 | xargs || echo ''",
            "memory": "free -h 2>/dev/null | awk '/Mem/{print $3\"/\"$2}' || echo '未知'",
            "disk": "df -h / 2>/dev/null | awk 'NR==2{print $3\"/\"$2}' || echo '未知'",
            "load": "cat /proc/loadavg 2>/dev/null | awk '{print $1, $2, $3}' || echo '未知'",
        }

        info = {}
        for key, cmd in commands.items():
            try:
                result = await self.exec_command(cmd, timeout=5, use_pty=False)
                value = result.get("stdout", "").strip()
                info[key] = value if value else "未知"
            except Exception:
                info[key] = "未知"

        return info

    async def close(self):
        if self._conn:
            try:
                self._conn.close()
                await self._conn.wait_closed()
            except Exception:
                pass
            self._conn = None


async def test_connection(host: str, port: int, username: str, password: str = "", key_path: str = "") -> dict:
    client = SSHClient(host, port, username, password, key_path)
    try:
        await client.connect()
        alive = await client.check_alive()
        return {"success": True, "alive": alive}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        await client.close()
