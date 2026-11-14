# MyServer API 端点

控制台与公开页的全部 HTTP/WebSocket 端点。路由经框架 Router 以模块命名空间注册，实际 URL 前缀 `/MyServer`。

## 鉴权

除标注「公开」外全部需要令牌，两种来源皆可：

- `Authorization: Bearer <token>` 请求头（优先）
- `?token=<token>` 查询参数（WebSocket 专用）

令牌来源：ErisPulse-Dashboard 宿主令牌（`Dashboard.verify_token`），或 MyServer 自管令牌（storage 键 `MyServer:auth_token`）。

WebSocket 无法自定义请求头，只接受查询参数形态。

## 页面

| 端点 | 方法 | 鉴权 | 说明 |
|------|------|------|------|
| `/MyServer/app` | GET | 无（页面本身，数据接口有） | 玻璃控制台整页（Dashboard 内以 iframe 挂载） |
| `/MyServer/public` | GET | 公开 | 公开状态页；`public_page=false` 时 404 |
| `/MyServer/res/<file>` | GET | 无 | 静态资源（xterm 三件套 / app.css / app.js / public.css / public.js） |

## 数据接口（控制台）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/MyServer/api/overview` | GET | 概览聚合：stats / machines（含缓存指标）/ 最近 10 条告警 / 会话清单 / 待确认数 |
| `/MyServer/api/machines` | GET | 机器清单（凭据字段已剥离为 `****`） |
| `/MyServer/api/machines` | POST | 新增机器并测连；body：`{name, ip, port, username, auth_type, password|private_key, group, notes}`；连接失败自动回滚删除，返回 400 |
| `/MyServer/api/machines/{name}` | PUT | 增量更新机器 |
| `/MyServer/api/machines/{name}` | DELETE | 删除机器 |
| `/MyServer/api/status/{name}` | GET | 实时状态：现场采集一次；失败回退最近缓存并附 `error` |
| `/MyServer/api/exec` | POST | 执行命令；body：`{name, command, timeout?}`；危险命令返回 `{needs_confirm: true, token, message}` |
| `/MyServer/api/confirm` | POST | 确认执行；body：`{name, token}`；令牌单次有效 120 秒 |
| `/MyServer/api/alerts?limit=` | GET | 最近告警 |
| `/MyServer/api/metrics?machine=&metric=&hours=` | GET | 指标历史，`[[value, timestamp], ...]`；metric ∈ cpu_percent / mem_percent / disk_percent / load1 |
| `/MyServer/api/files?machine=&path=` | GET | 远端目录列表：`[{name, is_dir, size, mtime}]` |
| `/MyServer/api/files/upload` | POST | 上传；body：`{name, remote_path, content_b64}`（浏览器读文件转 base64） |
| `/MyServer/api/files/fetch` | POST | 下载到浏览器；body：`{name, remote_path}` → `{content_b64, size}` |
| `/MyServer/api/files/read` | POST | 读取远端文本文件（在线编辑，上限 256 KB，二进制拒绝） |
| `/MyServer/api/files/write` | POST | 写回远端文本文件 |
| `/MyServer/api/files/mkdir` | POST | 新建目录；body：`{machine, path, name}` |
| `/MyServer/api/files/delete` | POST | 删除文件/目录（目录递归）；body：`{machine, path, is_dir}` |
| `/MyServer/api/files/rename` | POST | 重命名（同目录）；body：`{machine, path, name}` |
| `/MyServer/api/sessions` | GET | 托管会话清单 |
| `/MyServer/api/sessions/close` | POST | 关闭会话；body：`{name, session}` |
| `/MyServer/api/history?machine=&limit=` | GET | 审计记录（新在前） |

## 公开页接口

| 端点 | 方法 | 说明 |
|------|------|------|
| `/MyServer/api/public/overview` | GET | 公开（`public_page=true` 才可用）：机器名 / 在线态 / 缓存指标 / 内存磁盘用量文本 / 在线历史（`history`，每位一次检查）/ 最近事件。只读监控缓存，不触发 SSH 探测；`public_show_host=true` 时附打码 host，`public_geo=true` 时附国家（ipapi.co，缓存 24h），任何情况下不含凭据 |

`history` 来自 `online` 指标（每次监控检查记录 1/0），长度由 `public_history_points` 控制；`refresh` 为 `public_refresh_seconds`，0 表示页面只手动刷新。

## WebSocket

| 端点 | 说明 |
|------|------|
| `/MyServer/ws/terminal?machine=&session=&token=` | 交互终端：独立 SSH 进程 attach 远端 tmux 会话（无 tmux 降级普通 shell 并提示） |

消息协议：

- 客户端 → 服务端：文本即终端输入；`{"type":"resize","cols":C,"rows":R}` 调整尺寸
- 服务端 → 客户端：远端输出原文

## 错误形态

未授权返回 `401 {"error": "Unauthorized"}`；参数错误 `400`；机器不存在 `404`；重名 `409`。
