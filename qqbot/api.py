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
        # (group, path, mtime) -> (file_info, 过期时间)
        self._file_cache: dict[tuple[str, str, float], tuple[str, float]] = {}

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

    async def send_text(self, group_openid: str, content: str,
                        msg_id: str | None = None, msg_seq: int = 1) -> dict:
        payload: dict = {"msg_type": 0, "content": content}
        if msg_id:
            payload["msg_id"] = msg_id
            payload["msg_seq"] = msg_seq
        data = await http_json_async(
            "POST", f"{API_BASE}/v2/groups/{group_openid}/messages",
            payload, await self._headers(),
        )
        if "id" not in data:
            raise RuntimeError(f"发文本失败：{data}")
        return data

    async def send_markdown(self, group_openid: str, content: str,
                            msg_id: str | None = None, msg_seq: int = 1) -> dict:
        """发 markdown 卡片（msg_type=2）。群聊自定义 markdown 已对所有机器人开放。"""
        payload: dict = {"msg_type": 2, "markdown": {"content": content}}
        if msg_id:
            payload["msg_id"] = msg_id
            payload["msg_seq"] = msg_seq
        data = await http_json_async(
            "POST", f"{API_BASE}/v2/groups/{group_openid}/messages",
            payload, await self._headers(),
        )
        if "id" not in data:
            raise RuntimeError(f"发 markdown 失败：{data}")
        return data

    async def upload_image(self, group_openid: str, path: Path) -> str:
        key = (group_openid, str(path), path.stat().st_mtime)
        cached = self._file_cache.get(key)
        if cached and (cached[1] == 0 or time.time() < cached[1] - 30):
            return cached[0]

        raw = path.read_bytes()
        if len(raw) > DIRECT_UPLOAD_LIMIT:
            # 直传二进制的硬上限就是 5MB；超过要走分片上传（图片软限制 20MB）。
            file_info = await self._chunked_upload(group_openid, path, raw)
        else:
            payload = {
                "file_type": 1,
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
                raise RuntimeError(f"上传图片失败（{path.name}）：{data}")
            ttl = int(data.get("ttl") or 0)
            self._file_cache[key] = (str(file_info), time.time() + ttl if ttl else 0)
            log(f"[上传] {path.name} → file_info 就绪（ttl={ttl}s）")
            return str(file_info)
        ttl = int(file_info.get("ttl") or 0)
        self._file_cache[key] = (str(file_info.get("file_info")), time.time() + ttl if ttl else 0)
        return str(file_info.get("file_info"))

    async def _chunked_upload(self, group_openid: str, path: Path,
                              raw: bytes) -> dict:
        """超过 5MB 的图片走分片上传：

        upload_prepare（拿 upload_id + 各分片预签名 URL）
        → 逐片 PUT → 每片 upload_part_finish
        → 带 upload_id 调 files 接口合并，拿 file_info。
        """
        size = len(raw)
        payload = {
            "file_type": 1,
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
                "file_type": 1,
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
                         msg_id: str | None = None, msg_seq: int = 1) -> dict:
        file_info = await self.upload_image(group_openid, path)
        payload: dict = {"msg_type": 7, "media": {"file_info": file_info}}
        if msg_id:
            payload["msg_id"] = msg_id
            payload["msg_seq"] = msg_seq
        data = await http_json_async(
            "POST", f"{API_BASE}/v2/groups/{group_openid}/messages",
            payload, await self._headers(),
        )
        if "id" not in data:
            raise RuntimeError(f"发图片失败：{data}")
        return data


class GroupSender:
    """把"发一条"包装成被动回复：自动递增 msg_seq，超过 5 次退回主动消息。"""

    def __init__(self, api: QQBotAPI) -> None:
        self.api = api
        self._seq: dict[tuple[str, str], int] = {}

    def _next_seq(self, group: str, msg_id: str | None) -> tuple[str | None, int]:
        if not msg_id:
            return None, 1
        key = (group, msg_id)
        count = self._seq.get(key, 0) + 1
        self._seq[key] = count
        if count > MAX_PASSIVE_REPLIES:
            log(f"[发送] {msg_id[:12]}… 已回满 {MAX_PASSIVE_REPLIES} 条，改发主动消息")
            return None, 1
        return msg_id, count

    async def text(self, group: str, content: str, msg_id: str | None = None) -> None:
        content = format_numbers(content)
        reply_to, seq = self._next_seq(group, msg_id)
        await self.api.send_text(group, content, reply_to, seq)
        log(f"[发送] 文本（{len(content)} 字）：{content[:40]!r}")

    async def image(self, group: str, path: Path, msg_id: str | None = None) -> None:
        reply_to, seq = self._next_seq(group, msg_id)
        await self.api.send_image(group, path, reply_to, seq)
        log(f"[发送] 图片：{path}")

    async def markdown(self, group: str, content: str,
                       msg_id: str | None = None) -> None:
        reply_to, seq = self._next_seq(group, msg_id)
        await self.api.send_markdown(group, content, reply_to, seq)
        log(f"[发送] markdown（{len(content)} 字）：{content[:40]!r}")

    async def text_long(self, group: str, content: str,
                        msg_id: str | None = None) -> None:
        """长回复按段切成几条发：官方文本有长度上限，一条塞不下会被拒。"""
        chunks = split_text(content)
        if len(chunks) > 1:
            log(f"[发送] 回复 {len(content)} 字，切成 {len(chunks)} 条")
        for chunk in chunks:
            await self.text(group, chunk, msg_id)
