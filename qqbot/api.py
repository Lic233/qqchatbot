"""QQ 开放平台 HTTP API、分片上传、被动回复发送器。

依赖 base/config；不包含业务逻辑。
"""
from __future__ import annotations

from .base import *  # noqa: F401,F403


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------


class QQBotAPI:
    def __init__(self, appid: str, secret: str) -> None:
        self.appid = appid
        self.secret = secret
        self._token: str | None = None
        self._token_expire_at = 0.0
        self._token_lock = asyncio.Lock()
        # (group, path, mtime, file_type) -> (file_info, 过期时间)
        self._file_cache: dict[tuple[str, str, float, int], tuple[str, float]] = {}

    async def token(self, force: bool = False) -> str:
        async with self._token_lock:
            if not force and self._token and time.time() < self._token_expire_at - 60:
                return self._token
            data = await http_json_async(
                "POST", TOKEN_URL,
                {"appId": self.appid, "clientSecret": self.secret},
            )
            token = data.get("access_token")
            if not token:
                raise RuntimeError(f"取 access_token 失败：{data}")
            expires_in = int(data.get("expires_in") or 7200)
            self._token = str(token)
            self._token_expire_at = time.time() + expires_in
            log(f"[鉴权] access_token 已刷新，{expires_in}s 后过期")
            return self._token

    async def _headers(self) -> dict[str, str]:
        return {"Authorization": f"QQBot {await self.token()}"}

    async def gateway(self) -> str:
        data = await http_json_async("GET", GATEWAY_URL, headers=await self._headers())
        url = data.get("url")
        if not url:
            raise RuntimeError(f"取网关地址失败：{data}")
        return str(url)

    async def me(self) -> dict:
        """机器人自己的资料，主要是拿 username 用来剥正文开头的名字。"""
        return await http_json_async("GET", f"{API_BASE}/users/@me", headers=await self._headers())

    @staticmethod
    def _attach_passive(payload: dict, msg_id: str | None = None,
                        msg_seq: int = 1, event_id: str = "") -> dict:
        """把"这条回给谁"塞进 payload。

        被动回复有两种锚点：普通消息用 ``msg_id + msg_seq``（同一条最多 5 次），
        按钮点击用 ``event_id``（INTERACTION_CREATE 的 id，不需要 seq）。
        走 event_id 不吃主动消息的频控和每天 1000 条配额，所以按钮一定要走它。

        ``event_id`` 要带事件类型前缀（``INTERACTION_CREATE:xxxx``）：裸 uuid 会被
        平台判成 40034025「请求参数 event_id 无效」。回应互动那个接口反而**要裸的**，
        所以前缀在这里补，不在 Incoming 里补。
        """
        if event_id:
            payload["event_id"] = (event_id if ":" in event_id
                                   else f"INTERACTION_CREATE:{event_id}")
        elif msg_id:
            payload["msg_id"] = msg_id
            payload["msg_seq"] = msg_seq
        return payload

    async def _post_group(self, group_openid: str, payload: dict, kind: str = "消息") -> dict:
        """发群消息，顺带兜住 ``event_id`` 的两个坑。

        1. **必须带事件类型前缀**：``INTERACTION_CREATE:<uuid>``。传裸 uuid 会被判成
           40034025「请求参数 event_id 无效」（回应互动那个接口反而要裸的，两边不一致）。
        2. **平台登记有延迟**：事件推到我们手里时，它还没被登记成"可回复"，大约
           0.6~0.8 秒后才认。收到就回会踩空，所以撞上 40034025 就等一下再试。
        """
        url = f"{API_BASE}/v2/groups/{group_openid}/messages"
        headers = await self._headers()
        event_id = str(payload.get("event_id") or "")
        data: dict = {}
        for attempt, delay in enumerate((0.0, 0.9, 1.4)):
            if delay:
                await asyncio.sleep(delay)
            current = dict(payload)
            if attempt == 2 and event_id:
                # 最后一试换个写法（万一平台哪天只认裸 id）
                current["event_id"] = (
                    event_id.split(":", 1)[1] if ":" in event_id
                    else f"INTERACTION_CREATE:{event_id}"
                )
            data = await http_json_async("POST", url, current, headers)
            if data.get("err_code") != 40034025 or not event_id:
                break
            log(f"[发送] event_id 还不认（第 {attempt + 1} 次），等平台登记后重试")
        if "id" not in data:
            raise RuntimeError(f"发{kind}失败：{data}")
        return data

    async def send_text(self, group_openid: str, content: str,
                        msg_id: str | None = None, msg_seq: int = 1,
                        event_id: str = "") -> dict:
        payload: dict = {"msg_type": 0, "content": content}
        self._attach_passive(payload, msg_id, msg_seq, event_id)
        return await self._post_group(group_openid, payload, "文本")

    async def send_markdown(self, group_openid: str, content: str,
                            msg_id: str | None = None, msg_seq: int = 1,
                            event_id: str = "") -> dict:
        """发 markdown 卡片（msg_type=2）。群聊自定义 markdown 已对所有机器人开放。"""
        payload: dict = {"msg_type": 2, "markdown": {"content": content}}
        self._attach_passive(payload, msg_id, msg_seq, event_id)
        return await self._post_group(group_openid, payload, "markdown")

    async def send_keyboard(self, group_openid: str, content: str, rows: list[dict],
                            msg_id: str | None = None, msg_seq: int = 1,
                            event_id: str = "") -> dict:
        """发「markdown + 底部按钮」。按钮只能挂在 markdown 上（msg_type=2）。

        rows 是 ``[{"buttons": [button, ...]}, ...]``，最多 5 行、每行 5 个。
        按钮本身的构造见 ``qqbot/panel.py``。
        """
        payload: dict = {
            "msg_type": 2,
            "markdown": {"content": content},
            "keyboard": {"content": {"rows": rows}},
        }
        self._attach_passive(payload, msg_id, msg_seq, event_id)
        return await self._post_group(group_openid, payload, "按钮消息")

    async def interaction_ack(self, interaction_id: str, code: int = 0) -> dict:
        """回应按钮点击。

        官方要求 3 秒内回应，否则用户端一直转圈到超时；同一个 interaction_id
        只能回应一次。code：0 成功 / 1 失败 / 2 太频繁 / 3 重复 / 4 没权限 / 5 仅管理员。
        """
        if not interaction_id:
            return {}
        headers = await self._headers()
        # 文档写的是 /interactions/{id}，但 v2 接口都在 /v2 下，第一次见 404 就试 v2。
        for path in (
            f"{API_BASE}/interactions/{interaction_id}",
            f"{API_BASE}/v2/interactions/{interaction_id}",
        ):
            data = await http_json_async("PUT", path, {"code": int(code)},
                                         headers, timeout=8)
            if data.get("_http_status") == 404:
                continue
            if data.get("_http_status"):
                log(f"[按钮] 回应互动 {interaction_id[:8]}… 失败：{data}")
            return data
        log(f"[按钮] 回应互动的接口都不存在（{interaction_id[:8]}…）")
        return {"_http_status": 404}

    async def upload_image(self, group_openid: str, path: Path) -> str:
        return await self.upload_media(group_openid, path, 1)

    async def upload_media(self, group_openid: str, path: Path,
                           file_type: int = 1) -> str:
        """把本地文件传到群聊文件空间，拿 file_info。

        file_type：1 图片 / 2 视频 / 3 语音 / 4 文件（平台定义）。
        超过 5MB 一律走分片上传——那是直传二进制的硬上限。
        """
        key = (group_openid, str(path), path.stat().st_mtime, file_type)
        cached = self._file_cache.get(key)
        if cached and (cached[1] == 0 or time.time() < cached[1] - 30):
            return cached[0]

        raw = path.read_bytes()
        if len(raw) > DIRECT_UPLOAD_LIMIT:
            # 直传二进制的硬上限就是 5MB；超过要走分片上传（图片软限制 20MB）。
            file_info = await self._chunked_upload(group_openid, path, raw, file_type)
        else:
            payload = {
                "file_type": file_type,
                "file_name": path.name,
                "file_data": base64.b64encode(raw).decode("ascii"),
                "srv_send_msg": False,
            }
            data = await http_json_async(
                "POST", f"{API_BASE}/v2/groups/{group_openid}/files",
                payload, await self._headers(), timeout=60,
            )
            file_info = data.get("file_info")
            if not file_info:
                raise RuntimeError(f"上传文件失败（{path.name}）：{data}")
            ttl = int(data.get("ttl") or 0)
            self._file_cache[key] = (str(file_info), time.time() + ttl if ttl else 0)
            log(f"[上传] {path.name} → file_info 就绪（type={file_type}，ttl={ttl}s）")
            return str(file_info)
        ttl = int(file_info.get("ttl") or 0)
        self._file_cache[key] = (str(file_info.get("file_info")), time.time() + ttl if ttl else 0)
        return str(file_info.get("file_info"))

    async def _chunked_upload(self, group_openid: str, path: Path,
                              raw: bytes, file_type: int = 1) -> dict:
        """超过 5MB 的文件走分片上传：

        upload_prepare（拿 upload_id + 各分片预签名 URL）
        → 逐片 PUT → 每片 upload_part_finish
        → 带 upload_id 调 files 接口合并，拿 file_info。
        """
        size = len(raw)
        payload = {
            "file_type": file_type,
            "file_size": str(size),
            "file_name": path.name,
            "md5": hashlib.md5(raw).hexdigest(),
            "sha1": hashlib.sha1(raw).hexdigest(),
            "md5_10m": hashlib.md5(raw[:10002432]).hexdigest(),
        }
        log(f"[上传] {path.name} {size / 1024 / 1024:.1f}MB，超过 5MB，走分片上传")
        prepared = await http_json_async(
            "POST", f"{API_BASE}/v2/groups/{group_openid}/upload_prepare",
            payload, await self._headers(), timeout=60,
        )
        upload_id = prepared.get("upload_id")
        parts = prepared.get("parts") or []
        if not upload_id or not parts:
            raise RuntimeError(f"预上传失败（{path.name}）：{prepared}")

        offset = 0
        for part in parts:
            index = int(part.get("index") or 0)
            block_size = int(part.get("block_size") or prepared.get("block_size") or 0)
            chunk = raw[offset:offset + block_size] if block_size else b""
            offset += len(chunk)
            if not chunk:
                break
            url = str(part.get("presigned_url") or "")
            if not url:
                raise RuntimeError(f"分片 {index} 没有预签名地址")
            await asyncio.to_thread(http_put, url, chunk)
            await http_json_async(
                "POST", f"{API_BASE}/v2/groups/{group_openid}/upload_part_finish",
                {
                    "upload_id": upload_id,
                    "part_index": index,
                    "block_size": str(len(chunk)),
                    "md5": hashlib.md5(chunk).hexdigest(),
                },
                await self._headers(), timeout=60,
            )
            log(f"[上传] 分片 {index} 完成（{len(chunk) / 1024:.0f}KB）")

        if offset < size:
            raise RuntimeError(f"分片没覆盖完整个文件（{offset}/{size} 字节）")
        merged = await http_json_async(
            "POST", f"{API_BASE}/v2/groups/{group_openid}/files",
            {
                "file_type": file_type,
                "file_name": path.name,
                "srv_send_msg": False,
                "upload_id": upload_id,
            },
            await self._headers(), timeout=120,
        )
        if not merged.get("file_info"):
            raise RuntimeError(f"合并分片失败（{path.name}）：{merged}")
        log(f"[上传] {path.name} 合并完成（ttl={merged.get('ttl')}s）")
        return merged

    async def send_image(self, group_openid: str, path: Path,
                         msg_id: str | None = None, msg_seq: int = 1,
                         event_id: str = "") -> dict:
        file_info = await self.upload_image(group_openid, path)
        return await self._send_media(group_openid, file_info, "图片", msg_id, msg_seq,
                                      event_id)

    async def send_voice(self, group_openid: str, path: Path,
                         msg_id: str | None = None, msg_seq: int = 1,
                         event_id: str = "") -> dict:
        """发语音条：和图片同一个富媒体通道，只是 file_type=3。

        平台认 silk / mp3 / wav / ogg，所以 mp3 或 wav 直接发就行。
        """
        file_info = await self.upload_media(group_openid, path, 3)
        return await self._send_media(group_openid, file_info, "语音", msg_id, msg_seq,
                                      event_id)

    async def _send_media(self, group_openid: str, file_info: str, kind: str,
                          msg_id: str | None = None, msg_seq: int = 1,
                          event_id: str = "") -> dict:
        payload: dict = {"msg_type": 7, "media": {"file_info": file_info}}
        self._attach_passive(payload, msg_id, msg_seq, event_id)
        return await self._post_group(group_openid, payload, kind)


