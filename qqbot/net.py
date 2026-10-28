"""极简 WebSocket 客户端（标准库）与网关事件循环。

只依赖 base；Gateway 拿到 Handler 的实例调用 handle()。
"""
from __future__ import annotations

from .base import *  # noqa: F401,F403
from .api import QQBotAPI
from .handler import Handler


# --------------------------------------------------------------------------
# 极简 WebSocket 客户端（标准库）
# --------------------------------------------------------------------------


class WebSocket:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer

    @classmethod
    async def connect(cls, url: str) -> "WebSocket":
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"ws", "wss"}:
            raise ValueError(f"不支持的 WebSocket 地址：{url}")
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query

        context = ssl.create_default_context() if parsed.scheme == "wss" else None
        reader, writer = await asyncio.open_connection(
            host, port, ssl=context, server_hostname=host if context else None
        )
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        writer.write(request.encode("ascii"))
        await writer.drain()

        status = await reader.readline()
        if b" 101 " not in status and not status.endswith(b"101\r\n"):
            raise ConnectionError(f"WebSocket 握手失败：{status.decode('latin-1').strip()}")
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
        return cls(reader, writer)

    async def _send_frame(self, opcode: int, payload: bytes) -> None:
        header = bytearray([0x80 | opcode])
        mask = os.urandom(4)
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.writer.write(bytes(header) + mask + masked)
        await self.writer.drain()

    async def _recv_frame(self) -> tuple[bool, int, bytes]:
        first, second = await self.reader.readexactly(2)
        fin = bool(first & 0x80)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack(">H", await self.reader.readexactly(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", await self.reader.readexactly(8))[0]
        mask = await self.reader.readexactly(4) if masked else b""
        data = await self.reader.readexactly(length) if length else b""
        if masked:
            data = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        return fin, opcode, data

    async def send_json(self, payload: dict) -> None:
        await self._send_frame(0x1, json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    async def recv_json(self) -> dict:
        buffer = b""
        while True:
            fin, opcode, data = await self._recv_frame()
            if opcode == 0x9:          # ping
                await self._send_frame(0xA, data)
                continue
            if opcode == 0xA:          # pong
                continue
            if opcode == 0x8:          # close
                raise ConnectionError("服务端关闭了 WebSocket")
            buffer += data
            if fin:
                return json.loads(buffer.decode("utf-8"))

    async def close(self) -> None:
        try:
            await self._send_frame(0x8, b"")
        except Exception:
            pass
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except Exception:
            pass


# --------------------------------------------------------------------------
# 网关
# --------------------------------------------------------------------------


class Gateway:
    def __init__(self, api: QQBotAPI, handler: Handler) -> None:
        self.api = api
        self.handler = handler
        self.session_id: str | None = None
        self.last_seq: int | None = None
        self._seen: dict[str, float] = {}
        # 正在处理的事件任务；持有引用，避免被垃圾回收提前取消。
        self._tasks: set[asyncio.Task] = set()

    def _is_duplicate(self, msg_id: str) -> bool:
        """同一条消息可能被同时推两次（@ 事件 / 全量事件 / 重推）。"""
        if not msg_id:
            return False
        now = time.time()
        if msg_id in self._seen:
            return True
        self._seen[msg_id] = now
        if len(self._seen) > 500:
            for key, stamp in list(self._seen.items()):
                if now - stamp > 300:
                    self._seen.pop(key, None)
        return False

    async def run(self) -> None:
        backoff = 3
        while True:
            try:
                await self._session()
                backoff = 3
                await asyncio.sleep(1)      # 正常断开也别热循环
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 - 断线原因很多，统一重连
                log(f"[网关] 连接断开：{error!r}，{backoff}s 后重连")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _session(self) -> None:
        token = await self.api.token()
        url = await self.api.gateway()
        log(f"[网关] 连接 {url}")
        ws = await WebSocket.connect(url)
        heartbeat: asyncio.Task | None = None
        try:
            hello = await ws.recv_json()
            interval = float((hello.get("d") or {}).get("heartbeat_interval") or 45000) / 1000
            log(f"[网关] Hello，心跳间隔 {interval:.0f}s")
            if self.session_id:
                await ws.send_json({
                    "op": 6,
                    "d": {
                        "token": f"QQBot {token}",
                        "session_id": self.session_id,
                        "seq": self.last_seq or 0,
                    },
                })
                log("[网关] 尝试恢复会话")
            else:
                await ws.send_json({
                    "op": 2,
                    "d": {
                        "token": f"QQBot {token}",
                        "intents": INTENTS,
                        "shard": [0, 1],
                        "properties": {},
                    },
                })
                log("[网关] 已发送鉴权")
            heartbeat = asyncio.create_task(self._heartbeat(ws, interval))
            while True:
                payload = await ws.recv_json()
                opcode = payload.get("op")
                if opcode == 0:
                    if payload.get("s") is not None:
                        self.last_seq = payload["s"]
                    event_type = str(payload.get("t") or "")
                    data = payload.get("d") or {}
                    if event_type == "READY":
                        self.session_id = str(data.get("session_id") or "")
                        log(f"[网关] 已就绪，session={self.session_id[:8]}…")
                    elif event_type == "RESUMED":
                        log("[网关] 会话已恢复")
                    else:
                        await self._dispatch(event_type, data)
                elif opcode == 11:
                    continue
                elif opcode == 7:
                    log("[网关] 服务端要求重连")
                    break
                elif opcode == 9:
                    log("[网关] 会话失效，重新鉴权")
                    self.session_id = None
                    self.last_seq = None
                    break
                else:
                    log(f"[网关] 未处理的 op={opcode}")
        finally:
            if heartbeat is not None:
                heartbeat.cancel()
            await ws.close()

    async def _heartbeat(self, ws: WebSocket, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                await ws.send_json({"op": 1, "d": self.last_seq})
            except Exception:
                return

    async def _dispatch(self, event_type: str, data: dict) -> None:
        if event_type in ("GROUP_AT_MESSAGE_CREATE", "GROUP_MESSAGE_CREATE"):
            if DEBUG:
                raw = str(data.get("content") or "")
                log(f"[调试] 原始正文：{raw!r}")
            event = parse_group_event(event_type, data)
            if self._is_duplicate(event.msg_id):
                log(f"[事件] 跳过重复消息 {event.msg_id[:12]}…")
                return
            log(
                f"[事件] {event_type}{'（仅@）' if event_type == 'GROUP_AT_MESSAGE_CREATE' else '（全量）'} "
                f"群={event.group_openid[:8]}… "
                f"人={event.username or event.user_openid[:8]} 内容={event.content!r} "
                f"图={len(event.images)}"
                + (f" 卡片链接={event.attached_url}" if event.attached_url else "")
            )
            if not event.content and not event.images and not event.attached_url:
                # 正文空、又没图、还捞不出链接 —— 多半是没解析出来的分享卡片
                # （手机 QQ 转发 B站视频就是这个形态）。留一段原始 JSON，
                # 下次遇到解析不了才有东西可看。
                blob = json.dumps(data, ensure_ascii=False)
                log(f"[事件] 空正文且没解析出链接，原始事件（截断）：{blob[:900]}")
            # 每条事件各开一个任务：AI 慢（实测有一次 63s 才超时）时不能把
            # 后面的命令堵住，否则「保存吊图」要排在几分钟的问答后面。
            task = asyncio.create_task(self._handle_event(event))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            return
        if event_type.startswith("GROUP_"):
            log(f"[事件] {event_type}")
            return
        log(f"[事件] 忽略 {event_type}")

    async def _handle_event(self, event: Incoming) -> None:
        try:
            handled = await self.handler.handle(event)
            if not handled:
                log("[事件] 未命中任何规则")
        except Exception as error:  # noqa: BLE001 - 单条失败不能拖垮连接
            log(f"[事件] 处理失败：{error!r}")
