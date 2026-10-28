#!/usr/bin/env python3
"""QQ 官方机器人入口。

代码按层拆在 qqbot/ 里：
    config.py     路径 / 环境变量 / 人设 / 记忆 / 搜索参数
    base.py       日志、事件解析、文本/HTTP/图片工具、人设与短期记忆
    ai.py         DeepSeek 对话 + 联网搜索
    api.py        QQ 开放平台 HTTP API 与发送器
    cards.py      抽卡 / 开箱 / 库存
    features.py   功能列表、群友画像、名单、打卡、运势、老婆图
    videosum.py   B站视频链接 → 官方 AI 文稿 → 让模型评价（要 SESSDATA）
    handler.py    群消息业务处理（命令、关键词、歌词、AI、复读）
    net.py        WebSocket / 网关事件循环
    selftest.py   离线自检

仍然零第三方依赖（Pillow 可选）：HTTP 用 urllib，WebSocket 自己实现，
不用 httpx、websockets、NoneBot。

用法：
    python official_bot.py --selftest     # 不联网，跑一遍本地自检
    python official_bot.py --check        # 验 AppID/Secret，取 token + 网关地址
    python official_bot.py                # 正式连网关

凭据（二选一）：
    config/appid.txt + config/secret.txt（各一行）
    或环境变量 QQ_BOT_APPID / QQ_BOT_SECRET

配置目录默认 config/（凭据、人设、文案），数据目录默认 data/（运行时记录、图片）；
分别可用 QQCHATBOT_CONFIG_DIR / QQCHATBOT_DATA_DIR 覆盖。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import lyrics_line

from qqbot.ai import DeepSeek, web_search
from qqbot.api import GroupSender, QQBotAPI
from qqbot.base import KEEP_AWAKE, Paths, keep_awake, log, read_text_config
from qqbot.config import (
    CONFIG_DIR,
    DATA_DIR,
    DEEPSEEK_MODEL,
    PERSONA_FILE,
    SEARCH_ENABLED,
    config_file,
)
from qqbot.handler import Handler
from qqbot.net import Gateway


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------


def read_credential(filename: str, env_name: str) -> str:
    """凭据：config/ 优先，其次 data/（旧布局），最后环境变量。"""
    for base in (CONFIG_DIR, DATA_DIR):
        path = base / filename
        if path.is_file():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
    return os.getenv(env_name, "").strip()


def mask(value: str) -> str:
    if len(value) <= 6:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


async def check_credentials(appid: str, secret: str) -> int:
    api = QQBotAPI(appid, secret)
    try:
        token = await api.token()
        url = await api.gateway()
    except Exception as error:  # noqa: BLE001 - 排查用，直接打印原因
        log(f"[检查] 失败：{error!r}")
        return 1
    log(f"[检查] AppID {mask(appid)} 鉴权成功，token {mask(token)}")
    log(f"[检查] 网关地址：{url}")
    return 0


async def main_async(args: argparse.Namespace) -> int:
    if args.selftest:
        from qqbot.selftest import selftest

        return await selftest()

    Paths(DATA_DIR, CONFIG_DIR)  # 建好目录，顺便早暴露权限问题

    appid = read_credential("appid.txt", "QQ_BOT_APPID")
    secret = read_credential("secret.txt", "QQ_BOT_SECRET")
    if not appid or not secret:
        log(f"缺少凭据：把 AppID 写进 {CONFIG_DIR / 'appid.txt'}、"
            f"AppSecret 写进 {CONFIG_DIR / 'secret.txt'}，"
            "或设置环境变量 QQ_BOT_APPID / QQ_BOT_SECRET")
        return 2

    if args.check:
        return await check_credentials(appid, secret)

    api = QQBotAPI(appid, secret)
    sender = GroupSender(api)
    deepseek_key = read_text_config(config_file("deepseek_api.txt"), "DEEPSEEK_API_KEY")
    chat = None
    lyric_chat = None
    search = None
    if deepseek_key:
        deepseek = DeepSeek(deepseek_key)
        chat = deepseek.answer
        lyric_chat = lambda system, text, images=None: deepseek.answer(  # noqa: E731
            system, text, images=images,
            temperature=0.2, max_tokens=lyrics_line.LYRIC_MAX_TOKENS,
        )
        if SEARCH_ENABLED:
            # 搜索和对话共用同一把 key；模型自己决定搜不搜，按成功请求计费。
            search = lambda query: web_search(query, deepseek_key)  # noqa: E731
            log("[搜索] 已启用（DeepSeek Search），@对话 可按需联网查证")
        else:
            log("[搜索] 已关闭（QQCHATBOT_SEARCH=0）")
        log(f"[AI] 已启用（{DEEPSEEK_MODEL}），人设 {PERSONA_FILE}")
    else:
        log("[AI] 没配 config/deepseek_api.txt，@机器人 不会走 AI")
    handler = Handler(sender, Paths(DATA_DIR, CONFIG_DIR), chat=chat, lyric_chat=lyric_chat,
                      search=search)
    log(f"启动：AppID {mask(appid)}，数据目录 {DATA_DIR}")
    try:
        profile = await api.me()
        username = str(profile.get("username") or "").strip()
        if username:
            handler.bot_names.add(username)
            log(f"[资料] 机器人名字：{username}")
        for field_name in ("id", "union_openid"):
            value = str(profile.get(field_name) or "").strip()
            if value:
                handler.bot_ids.add(value)
        if handler.bot_ids:
            log(f"[资料] 机器人 ID：{sorted(handler.bot_ids)}")
        else:
            log("[资料] 警告：没取到机器人 ID，@ 判定会退化成「有 @ 就算叫我」")
    except Exception as error:  # noqa: BLE001 - 拿不到名字不影响主流程
        log(f"[资料] 取机器人名字失败：{error!r}")
    if keep_awake(KEEP_AWAKE):
        log("[电源] 已请求阻止系统睡眠（显示器仍可关闭；要关掉设 QQCHATBOT_KEEP_AWAKE=0）")
    elif KEEP_AWAKE and sys.platform != "win32":
        log("[电源] 非 Windows，跳过防休眠")
    gateway = Gateway(api, handler)
    try:
        await gateway.run()
    except KeyboardInterrupt:
        log("已停止")
    finally:
        keep_awake(False)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="QQ 官方机器人")
    parser.add_argument("--selftest", action="store_true", help="本地自检，不联网")
    parser.add_argument("--check", action="store_true", help="只验证凭据与网关")
    args = parser.parse_args()
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
