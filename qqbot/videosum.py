"""B站视频链接 → 文稿 → 交给模型评价、总结。

只做 B站，理由很实在：官方「AI 总结」接口一次就能把整段文稿（带时间戳）吐出来，
纯标准库、不用装 ffmpeg、不用跑 whisper、不用下模型。抖音/YouTube 没有等价物，
得走「下载 + 语音识别」那条重活，留着 find_video_link() 这个入口以后接。

链路：
    b23.tv 短链 / BV 号 / av 号
      → x/web-interface/view                      拿 cid、up_mid、时长、简介
      → x/web-interface/view/conclusion/get       （Wbi 签名 + SESSDATA）
           ├─ 有 → model_result 里的摘要 / 提纲 / AI 全文文稿
           └─ 没有 → x/player/wbi/v2 的 CC 字幕兜底
      → review_prompt() 拼成给模型的资料

实测坑（2026-10）：
* 请求头不带浏览器 UA 和 Referer，接口直接回 412；
* Wbi 签名要现算，密钥来自 nav 接口，会轮换，所以只缓存几分钟；
* 带登录态的 player/wbi/v2 反而更容易 412，所以它只当兜底、失败就算了；
* 短链是 302，得先跟到最终地址才拿得到 BV 号；
* 没有 SESSDATA 时 conclusion/get 回 -101（账号未登录），这是最常见的情况，
  调用方要把话说清楚，别让模型瞎编。
"""
from __future__ import annotations

import difflib
import gzip
import hashlib
import io
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .base import *  # noqa: F401,F403


# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------

VIEW_URL = "https://api.bilibili.com/x/web-interface/view"
NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
CONCLUSION_URL = "https://api.bilibili.com/x/web-interface/view/conclusion/get"
PLAYER_URL = "https://api.bilibili.com/x/player/wbi/v2"
SNAPSHOT_URL = "https://api.bilibili.com/x/player/videoshot"
# 按标题找视频（手机端分享的卡片里常常只有标题，没有链接）
SEARCH_URL = "https://api.bilibili.com/x/web-interface/wbi/search/type"
# 标题相似度到这个分就不用再搜第二轮了（0.95 基本就是同一句话，只有标点不同）。
_TITLE_SURE = 0.95

# 登录态续期（B站 web 端自己用的那套，见 README「cookie 为什么会突然失效」）
COOKIE_INFO_URL = "https://passport.bilibili.com/x/passport-login/web/cookie/info"
CORRESPOND_URL = "https://www.bilibili.com/correspond/1/"
REFRESH_URL = "https://passport.bilibili.com/x/passport-login/web/cookie/refresh"
CONFIRM_URL = "https://passport.bilibili.com/x/passport-login/web/confirm/refresh"

# 续期时用来加密时间戳的 RSA 公钥（1024 bit），取自 B站 web 端。
REFRESH_KEY_N = int(
    "cb81dd8e02470656da04dd38544446e2a3412051cfe9adc6a330a5ef9022850968"
    "4960970b91c3360ca29c49e1690ff8fa068cb9dfc6179d1e9585cb9424e847db"
    "1ef59f33e37dd4dca8ccfb7631ee9b4a92640d00c8204300152a0ab7cd802889"
    "d3445aec69918fe6022b534912e7b095be3424dad1ba81145e969b533181f1",
    16,
)
REFRESH_KEY_E = 65537
REFRESH_KEY_BYTES = 128

# 接口认 UA，默认的 qqchatbot/0.1 会被 412 拦掉。
HTTP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Wbi 混淆表（B站前端写死的那张）。
MIXIN_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61,
    26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36,
    20, 34, 44, 52,
]

# 手机端分享出来的链接尾巴很脏：``?share_source=copy_web&vd_source=…``、
# 后面紧跟中文（``…bdcc视频内容``）、全角标点。所以 URL 的字符集要**排掉中文
# 和全角符号** —— 否则短链会把中文一起吞进去，变成一条打不开的地址
# （``b23.tv/abc视频内容``），然后报「这个链接我没认出来」。
_URL_RE = re.compile(
    r"https?://[^\s\"'<>，。；：！？、（）()【】〔〕「」『』《》〈〉"
    r"\u3000\u4e00-\u9fff\uff00-\uffef]+"
)
# 偶尔 QQ 会把协议头吃掉，只剩 ``b23.tv/abc123``（手机端转发时见过）。
_BARE_SHORT_RE = re.compile(
    r"(?<![0-9A-Za-z.])((?:b23\.tv|bili2233\.cn|bili\.tv)/[0-9A-Za-z]+)",
    re.IGNORECASE,
)
# QQ 小程序卡片的跳转中转页（B站小程序卡片里只有这个）；url.cn / t.cn 是
# QQ 微信自己套的那层短链，偶尔会把 B站地址包在里面。
_QQ_RELAY_RE = re.compile(
    r"https?://(?:m\.q\.qq\.com/a/s/|url\.cn/|t\.cn/)[0-9A-Za-z_\-]+"
)
# 这些域名自己不是 B站，但跟一次跳转就能拿到真正的地址。
RELAY_HOSTS = ("q.qq.com", "url.cn", "t.cn", "dwz.cn")
_BV_RE = re.compile(r"BV[0-9A-Za-z]{10}")
_AV_RE = re.compile(r"(?<![0-9A-Za-z])av(\d{1,12})(?![0-9A-Za-z])", re.IGNORECASE)
# 落地页 HTML 里找 BV 号：只认「明确指向某个视频」的写法，
# 否则首页推荐位里一堆 BV 号，随便捡一个就是错的视频。
_BVID_IN_PAGE_RE = re.compile(
    r"""(?:/video/|"bvid"\s*:\s*"|bvid=|bvid%22%3A%22)(BV[0-9A-Za-z]{10})"""
)

# B站自家的域名。手机 App 分享有时给 ``bili2233.cn``（B站自己的另一个短链域名），
# 老版本还给 ``bili.tv``。
BILI_HOSTS = ("bilibili.com", "b23.tv", "bili2233.cn", "bili.tv")
# 这些是「短码 → 302」的域名，路径第一段就是短码。
SHORT_HOSTS = ("b23.tv", "bili2233.cn", "bili.tv")
# 跟跳转时最多读这么多字节落地页，只为在 HTML 里找 BV 号。
_PAGE_LIMIT = 200_000


# --------------------------------------------------------------------------
# 链接识别
# --------------------------------------------------------------------------


def _host_of(url: str) -> str:
    return (urllib.parse.urlparse(url).netloc or "").lower().split(":")[0]


def _is_bili_host(host: str) -> bool:
    host = (host or "").lower().split(":")[0]
    return any(host == name or host.endswith("." + name) for name in BILI_HOSTS)


def _is_short_host(host: str) -> bool:
    host = (host or "").lower().split(":")[0]
    return any(host == name or host.endswith("." + name) for name in SHORT_HOSTS)


def _is_relay_host(host: str) -> bool:
    """QQ / 微信套的那层中转短链——不是 B站，但跟一次就能看出是不是。"""
    host = (host or "").lower().split(":")[0]
    return any(host == name or host.endswith("." + name) for name in RELAY_HOSTS)


