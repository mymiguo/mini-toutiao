"""
QQ Bot Bridge — 通过 QQ 官方机器人远程操控 Claude Code。

架构:
  用户 QQ → QQ 服务器 → WebSocket → 本脚本 → claude -c -p → 回复 QQ 消息

依赖: pip install qq-botpy
配置: 在 qq_bridge_config.json 中填写 AppID/AppSecret
"""

import asyncio
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import botpy
from botpy.flags import Intents
from botpy.message import C2CMessage

# ============================================================
# 加载配置
# ============================================================
SCRIPT_DIR = Path(__file__).resolve().parent


def load_config():
    config_path = SCRIPT_DIR / "qq_bridge_config.json"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            return json.load(f)
    # Fallback: try parent directory
    config_path = SCRIPT_DIR.parent / "qq_bridge_config.json"
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            return json.load(f)
    raise FileNotFoundError(
        "请创建 qq_bridge_config.json 文件，包含 appid, appsecret, claude_path, project_dir"
    )


cfg = load_config()
APPID = cfg["appid"]
APPSECRET = cfg["appsecret"]
CLAUDE_PATH = cfg.get("claude_path", "claude")
PROJECT_DIR = Path(cfg.get("project_dir", str(SCRIPT_DIR.parent)))
SESSION_TTL = cfg.get("session_ttl", 1800)  # 30分钟
CLAUDE_TIMEOUT = cfg.get("claude_timeout", 300)  # 5分钟
MAX_MSG_LEN = cfg.get("max_msg_len", 3800)
CHUNK_DELAY = cfg.get("chunk_delay", 0.6)
RATE_LIMIT = cfg.get("rate_limit", 3)

SESSION_FILE = Path(cfg.get("session_file", str(PROJECT_DIR / ".claude" / "qq_bot_session.json")))

# ============================================================
# 会话管理
# ============================================================
class SessionManager:
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.data = self._load()

    def _load(self) -> dict:
        if self.file_path.exists():
            try:
                return json.loads(self.file_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"session_active": False, "message_count": 0, "last_message_at": None}

    def _save(self):
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def is_active(self) -> bool:
        if not self.data["session_active"]:
            return False
        last = self.data.get("last_message_at")
        if not last:
            return False
        return time.time() - last < SESSION_TTL

    def record(self):
        self.data["session_active"] = True
        self.data["message_count"] = self.data.get("message_count", 0) + 1
        self.data["last_message_at"] = time.time()
        self._save()

    def reset(self):
        self.data = {"session_active": False, "message_count": 0, "last_message_at": None}
        self._save()


session = SessionManager(SESSION_FILE)


# ============================================================
# Claude Code 调用
# ============================================================
def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def split_long_message(text: str, max_len: int = MAX_MSG_LEN) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n", 0, max_len)
        if cut == -1 or cut < max_len // 2:
            for sep in ["。", ". ", "；", "！", "？", "\n"]:
                pos = remaining.rfind(sep, 0, max_len)
                if pos > max_len // 2:
                    cut = pos + len(sep)
                    break
        if cut == -1 or cut < 100:
            cut = max_len
        chunks.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    total = len(chunks)
    return [f"({i + 1}/{total}) {c}" for i, c in enumerate(chunks)]


async def run_claude(prompt: str, continue_session: bool = False) -> str:
    args = [
        CLAUDE_PATH,
        "--append-system-prompt",
        "你是用户的AI助手，通过QQ与用户交流。保持口语化、自然的朋友聊天风格，简洁直接，不要过度格式化。称呼用户为大哥。",
    ]
    if continue_session:
        args.append("-c")
    args.extend(["-p", prompt])

    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(PROJECT_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=CLAUDE_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return "Claude Code 执行超时，请简化请求。"

    output = stdout.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace")
        return f"Claude Code 执行出错 (code={proc.returncode}):\n{err[:500]}"

    return strip_ansi(output).strip()


# ============================================================
# 速率限制
# ============================================================
_last_msg_time: dict[str, float] = {}


def check_rate(user_id: str) -> tuple[bool, str]:
    now = time.time()
    if user_id in _last_msg_time:
        elapsed = now - _last_msg_time[user_id]
        if elapsed < RATE_LIMIT:
            return False, f"请稍等 {RATE_LIMIT - elapsed:.0f} 秒"
    _last_msg_time[user_id] = now
    return True, ""


# ============================================================
# 机器人客户端
# ============================================================
class ClaudeBot(botpy.Client):
    async def on_ready(self):
        print("[bridge] 机器人已上线，等待消息...")

    async def on_c2c_message_create(self, message: C2CMessage):
        user_id = message.author.user_openid
        content = (message.content or "").strip()
        print(f"[bridge] {user_id[:12]}...: {content[:80]}")

        if not content:
            return

        if content == "/reset":
            session.reset()
            await message.reply(content="会话已重置。", msg_seq=1)
            return

        if content == "/status":
            active = session.is_active()
            count = session.data.get("message_count", 0)
            await message.reply(
                content=f"会话{'活跃' if active else '空闲'}，已对话 {count} 轮。", msg_seq=1
            )
            return

        ok, reason = check_rate(user_id)
        if not ok:
            await message.reply(content=reason, msg_seq=1)
            return

        await message.reply(content="思考中...", msg_seq=1)

        continue_session = session.is_active()
        try:
            response = await run_claude(content, continue_session=continue_session)
        except Exception as e:
            response = f"Claude Code 调用失败: {e}"

        session.record()

        if not response:
            response = "(无输出)"

        chunks = split_long_message(response)
        for i, chunk in enumerate(chunks):
            await message.reply(content=chunk, msg_seq=i + 2)
            await asyncio.sleep(CHUNK_DELAY)


# ============================================================
# 启动
# ============================================================
def main():
    print("[bridge] QQ → Claude Code 桥接启动中...")
    print(f"[bridge] 项目目录: {PROJECT_DIR}")

    intents = Intents(public_messages=True)
    client = ClaudeBot(intents=intents)
    client.run(appid=APPID, secret=APPSECRET)


if __name__ == "__main__":
    main()