class GroupSender:
    """把"发一条"包装成被动回复：自动递增 msg_seq，超过 5 次退回主动消息。"""

    def __init__(self, api: QQBotAPI) -> None:
        self.api = api
        self._seq: dict[tuple[str, str], int] = {}

    def _target(self, group: str, msg_id: str | None) -> tuple[str | None, int, str]:
        """算出这条回复的被动锚点 → ``(msg_id, msg_seq, event_id)``。

        按钮点击的锚点被包成 ``event:<id>`` 塞在 msg_id 里（见
        ``base.event_reply_token``）——这样 handler 里那上百个
        ``sender.xxx(..., event.msg_id)`` 一行都不用改，发送层自己认前缀。
        """
        if not msg_id:
            return None, 1, ""
        kind, target = split_reply_token(msg_id)
        key = (group, msg_id)
        count = self._seq.get(key, 0) + 1
        self._seq[key] = count
        if count > MAX_PASSIVE_REPLIES:
            log(f"[发送] {msg_id[:12]}… 已回满 {MAX_PASSIVE_REPLIES} 条，改发主动消息")
            return None, 1, ""
        if kind == "event":
            return None, 1, target
        return target or None, count, ""

    async def text(self, group: str, content: str, msg_id: str | None = None) -> None:
        content = format_numbers(content)
        reply_to, seq, event_id = self._target(group, msg_id)
        await self.api.send_text(group, content, reply_to, seq, event_id=event_id)
        log(f"[发送] 文本（{len(content)} 字）：{content[:40]!r}")

    async def image(self, group: str, path: Path, msg_id: str | None = None) -> None:
        reply_to, seq, event_id = self._target(group, msg_id)
        await self.api.send_image(group, path, reply_to, seq, event_id=event_id)
        log(f"[发送] 图片：{path}")

    async def voice(self, group: str, path: Path, msg_id: str | None = None) -> None:
        reply_to, seq, event_id = self._target(group, msg_id)
        await self.api.send_voice(group, path, reply_to, seq, event_id=event_id)
        log(f"[发送] 语音：{path}")

    async def markdown(self, group: str, content: str,
                       msg_id: str | None = None) -> None:
        reply_to, seq, event_id = self._target(group, msg_id)
        await self.api.send_markdown(group, content, reply_to, seq, event_id=event_id)
        log(f"[发送] markdown（{len(content)} 字）：{content[:40]!r}")

    async def panel(self, group: str, content: str, rows: list[dict],
                    msg_id: str | None = None) -> None:
        """发一条带按钮的 markdown 面板。行/列超限会被平台拒（40034029）。"""
        reply_to, seq, event_id = self._target(group, msg_id)
        await self.api.send_keyboard(group, content, rows, reply_to, seq,
                                     event_id=event_id)
        log(f"[发送] 按钮面板（{len(rows)} 行）：{content[:30]!r}")

    async def text_long(self, group: str, content: str,
                        msg_id: str | None = None) -> None:
        """长回复按段切成几条发：官方文本有长度上限，一条塞不下会被拒。"""
        chunks = split_text(content)
        if len(chunks) > 1:
            log(f"[发送] 回复 {len(content)} 字，切成 {len(chunks)} 条")
        for chunk in chunks:
            await self.text(group, chunk, msg_id)