def short_link(url: str) -> str:
    """把短链收拾成 ``https://b23.tv/<短码>``。

    手机分享常带一长串 ``?share_source=…&vd_source=…``，甚至中文粘在尾巴上；
    短码本身永远是纯字母数字，所以只取路径第一段的字母数字部分重新拼一条，
    这样后面跟 302 就一定跳得动。
    """
    host = _host_of(url)
    if not _is_short_host(host):
        return ""
    segment = urllib.parse.urlparse(url).path.strip("/").split("/")[0]
    # 只留 ASCII 字母数字：str.isalnum() 对中文也返回 True，用了会把
    # 「AbCd123啦啦啦」整段当成短码。
    code = "".join(re.findall(r"[0-9A-Za-z]", segment))
    if not code:
        return ""
    return f"https://{host}/{code}"


def find_video_link(text: str) -> str | None:
    """从一句话里挑出 B站的东西：完整链接、短链，或光秃秃的 BV 号/av 号。

    返回原样的字符串，交给 :meth:`BiliClient.resolve` 归一成 bvid。
    认不出来返回 None —— 调用方据此走普通对话。
    """
    text = text or ""
    for url in _URL_RE.findall(text):
        if _is_bili_host(_host_of(url)):
            return url
    # 协议头被吃掉、或者链接被中文粘住的短链
    match = _BARE_SHORT_RE.search(text)
    if match:
        return "https://" + match.group(1).rstrip(".")
    match = _BV_RE.search(text)
    if match:
        return match.group(0)
    match = _AV_RE.search(text)
    if match:
        return match.group(0)
    return None


def _raw_variants(raw: str):
    """卡片 JSON 里链接的几种常见伪装，逐个还原后再搜。

    踩过的三种：
    * ``https:\\/\\/b23.tv\\/abc``（转义一层）
    * ``https:\\\\/\\\\/b23.tv\\\\/abc``（整个卡片被序列化了两遍，反斜杠叠了两层）
    * ``https%3A%2F%2Fb23.tv%2Fabc``（整条 URL 被 urlencode 塞进参数里）

    前两种统一用「把斜杠前面的反斜杠全吃掉」处理，一层两层三层都行。
    """
    body = raw or ""
    # \u002F 是 "/" 的转义写法，序列化两遍就变成 \\u002F。
    body = re.sub(r"\\+u002[fF]", "/", body)
    body = re.sub(r"\\+u003[aA]", ":", body)
    # URL 本身不可能含反斜杠，所以斜杠前的反斜杠一律删掉是安全的。
    body = re.sub(r"\\+/", "/", body)
    seen = {body}
    yield body
    for _ in range(2):
        decoded = urllib.parse.unquote(body)
        if decoded in seen:
            break
        seen.add(decoded)
        yield decoded


def find_link_in_raw(raw: str) -> str:
    """在整条事件的原始 JSON 里翻 B站链接。

    QQ 的分享卡片不走 content（正文是空的），跳转地址埋在卡片 JSON 里，所以
    base.parse_group_event 会把原始事件抖一遍找链接。

    顺序很要紧：先把所有还原形态的「完整链接」都试完，再退到裸短链 / BV 号。
    反过来的话，``https:\\/\\/b23.tv\\/abc?share_source=…`` 会先被裸短链那条
    规则截成 ``https://b23.tv/abc``，分享参数就丢了（虽然还能用，但不该这么干）。
    """
    bodies = list(_raw_variants(raw))
    for body in bodies:
        for url in _URL_RE.findall(body):
            if _is_bili_host(_host_of(url)):
                return url.rstrip("\\")
    # 协议头被吃掉，只剩 ``b23.tv/abc123``
    for body in bodies:
        match = _BARE_SHORT_RE.search(body)
        if match:
            return "https://" + match.group(1).rstrip(".")
    # 光秃秃的 BV 号：只在整条事件里能看出 B站 痕迹时才认。实测踩过 —— 一条
    # 平平常常的文字消息，事件某个随机字段里凑出 ``…BVqQDrsNYAeD…``，就被当成
    # 视频链接存了 10 分钟，接着别人问「总结一下」直接被劫持，报 code=-400。
    for body in bodies:
        lowered = body.lower()
        if not ("哔哩哔哩" in body or "bilibili" in lowered or "b23.tv" in lowered):
            continue
        match = _BV_RE.search(body)
        if match:
            return match.group(0)
    # B站小程序卡片 / QQ 套的中转短链：卡片里只有跳转页，没有 B站地址。
    # 只有同时出现「哔哩哔哩」字样才认，免得把别的小程序也当视频。
    for body in bodies:
        if "哔哩哔哩" not in body and "bilibili" not in body.lower():
            continue
        match = _QQ_RELAY_RE.search(body)
        if match:
            return match.group(0)
    return ""


# --------------------------------------------------------------------------
# 按标题找视频（手机端卡片里只有标题时用）
# --------------------------------------------------------------------------

# 搜索结果里标题带高亮标签：``【摄影集】<em class="keyword">洛克</em>王国…``
_EM_TAG_RE = re.compile(r"<[^>]{1,120}>")
_HTML_ENTITIES = (
    ("&quot;", '"'), ("&#39;", "'"), ("&lt;", "<"),
    ("&gt;", ">"), ("&amp;", "&"),
)
# 比较标题时只保留中日韩文字和字母数字：标点、emoji、空格在搜索结果里经常被
# 改写，留着反而拉低相似度。但 ①②③ 这类序号要留着（映射成数字），不然
# 「某某②」和「某某③」这种同一个系列的不同集会被当成同一条。
_TITLE_NOISE_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff]+")
_CIRCLED_DIGITS = {chr(0x2460 + index): str(index + 1) for index in range(20)}


def strip_em(text: str) -> str:
    """去掉搜索结果的 <em> 高亮标签和 HTML 实体。"""
    out = _EM_TAG_RE.sub("", str(text or ""))
    for entity, char in _HTML_ENTITIES:
        out = out.replace(entity, char)
    return out


def clean_title(text: str, *, keep_numbers: bool = True) -> str:
    """标题归一化：去标签、去 ``[QQ小程序]`` 前缀、只留文字数字、转小写。

    ``keep_numbers=False`` 会把 ①②③ 直接丢掉，只用来拼搜索关键词 —— B站的
    搜索对这类序号很敏感，带上「2」经常一条都对不上。打分仍然用带序号的版本，
    不然「某某②」和「某某③」会打平。
    """
    out = strip_em(str(text or ""))
    out = out.replace("[QQ小程序]", "").replace("【QQ小程序】", "")
    if keep_numbers:
        for symbol, digit in _CIRCLED_DIGITS.items():
            out = out.replace(symbol, digit)
    return _TITLE_NOISE_RE.sub("", out).lower()


def title_similarity(left: str, right: str) -> float:
    """两个标题有多像（0~1）。都是归一化之后的串。"""
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return difflib.SequenceMatcher(None, left, right).ratio()


# --------------------------------------------------------------------------
# 数据结构
# --------------------------------------------------------------------------


class BiliBlocked(RuntimeError):
    """被风控（412）—— 通常是请求头不对或请求太密。"""


class BiliNeedLogin(RuntimeError):
    """接口要求登录（-101）—— 缺 SESSDATA。"""


