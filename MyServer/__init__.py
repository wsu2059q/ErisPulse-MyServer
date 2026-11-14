"""ErisPulse-MyServer 2.0：聊天平台里的 AI 原生机房。

SSH 有的全有（exec / 交互终端 / SFTP / 密钥认证），SSH 没有的也有：
AI 代管（qvq 约定服务）、危险命令分级确认、远端 tmux 会话托管、
舰队批量操作、审计回放、阈值告警进聊天。
"""

from .Main import Main

__version__ = "2.0.0"

__all__ = ["Main", "__version__"]
