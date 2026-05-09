# QQ Bot Bridge — Claude Code 远程桥接

通过 QQ 官方机器人远程操控 Claude Code。私聊机器人发消息 → Claude Code 处理 → 结果回复到 QQ。

## 安装方式

### 方式 1：Claude Code 插件安装（推荐）

```bash
# 添加 marketplace
/plugin marketplace add mymiguo/mini-toutiao

# 安装技能
/plugin install qq-bot-bridge@mymiguo-tools
```

### 方式 2：手动安装

```bash
# 复制技能目录到项目
cp -r .claude/skills/qq-bot-bridge 你的项目/.claude/skills/

# 复制桥接脚本
cp qq_bridge.py 你的项目/
cp start_qq_bridge.bat 你的项目/

# 安装 Python 依赖
pip install qq-botpy
```

## 配置

创建 `qq_bridge_config.json`（参考 `qq_bridge_config.example.json`）：

```json
{
    "appid": "你的QQ机器人AppID",
    "appsecret": "你的QQ机器人AppSecret",
    "claude_path": "C:\\Users\\...\\AppData\\Roaming\\npm\\claude.cmd",
    "project_dir": "C:\\Users\\...\\你的项目目录"
}
```

## 启动

双击 `start_qq_bridge.bat` 或命令行运行：

```bash
python qq_bridge.py
```

## 使用

手机 QQ 给机器人发消息即可操控 Claude Code：

- 任意文本 → Claude Code 处理并回复
- `/reset` → 重置会话
- `/status` → 查看会话状态

## 前置条件

1. 在 [QQ 开放平台](https://bot.q.qq.com) 注册机器人
2. 获取 AppID 和 AppSecret
3. 开启 **C2C 私聊** 权限
4. 安装 `claude` CLI 和 Python 3.11+