@dataclass
class Video:
    bvid: str
    aid: int
    cid: int
    title: str
    up_name: str = ""
    up_mid: int = 0
    duration: int = 0
    desc: str = ""
    view: int = 0
    like: int = 0
    # 下面几项回头由 _fill_text() 填
    summary: str = ""
    outline: str = ""
    text: str = ""
    source: str = ""
    # 官方快照帧 [(第几秒, jpeg 字节), ...]，由 _fill_frames() 填
    frames: list[tuple[int, bytes]] = field(default_factory=list)

    def duration_text(self) -> str:
        return duration_text(self.duration)

    def has_content(self) -> bool:
        return bool(self.text or self.summary or self.outline)


def duration_text(seconds: int) -> str:
    seconds = max(0, int(seconds or 0))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}小时{minutes}分"
    if minutes:
        return f"{minutes}分{secs}秒" if secs else f"{minutes}分钟"
    return f"{secs}秒"


def _mmss(seconds) -> str:
    try:
        total = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        return "00:00"
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit] + "…"


# --------------------------------------------------------------------------
# 客户端
# --------------------------------------------------------------------------


def _xor(left: bytes, right: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(left, right))


def _mgf1(seed: bytes, length: int) -> bytes:
    """MGF1 掩码生成（RFC 8017 附录 B）。只用 SHA-256。"""
    out = b""
    counter = 0
    while len(out) < length:
        out += hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
        counter += 1
    return out[:length]


def correspond_path(timestamp_ms: int) -> str:
    """毫秒时间戳 → B站换 refresh_csrf 用的路径片段。

    算法是 RSA-OAEP(SHA-256) 加密 ``refresh_<毫秒时间戳>`` 再转十六进制。
    这里用标准库手搓：为了一个续期功能去装 cryptography/pycryptodome 不划算。

    **时间戳必须用「此刻」**——服务端会校验时效，拿旧时间戳算出来的地址
    只会返回空页面，表现出来就是「找不到 refresh_csrf」。
    """
    message = f"refresh_{timestamp_ms}".encode()
    hlen = 32
    k = REFRESH_KEY_BYTES
    if len(message) > k - 2 * hlen - 2:
        raise ValueError("消息太长，塞不进 1024 位密钥")
    padding = b"\x00" * (k - len(message) - 2 * hlen - 2)
    data_block = hashlib.sha256(b"").digest() + padding + b"\x01" + message
    seed = os.urandom(hlen)
    masked_db = _xor(data_block, _mgf1(seed, k - hlen - 1))
    masked_seed = _xor(seed, _mgf1(masked_db, hlen))
    block = b"\x00" + masked_seed + masked_db
    cipher = pow(int.from_bytes(block, "big"), REFRESH_KEY_E, REFRESH_KEY_N)
    return cipher.to_bytes(k, "big").hex()


def dump_cookie(cookies: dict[str, str]) -> str:
    """dict → ``a=1; b=2`` 一行，直接塞进 Cookie 头或者写文件都行。"""
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def save_cookie(cookies: dict[str, str]) -> bool:
    """把续期拿到的整段 cookie 写回配置文件（``config/bilibili_cookie.txt``）。

    只写文件，不碰环境变量：配在 env 里的那种情况没法持久化，只能本次进程内有效。
    """
    if not cookies:
        return False
    try:
        VIDEO_COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
        VIDEO_COOKIE_FILE.write_text(dump_cookie(cookies) + "\n", encoding="utf-8")
        return True
    except OSError as error:
        log(f"[视频] 新 cookie 写盘失败：{error!r}")
        return False


def _parse_set_cookie(lines: list[str]) -> dict[str, str]:
    """响应头里的 Set-Cookie 列表 → ``{名字: 值}``。只取第一个分号前那段。"""
    cookies: dict[str, str] = {}
    for line in lines:
        head = line.split(";", 1)[0].strip()
        name, separator, value = head.partition("=")
        if separator and name.strip():
            cookies[name.strip()] = value.strip()
    return cookies


def clean_sessdata(raw: str) -> str:
    """把用户粘进来的东西收拾成能直接塞进 Cookie 头的值。

    实测大家粘的花样太多：整段 ``SESSDATA=xxx; bili_jct=yyy``、带引号、带
    ``SESSDATA=`` 前缀、或者多粘了一层空格。这里统一抠出 SESSDATA 那一段。
    **不做 URL 解码** —— 浏览器里存的就是 ``%2C`` 形式，服务端会自己解；
    真还原成逗号反而可能被 Cookie 解析器当成两段。
    """
    text = (raw or "").strip().strip('"').strip("'").strip()
    if not text:
        return ""
    match = re.search(r"SESSDATA\s*=\s*([^;\s]+)", text, re.IGNORECASE)
    if match:
        text = match.group(1)
    return text.strip().strip('"').strip("'")


def parse_cookie(raw: str) -> dict[str, str]:
    """整段 Cookie 字符串（或光秃秃一个值）→ dict。

    支持 F12 里直接复制出来的 ``SESSDATA=xxx; buvid3=yyy; …``、多行、带引号；
    只有一个不带 ``=`` 的值时，按 SESSDATA 处理。

    为什么值得支持整段：B站 会校验 buvid3 这类设备指纹，而且 SESSDATA 会随
    浏览器访问滚动刷新 —— 只捂着一个值，很容易「刚才还能用，现在 -101」。
    """
    text = (raw or "").strip()
    if not text:
        return {}

    # 从 Network 面板「复制为 cURL」粘过来的整条命令里捞 cookie 请求头，
    # 这是拿到 HttpOnly（SESSDATA）最省事的办法。
    # 注意：必须在去掉首尾引号之前做，否则命令末尾的收尾引号会被 strip 掉。
    if "curl" in text.lower():
        found = re.search(
            r"-H\s+['\"]cookie:\s*([^'\"]+)['\"]", text, re.IGNORECASE
        ) or re.search(r"-b\s+['\"]([^'\"]+)['\"]", text)
        if found:
            text = found.group(1)

    text = text.strip().strip('"').strip("'").strip()
    # 只复制到「cookie: xxx」这一行也行
    text = re.sub(r"^\s*(?:set-)?cookie\s*:\s*", "", text, flags=re.IGNORECASE)
    text = text.strip()

    if not text:
        return {}
    if "=" not in text and "\t" not in text:
        return {"SESSDATA": text}

    # F12「应用 → Cookie」表格里右键全选复制，出来的是 Tab 分隔的多列文本：
    #   Name\tValue\tDomain\tPath\t…\nSESSDATA\txxx\t.bilibili.com\t/\t…
    # 这种行里没有 "="，按分号切会整行丢掉，所以先认出来单独处理。
    if "\t" in text:
        cookies: dict[str, str] = {}
        for line in text.splitlines():
            cells = line.split("\t")
            if len(cells) < 2:
                # 表格里手动补的一行（``SESSDATA=xxx``）没有 Tab，按分号规则兜住，
                # 不然「表格 + 手补一行」这种混合格式会把补的那行进不去。
                name, separator, value = line.partition("=")
                name, value = name.strip(), value.strip()
                if separator and re.fullmatch(r"[A-Za-z0-9_.\-]+", name) and value:
                    cookies[name] = value
                continue
            name, value = cells[0].strip(), cells[1].strip()
            if not name or not value or name.lower() in ("name", "名称"):
                continue
            if re.fullmatch(r"[A-Za-z0-9_.\-]+", name):
                cookies[name] = value
        if cookies:
            return cookies

    cookies = {}
    for chunk in re.split(r"[;\n\r]+", text):
        name, separator, value = chunk.partition("=")
        name, value = name.strip(), value.strip()
        if separator and name and value:
            cookies[name] = value
    return cookies


def load_cookie() -> str:
    """读出配置好的 cookie：整段优先，其次单独一个 SESSDATA。"""
    whole = read_text_config(VIDEO_COOKIE_FILE, "BILIBILI_COOKIE")
    if whole.strip():
        return whole
    return read_text_config(VIDEO_SESSDATA_FILE, "BILIBILI_SESSDATA")


class BiliClient:
    """B站接口的最小封装：只要一个 SESSDATA 就能拿到文稿。

    ``sessdata`` 留空也能跑，只是多半只能拿到标题/简介 —— conclusion/get 会回
    -101。这是刻意设计的：没配 cookie 时不该炸，只是老实说看不了。
    """

    def __init__(self, cookie: str = "", *, timeout: float = 15.0) -> None:
        # 支持整段 Cookie（SESSDATA + buvid3 + …），也支持只给一个 SESSDATA 值。
        # 实测只带 SESSDATA 也能通，但 B站 那边一刷新就作废，带上整段更稳。
        self.cookies = parse_cookie(cookie)
        self.sessdata = self.cookies.get("SESSDATA", "")
        # 有 cookie 却没有 SESSDATA，是「复制方式不对」而不是「没配」。
        # 实际踩过：F12 的 Cookie 表格 Ctrl+A 只复制已渲染的行，而 SESSDATA
        # 是 HttpOnly、按名字排在后面，很容易整行漏掉，然后一路报「没配」。
        if self.cookies and not self.sessdata:
            log(
                f"[视频] 读到 {len(self.cookies)} 个 cookie 但没有 SESSDATA —— "
                "多半是表格只复制到了可见部分，改用 Network 里复制 cookie 请求头"
            )

        self.timeout = timeout
        self._mixin = ""
        self._mixin_at = 0.0
        # 登录态检查结果缓存，60 秒内不重复问 nav（视频流程本来就要好几秒，
        # 但 cookie 死了的话反复重试续期很浪费请求）。
        self._login_at = 0.0
        self._login_ok = False
        # 续期成功后把新 cookie 落盘，下次启动直接能用；调用方可以换掉这个回调
        # （比如想在内存里存就别写文件）。
        self.on_refresh = save_cookie

    # ---- 底层请求 ----

    def _headers(self, bvid: str = "") -> dict[str, str]:
        referer = (
            f"https://www.bilibili.com/video/{bvid}"
            if bvid else "https://www.bilibili.com/"
        )
        headers = {
            "User-Agent": HTTP_UA,
            "Referer": referer,
            "Origin": "https://www.bilibili.com",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        if self.cookies:
            headers["Cookie"] = "; ".join(
                f"{name}={value}" for name, value in self.cookies.items()
            )
        return headers

    def _raw(self, url: str, form: dict | None = None,
             bvid: str = "") -> tuple[int, str, dict[str, str]]:
        """发一次请求，返回 (状态码, 响应体, 新下发的 cookie)。

        不走 ``http_json()`` 的两个原因：续期要看响应头里的新 cookie；而且 B站
        会返回 gzip，标准库的 urlopen 不会自动解压。
        """
        referer = (
            f"https://www.bilibili.com/video/{bvid}"
            if bvid else "https://www.bilibili.com/"
        )
        headers = {
            "User-Agent": HTTP_UA,
            "Referer": referer,
            "Origin": "https://www.bilibili.com",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        if "passport.bilibili.com" in url or "/bapis/" in url:
            headers["Origin"] = "https://passport.bilibili.com"
        if self.cookies:
            headers["Cookie"] = dump_cookie(self.cookies)
        body = None
        if form is not None:
            body = urllib.parse.urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status = int(response.status)
                raw = response.read()
                headers_out = response.headers
        except urllib.error.HTTPError as error:
            status = int(error.code)
            try:
                raw = error.read()
            except Exception:  # noqa: BLE001 - 读不出 body 就当空
                raw = b""
            headers_out = error.headers or {}
        encoding = (headers_out.get("Content-Encoding", "") or "").lower()
        fresh = _parse_set_cookie(list(headers_out.get_all("Set-Cookie") or []))
        if "gzip" in encoding:
            try:
                raw = gzip.decompress(raw)
            except OSError:
                pass
        if fresh:
            self._absorb(fresh)
        return status, raw.decode("utf-8", errors="replace"), fresh

    def _absorb(self, fresh: dict[str, str]) -> None:
        """收下响应里下发的新 cookie。

        B站会滚动换发 SESSDATA：换发之后旧值就作废了。如果我们只读不存，
        下一次还拿旧值去问，就会被判「账号未登录」—— 这正是「刚才还能用，
        过一会儿就 -101」的由来。
        """
        changed = {name: value for name, value in fresh.items()
                   if self.cookies.get(name) != value}
        if not changed:
            return
        self.cookies.update(changed)
        self.sessdata = self.cookies.get("SESSDATA", "")
        if callable(self.on_refresh):
            self.on_refresh(self.cookies)
        if "SESSDATA" in changed:
            log("[视频] 服务端换发了新 cookie，已更新并写回磁盘")

    def _json(self, url: str, bvid: str = "") -> dict:
        status, text, _ = self._raw(url, bvid=bvid)
        if status == 412:
            raise BiliBlocked("B站风控 412")
        try:
            return json.loads(text) if text.strip() else {}
        except ValueError:
            return {"_raw": text[:200]}

    def _mix_key(self) -> str:
        if self._mixin and time.time() - self._mixin_at < 300:
            return self._mixin
        data = self._json(NAV_URL)
        wbi = (data.get("data") or {}).get("wbi_img") or {}
        img = _key_of(wbi.get("img_url"))
        sub = _key_of(wbi.get("sub_url"))
        if not img or not sub:
            raise RuntimeError("拿不到 Wbi 密钥")
        raw = img + sub
        self._mixin = "".join(raw[index] for index in MIXIN_TAB if index < len(raw))[:32]
        self._mixin_at = time.time()
        return self._mixin

    def _signed_url(self, base: str, params: dict) -> str:
        pairs = []
        for key, value in params.items():
            if value is None or value == "":
                continue
            # Wbi 规定：值里这几个字符要剔掉，再 urlencode。
            cleaned = "".join(ch for ch in str(value) if ch not in "!'()*")
            pairs.append((key, cleaned))
        pairs.sort()
        pairs.append(("wts", str(int(time.time()))))
        query = urllib.parse.urlencode(pairs)
        signature = hashlib.md5((query + self._mix_key()).encode()).hexdigest()
        return f"{base}?{query}&w_rid={signature}"

    # ---- 解析成 bvid ----

    def resolve(self, text: str) -> str:
        """把链接 / 短链 / av 号统一成 bvid；认不出来返回空串。"""
        link = find_video_link(text)
        if not link:
            return ""
        bvid = self._bvid_in(link)
        if bvid:
            return bvid
        host = _host_of(link)

        # B站小程序卡片 / QQ 套的中转短链：卡片里只有一个跳转页，真正地址在
        # 页面里。
        if _is_relay_host(host):
            final, page = _follow(link, self.timeout)
            inner = find_video_link(final) or find_video_link(page)
            if not inner:
                log(f"[视频] 中转页里没找到 B站地址：{final[:120]}")
                return ""
            link = inner
            host = _host_of(link)
            bvid = self._bvid_in(link)
            if bvid:
                return bvid

        if not (_is_bili_host(host) or _is_short_host(host)):
            return ""
        # 短链只留短码再跟：share_source / vd_source 那一串参数、粘在尾巴上的
        # 中文，一律丢掉；完整链接则原样跟。
        target = short_link(link) or link
        final, page = _follow(target, self.timeout)
        # 正常情况最终地址里就有 BV 号；短链过期/被拦时会落到首页或活动页，
        # 那就去 HTML 里找，但只认 /video/、bvid= 这种明确写法，免得捡到
        # 首页推荐位里的别的视频。
        returned = self._bvid_in(final)
        if returned:
            return returned
        match = _BVID_IN_PAGE_RE.search(page or "")
        if match:
            return match.group(1)
        returned = self._bvid_in(page)
        if returned:
            return returned
        log(f"[视频] 短链跳出去没带 BV 号：{final[:120]}")
        return ""

    def _bvid_in(self, blob: str) -> str:
        """从一串文本里取 BV 号；只有 av 号就先换成 bvid。"""
        match = _BV_RE.search(blob or "")
        if match:
            return match.group(0)
        match = _AV_RE.search(blob or "")
        if match:
            return self._bvid_of_aid(match.group(1))
        return ""

    def _bvid_of_aid(self, aid) -> str:
        try:
            data = self._json(f"{VIEW_URL}?aid={int(aid)}")
        except Exception as error:  # noqa: BLE001 - 认不出来就当没有
            log(f"[视频] av 号转 bvid 失败：{error!r}")
            return ""
        return str((data.get("data") or {}).get("bvid") or "")

    def search_bvid(self, title: str) -> str:
        """只有标题时，去 B站 搜一个最像的视频回来。

        为什么需要这个：手机端把视频分享到 QQ，走的是「小程序卡片」，卡片被平台
        转成一段纯文字（``[卡片消息] 小程序 / title: … / source: 哔哩哔哩``），
        里面**根本没有链接**，只有标题。所以只能拿标题去搜。

        搜索接口要登录态（没 cookie 会回 -101），也走 Wbi 签名。挑的时候按标题
        相似度取最高分，低于 ``VIDEO_TITLE_MATCH`` 就当没搜到 —— 宁可让用户
        重发链接，也别总结一个不相干的视频。

        搜两轮：先拿带序号的标题搜（准），不行再拿去掉 ①②③ 的搜（宽），
        但两轮打分都用带序号的版本，这样「某某②」不会被「某某③」抢走。
        第一轮分数不够高（<0.95）才去搜第二轮 —— 已经很肯定了就别多花一次请求。
        """
        target = clean_title(title)
        if not target:
            return ""
        queries = [target]
        loose = clean_title(title, keep_numbers=False)
        if loose and loose != target:
            queries.append(loose)
        best_bvid, best_score = "", 0.0
        for keyword in queries:
            bvid, score = self._search_once(keyword, target)
            if score > best_score:
                best_bvid, best_score = bvid, score
            if best_score >= _TITLE_SURE:
                break
        if best_bvid and best_score >= VIDEO_TITLE_MATCH:
            log(f"[视频] 按标题定到 {best_bvid}（相似度 {best_score:.2f}）：{target[:24]!r}")
            return best_bvid
        return ""

    def _search_once(self, keyword: str, target: str) -> tuple[str, float]:
        """搜一次，返回 (最像的 bvid, 相似度)。不够像就给空串。"""
        try:
            payload = self._json(self._signed_url(SEARCH_URL, {
                "search_type": "video",
                "keyword": keyword,
                "page": 1,
            }))
        except BiliBlocked as error:
            log(f"[视频] 按标题搜索被拦：{error}")
            return "", 0.0
        except Exception as error:  # noqa: BLE001 - 搜不到就当没有
            log(f"[视频] 按标题搜索失败：{error!r}")
            return "", 0.0
        if payload.get("code") != 0:
            code = payload.get("code")
            if code == -101:
                log("[视频] 按标题搜索要登录态（-101），cookie 多半已经作废")
            else:
                log(f"[视频] 按标题搜索被拒：code={code} {payload.get('message')}")
            return "", 0.0
        best_bvid, best_score = "", 0.0
        for item in (payload.get("data") or {}).get("result") or []:
            if not isinstance(item, dict):
                continue
            bvid = str(item.get("bvid") or "")
            if not bvid:
                continue
            score = title_similarity(target, clean_title(str(item.get("title") or "")))
            if score > best_score:
                best_bvid, best_score = bvid, score
        log(
            f"[视频] 按标题搜「{keyword[:20]}」最高 {best_score:.2f} "
            f"（门槛 {VIDEO_TITLE_MATCH:.2f}）"
        )
        return (best_bvid, best_score) if best_score >= VIDEO_TITLE_MATCH else ("", best_score)

    def analyze_by_title(self, title: str) -> Video | None:
        """标题 → 搜到的视频 → 文稿。搜不到返回 None。"""
        bvid = self.search_bvid(title)
        if not bvid:
            return None
        video = self._video_info(bvid)
        if video is None:
            return None
        self._fill_text(video)
        return video

    # ---- 主流程 ----

    def analyze(self, text: str) -> Video | None:
        """一句话 → Video（能填的都填上）。认不出视频就返回 None。

        同步函数：调用方用 ``asyncio.to_thread`` 丢进线程，别卡住事件循环。
        画面截图不在这里抓 —— 那是可选的第二步 ``snapshot()``，看完时长再决定。
        """
        bvid = self.resolve(text)
        if not bvid:
            return None
        video = self._video_info(bvid)
        if video is None:
            return None
        self._fill_text(video)
        return video

    def is_login(self) -> bool:
        """问一次 nav 接口：cookie 到底还有效没有。

        比等 conclusion/get 回 -101 再猜要清楚得多 —— 那个 -101 既可能是
        「没配」，也可能是「配了已经作废」，排查时全靠试。
        """
        try:
            payload = self._json(NAV_URL)
        except Exception:  # noqa: BLE001 - 网络问题当没登录处理
            return False
        return bool(((payload or {}).get("data") or {}).get("isLogin"))

    # ---- 登录态续期 ----
    #
    # 为什么需要这一段：B站 web 端有一套「滑动续期」机制，浏览器每次访问都会
    # 换发新 SESSDATA，旧值随即作废。你把 cookie 复制给机器人之后，只要浏览器
    # 那边还开着 B站，几分钟内机器人手里这份就成了「上一版」——表现就是
    # 「刚才还能用，现在 -101」。这里按 B站自己的流程主动续期，把新 cookie
    # 写回文件，机器人就能自己续命。

    def check_refresh(self) -> bool | None:
        """问服务端这份 cookie 要不要续期。

        返回 True=建议续期，False=还在有效期，None=问不出来（缺少 bili_jct 或网络问题）。
        """
        csrf = self.cookies.get("bili_jct", "")
        if not csrf:
            return None
        try:
            payload = self._json(f"{COOKIE_INFO_URL}?csrf={urllib.parse.quote(csrf)}")
        except Exception:  # noqa: BLE001 - 问不出来就当不知道
            return None
        if payload.get("code") != 0:
            return None
        return bool((payload.get("data") or {}).get("refresh"))

    @staticmethod
    def _dom_value(page: str, element_id: str) -> str:
        """从续期页面里抠 ``id="1-name"`` / ``id="1-value"`` 的文本。

        放宽成 ``[^>]*`` 是因为 B站给这俩 div 还挂了 class，写死会漏。
        """
        match = re.search(
            rf'id=["\']{re.escape(element_id)}["\'][^>]*>\s*([^<\s]+)\s*<', page)
        return match.group(1) if match else ""

    def refresh(self) -> bool:
        """按 B站 web 端自己的流程续期一次，成功就把新 cookie 收进 ``self.cookies``。

        2026-10 实测的新版流程（和网上旧教程不一样）：
        * ``cookie/refresh`` **不再要 csrf**，只要 ``refresh_csrf`` + ``refresh_token``；
        * ``refresh_csrf`` 和 ``refresh_token`` 都写在 correspond 页面的
          ``#1-name`` / ``#1-value`` 里；
        * 拿到新 cookie 后还要调一次 ``confirm/refresh``，否则服务端只算「预刷新」。
        """
        token = self.cookies.get("ac_time_value", "")
        if not self.sessdata:
            return False

        # 1) 取 refresh_csrf（顺带拿页面里的 refresh_token 兜底）。
        #    时间戳必须是「这一刻」，旧时间戳算出来的地址只会给空壳页面。
        address = f"{CORRESPOND_URL}{correspond_path(int(time.time() * 1000))}"
        try:
            status, page, _ = self._raw(address)
        except Exception as error:  # noqa: BLE001 - 网络/被拒都算没辙
            log(f"[视频] 取 refresh_csrf 失败：{error!r}")
            return False
        refresh_csrf = self._dom_value(page, "1-name")
        token = token or self._dom_value(page, "1-value")
        if not refresh_csrf:
            log(f"[视频] 续期页面没给 refresh_csrf（HTTP {status}，"
                f"{len(page)} 字）—— 多半是页面改成前端渲染了，得重新取一次 cookie")
            return False
        if not token:
            log("[视频] 没有 refresh_token（ac_time_value，在 localStorage 不在 cookie 里），没法续期")
            return False

        # 2) 换新 cookie
        try:
            _, text, fresh = self._raw(REFRESH_URL, {
                "refresh_csrf": refresh_csrf,
                "source": "main_web",
                "refresh_token": token,
            })
        except Exception as error:  # noqa: BLE001
            log(f"[视频] 续期请求失败：{error!r}")
            return False
        try:
            payload = json.loads(text)
        except ValueError:
            payload = {}
        if payload.get("code") != 0:
            log(f"[视频] 续期被拒：{payload.get('code')} {payload.get('message')}")
            return False
        if not fresh.get("SESSDATA"):
            log("[视频] 续期返回里没有新 SESSDATA")
            return False

        new_token = str((payload.get("data") or {}).get("refresh_token") or "")
        if new_token:
            self.cookies["ac_time_value"] = new_token

        # 3) 确认。不确认的话旧 token 不失效、新 token 也可能不生效。
        try:
            self._raw(CONFIRM_URL, {"refresh_token": new_token or token})
        except Exception as error:  # noqa: BLE001 - 确认失败不影响手里这份新 cookie
            log(f"[视频] 续期确认失败（新 cookie 已拿到）：{error!r}")

        if callable(self.on_refresh):
            self.on_refresh(self.cookies)
        log("[视频] cookie 续期成功，已写回磁盘")
        return True

    def ensure_login(self) -> bool:
        """取文稿之前过一遍：还有效就放行，失效了就试着续期。

        返回 True 表示「现在能拿 AI 文稿」；没有 cookie 也返回 False，这不算错误。
        结果缓存 60 秒，免得一批视频接连处理时反复问 nav / 反复续期。
        """
        if not self.sessdata:
            return False
        now = time.monotonic()
        if now - self._login_at < 60:
            return self._login_ok
        if self.is_login():
            ready = True
        else:
            log("[视频] 登录态已失效，尝试自动续期…")
            ready = self.refresh() and self.is_login()
            if not ready:
                log("[视频] 自动续期没成功，需要重新取一次 cookie")
        self._login_at = now
        self._login_ok = ready
        return ready

    def snapshot(self, video: Video, count: int = 6) -> int:
        """给已经 analyze 过的视频补一组画面截图，返回实际抓到几张。

        单独一个方法是为了让调用方先判断时长/开关 —— 长视频没必要白抓一遍。
        """
        self._fill_frames(video, count)
        return len(video.frames)

    def _video_info(self, bvid: str) -> Video | None:
        try:
            data = self._json(f"{VIEW_URL}?bvid={bvid}", bvid)
        except Exception as error:  # noqa: BLE001 - 打不开就当没这条
            log(f"[视频] 取信息失败：{error!r}")
            return None
        if data.get("code") != 0:
            log(f"[视频] 取信息失败：code={data.get('code')} {data.get('message')}")
            return None
        payload = data.get("data") or {}
        owner = payload.get("owner") or {}
        stat = payload.get("stat") or {}
        return Video(
            bvid=str(payload.get("bvid") or bvid),
            aid=int(payload.get("aid") or 0),
            cid=int(payload.get("cid") or 0),
            title=str(payload.get("title") or "").strip(),
            up_name=str(owner.get("name") or "").strip(),
            up_mid=int(owner.get("mid") or 0),
            duration=int(payload.get("duration") or 0),
            desc=str(payload.get("desc") or "").strip(),
            view=int(stat.get("view") or 0),
            like=int(stat.get("like") or 0),
        )

    def _fill_text(self, video: Video) -> None:
        """按「AI 文稿 → 平台摘要 → CC 字幕 → 只有简介」的顺序找内容。"""
        # 先确认登录态：失效就自动续期一次，省得白白走一遍失败流程。
        self.ensure_login()
        try:
            if self._ai_text(video):
                return
        except BiliNeedLogin:
            # -101 有两个完全不同的原因，混着报会误导排查（自己踩过）：
            # 没配 cookie，和配了但已经失效（用户退出登录/换设备/过期）。
            if self.sessdata:
                log("[视频] SESSDATA 被拒（-101），自动续期也没救回来，需要重新取一次 cookie")
            else:
                log("[视频] 没配 SESSDATA，拿不到 AI 文稿")
        except BiliBlocked as error:
            log(f"[视频] {error}，改用字幕兜底")
        except Exception as error:  # noqa: BLE001 - 换个来源继续
            log(f"[视频] AI 文稿失败：{error!r}")
        try:
            if self._cc_text(video):
                return
        except Exception as error:  # noqa: BLE001 - 兜底再失败就只剩简介
            log(f"[视频] CC 字幕失败：{error!r}")
        video.source = "只有标题和简介"

    def _ai_text(self, video: Video) -> bool:
        url = self._signed_url(CONCLUSION_URL, {
            "bvid": video.bvid,
            "cid": video.cid,
            "up_mid": video.up_mid or "",
        })
        data = self._json(url, video.bvid)
        code = data.get("code")
        if code == -101:
            raise BiliNeedLogin("账号未登录")
        if code != 0:
            log(f"[视频] AI 总结不可用：code={code} {data.get('message')}")
            return False
        payload = data.get("data") or {}
        # data.code：0 有摘要，1 无摘要（没识别到语音/排队中），-1 不支持
        if payload.get("code") != 0:
            log(f"[视频] 这个视频没有 AI 摘要（data.code={payload.get('code')}）")
            return False
        result = payload.get("model_result") or {}
        if isinstance(result, str):  # 老版本直接给一段字符串
            video.summary = result.strip()
            video.source = "平台摘要"
            return bool(video.summary)
        video.summary = str(result.get("summary") or "").strip()
        video.outline = _format_outline(result.get("outline") or [])
        video.text = _subtitle_text(result.get("subtitle") or [])
        if video.text:
            video.source = "AI 文稿"
        elif video.summary or video.outline:
            video.source = "平台摘要 + 提纲"
        return video.has_content()

    def _cc_text(self, video: Video) -> bool:
        url = self._signed_url(PLAYER_URL, {"bvid": video.bvid, "cid": video.cid})
        data = self._json(url, video.bvid)
        if data.get("code") != 0:
            return False
        subtitles = ((data.get("data") or {}).get("subtitle") or {}).get(
            "subtitles"
        ) or []
        for item in subtitles:
            sub_url = str(item.get("subtitle_url") or "").strip()
            # 实测这个字段有时只给个 "https:"，或给协议相对的 //host/...
            if sub_url.startswith("//"):
                sub_url = "https:" + sub_url
            elif not sub_url.startswith("http"):
                continue
            try:
                body = self._json(sub_url, video.bvid)
            except Exception as error:  # noqa: BLE001 - 换下一条字幕
                log(f"[视频] 字幕下载失败：{error!r}")
                continue
            pieces = [
                str(line.get("content") or "").strip()
                for line in body.get("body") or []
            ]
            text = "".join(piece for piece in pieces if piece)
            if len(text) >= 40:
                video.text = text
                video.source = f"CC 字幕（{item.get('lan_doc') or item.get('lan') or '未知语言'}）"
                return True
        return False

    # ---- 画面快照 ----

    def _fill_frames(self, video: Video, count: int) -> None:
        """抓一组官方快照帧，让模型除了「听到的」还能看到「屏幕上的」。

        背景：所谓 AI 文稿其实是 ASR 把声音转成文字，纯音乐、无声演示、
        PPT 录屏这类视频文稿是空的，字幕里的参数、图表它也一概看不到。
        补救办法是官方的 videoshot 接口 —— 它把整段视频压成一张雪碧图
        （默认 10×10 格），自带每帧对应的秒数。裁开就是一组均匀分布的截图，
        不用下载视频、不用 ffmpeg，是「不引入重依赖还能看画面」的唯一办法。

        失败一律当没有：截图是锦上添花，不该拖垮整条链路。
        """
        if count <= 0:
            return
        try:
            from PIL import Image  # 裁雪碧图要用；没装就只看文稿
        except ImportError:
            log("[视频] 没装 Pillow，跳过画面快照")
            return
        try:
            payload = self._json(
                f"{SNAPSHOT_URL}?bvid={video.bvid}&cid={video.cid}&index=1",
                video.bvid,
            )
        except Exception as error:  # noqa: BLE001 - 画面是附加项，失败不算错
            log(f"[视频] 快照接口失败：{error!r}")
            return

        data = (payload or {}).get("data") or {}
        stamps = data.get("index") or []
        images = data.get("image") or []
        try:
            x_len = int(data.get("img_x_len") or 0)
            y_len = int(data.get("img_y_len") or 0)
            x_size = int(data.get("img_x_size") or 0)
            y_size = int(data.get("img_y_size") or 0)
        except (TypeError, ValueError):
            return
        if not (stamps and images and x_len and y_len and x_size and y_size):
            return

        per_sheet = x_len * y_len
        for position in _pick_positions(len(stamps), count):
            sheet, cell = divmod(position, per_sheet)
            if sheet >= len(images):
                continue
            url = str(images[sheet])
            if url.startswith("//"):
                url = "https:" + url
            try:
                raw = _fetch_image(url, self.timeout, video.bvid)
                with Image.open(io.BytesIO(raw)) as sprite:
                    row, col = divmod(cell, x_len)
                    box = (
                        col * x_size, row * y_size,
                        (col + 1) * x_size, (row + 1) * y_size,
                    )
                    frame = sprite.convert("RGB").crop(box)
                    buffer = io.BytesIO()
                    frame.save(buffer, format="JPEG", quality=80)
            except Exception as error:  # noqa: BLE001
                log(f"[视频] 截图裁切失败：{error!r}")
                continue
            video.frames.append((int(stamps[position] or 0), buffer.getvalue()))


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------


def _pick_positions(total: int, count: int) -> list[int]:
    """从 total 帧里均匀挑 count 个位置，掐掉头尾各 4%（片头片尾多是黑场）。"""
    if total <= 0 or count <= 0:
        return []
    if total <= count:
        return list(range(total))
    margin = int(total * 0.04)
    low = margin
    high = max(low, total - 1 - margin)
    span = high - low
    if count == 1:
        return [low + span // 2]
    return sorted({low + round(index * span / (count - 1))
                   for index in range(count)})


def _fetch_image(url: str, timeout: float, bvid: str = "") -> bytes:
    """下雪碧图。和 API 一样要带 Referer，否则图床会拒。"""
    referer = (
        f"https://www.bilibili.com/video/{bvid}"
        if bvid else "https://www.bilibili.com/"
    )
    request = urllib.request.Request(
        url, headers={"User-Agent": HTTP_UA, "Referer": referer}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _key_of(url) -> str:
    """从 wbi_img 的 URL 里抠出密钥（去目录、去扩展名）。"""
    name = str(url or "").rsplit("/", 1)[-1]
    return name.split(".")[0]


def _follow(url: str, timeout: float) -> tuple[str, str]:
    """跟着 302 走到最终地址，返回 (最终地址, 落地页正文)。

    落地页正文只在「最终地址里没有 BV 号」时才有用：短链过期/被拦截时 B站会
    跳到一个中转页，真正的视频地址写在 HTML 的跳转脚本里。所以顺手读一小段，
    读不到也无所谓。
    """
    request = urllib.request.Request(url, headers={
        "User-Agent": HTTP_UA,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            final = response.geturl() or url
            try:
                page = response.read(_PAGE_LIMIT).decode("utf-8", "replace")
            except Exception:  # noqa: BLE001 - 读正文失败不影响拿地址
                page = ""
            return final, page
    except urllib.error.HTTPError as error:
        # 4xx/5xx 也算「跳到了」，错误响应的地址和正文里偶尔还留着线索。
        final = getattr(error, "url", "") or url
        try:
            page = error.read(_PAGE_LIMIT).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - 同上
            page = ""
        return final, page
    except Exception as error:  # noqa: BLE001 - 跟不动就按原链接再试
        log(f"[视频] 短链跳转失败：{error!r}")
        return url, ""


def _format_outline(outline) -> str:
    lines: list[str] = []
    for section in outline or []:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").strip()
        stamp = _mmss(section.get("timestamp"))
        if title:
            lines.append(f"{stamp} {title}")
        for point in section.get("part_outline") or []:
            if not isinstance(point, dict):
                continue
            content = str(point.get("content") or "").strip()
            if content:
                lines.append(f"  {_mmss(point.get('timestamp'))} {content}")
    return "\n".join(lines)


def _subtitle_text(subtitle) -> str:
    """AI 文稿：subtitle[0].part_subtitle[].content 逐段拼起来。"""
    for track in subtitle or []:
        if not isinstance(track, dict):
            continue
        pieces = [
            str(part.get("content") or "").strip()
            for part in track.get("part_subtitle") or []
            if isinstance(part, dict)
        ]
        text = "".join(piece for piece in pieces if piece)
        if text:
            return text
    return ""


# --------------------------------------------------------------------------
# 给模型的资料
# --------------------------------------------------------------------------

REVIEW_HEAD = (
    "上面是这个视频的全部资料。请你先像个正常人一样「看完」，然后做两件事：\n"
    "1）用两三句话说清它到底讲了什么，别照抄提纲，也别按时间顺序复述；\n"
    "2）给你的看法：哪里说得有意思、哪里站不住脚或让你想反驳、值不值得看。\n"
)
# 只有文稿时 / 还有截图时，说「凭什么下判断」的措辞不一样：
# 前者不许提画面，后者可以描述画面，但都不许编没看到的。
REVIEW_BASIS_TEXT = (
    "有提纲或文稿就基于它们说具体的点；只有标题和简介时，就老实说你只看到简介，"
    "别假装看过内容，也别编造视频里的画面和原话。\n"
)
REVIEW_BASIS_FRAMES = (
    "有提纲或文稿就基于它们说具体的点；没有文稿时，就靠截图里真实出现的东西说。"
    "截图只是抽样，没截到的地方别编，也别假装自己听到了声音。\n"
)
REVIEW_TAIL = (
    "直接说人话，像跟群友聊刚看完的视频，别用列表、别用标题、别分段写小作文，"
    "整段控制在 200 字以内。"
)

REVIEW_INSTRUCTION = REVIEW_HEAD + REVIEW_BASIS_TEXT + REVIEW_TAIL


def review_instruction(has_frames: bool = False) -> str:
    """按有没有截图选措辞 —— 混着说会让模型不知道该不该提画面。"""
    basis = REVIEW_BASIS_FRAMES if has_frames else REVIEW_BASIS_TEXT
    return REVIEW_HEAD + basis + REVIEW_TAIL


def review_prompt(video: Video, transcript_limit: int = 6000) -> str:
    """把视频资料拼成一条 user 消息。"""
    lines = ["【视频信息】", f"标题：{video.title or '（无标题）'}"]
    if video.up_name:
        lines.append(f"UP主：{video.up_name}")
    lines.append(f"时长：{video.duration_text()}")
    if video.view:
        lines.append(f"播放：{video.view}")
    if video.desc:
        lines.append(f"简介：{_clip(video.desc, 400)}")
    if video.source:
        lines.append(f"资料来源：{video.source}")
    if video.summary:
        lines += ["", "【平台摘要】", video.summary]
    if video.outline:
        lines += ["", "【分段提纲】", video.outline]
    if video.text:
        lines += [
            "",
            f"【文稿（原 {len(video.text)} 字，这里截断展示）】",
            _clip(video.text, transcript_limit),
        ]
    else:
        lines += ["", "（没拿到字幕或文稿，只能看标题、简介和提纲。）"]
    if video.frames:
        stamps = "、".join(_mmss(second) for second, _ in video.frames)
        lines += [
            "",
            f"【画面截图】这条消息还附了 {len(video.frames)} 张这个视频的截图"
            f"（第 {stamps} 处各一张）。它们只是抽样：画面上出现的文字、图表、"
            "场景和人物可以据此判断，没抽到的地方仍然是空白，别补。",
        ]
    instruction = review_instruction(bool(video.frames))
    lines += ["", instruction]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 手动验一把：python -m qqbot.videosum <链接或BV号>
# 不经过 QQ，也不会把 cookie 打出来，配完 SESSDATA 先用它确认通了再重启机器人。
# --------------------------------------------------------------------------

def _refresh_hint(need: bool | None) -> str:
    if need is None:
        return "问不出来（缺 bili_jct，或者网络不通）"
    return "该续期了" if need else "暂时不用"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="试一下 B站视频能不能取到文稿")
    parser.add_argument("link", nargs="?", default="", help="视频链接 / BV 号 / av 号")
    parser.add_argument("--frames", type=int, default=VIDEO_FRAMES,
                        help=f"顺带抓几张画面截图（默认 {VIDEO_FRAMES}，0 = 不抓）")
    parser.add_argument("--save", default="", metavar="目录",
                        help="把抓到的截图存下来，方便自己看一眼")
    parser.add_argument("--refresh", action="store_true",
                        help="只续期登录态，不取视频（配完 cookie 先跑这个）")
    args = parser.parse_args()

    client = BiliClient(load_cookie())
    if client.sessdata:
        extra = len(client.cookies) - 1
        print(f"SESSDATA：已读到（{len(client.sessdata)} 字符）"
              + (f"，另带 {extra} 个 cookie" if extra > 0 else "，只有这一个"))
        missing = [name for name in ("bili_jct", "ac_time_value")
                   if not client.cookies.get(name)]
        if "bili_jct" in missing:
            print("缺少 bili_jct：这份 cookie 不全，自动续期做不了"
                  "（从 Network 里复制 cookie 请求头能带全）")
        if "ac_time_value" in missing:
            # 它不是 cookie，存在 localStorage，复制 cookie 永远拿不到，别说成「cookie 不全」
            print("缺少 ac_time_value：它存在 localStorage 而不是 cookie 里，"
                  "所以复制 cookie 拿不到。补法：")
            print("  F12 → 控制台 → localStorage.getItem('ac_time_value')")
            print("  然后在 data/bilibili_cookie.txt 末尾另起一行写 ac_time_value=那个值")
            print("  （缺它不影响取文稿，只是失效后不能自动续期）")
        login = client.is_login()
        print(f"登录态：{'有效' if login else '无效（B站回 -101）'}")
        if login:
            print("续期建议：" + _refresh_hint(client.check_refresh()))
    else:
        print("SESSDATA：没配（只能靠截图和简介）")

    if args.refresh:
        if not client.sessdata:
            print("没配 cookie，没什么好续的。")
            raise SystemExit(1)
        refreshed = client.refresh()
        print("续期：" + ("成功，新 cookie 已写回 config/bilibili_cookie.txt" if refreshed
                        else "失败（原因见上面的日志）"))
        if refreshed:
            print("续期后登录态：" + ("有效" if client.is_login() else "仍然无效"))
        raise SystemExit(0 if refreshed else 1)

    target = args.link.strip() or input("视频链接或 BV 号：").strip()

    result = client.analyze(target)
    if result is None:
        print("没认出来，或者视频取不到。链接对吗？")
        raise SystemExit(1)
    print(f"《{result.title}》 {result.up_name} {result.duration_text()}")
    print(f"来源：{result.source}")
    print(f"摘要 {len(result.summary)} 字 / 提纲 {len(result.outline)} 字 / 文稿 {len(result.text)} 字")
    if result.text:
        print("文稿开头：" + result.text[:80])
    elif result.summary:
        print("摘要开头：" + result.summary[:80])

    if args.frames > 0:
        count = client.snapshot(result, args.frames)
        stamps = "、".join(_mmss(second) for second, _ in result.frames)
        print(f"画面截图：{count} 张" + (f"（{stamps}）" if stamps else ""))
        if args.save and result.frames:
            folder = Path(args.save)
            folder.mkdir(parents=True, exist_ok=True)
            for index, (second, data) in enumerate(result.frames, 1):
                (folder / f"{index:02d}_{_mmss(second).replace(':', '-')}.jpg").write_bytes(data)
            print(f"已存到 {folder}")
