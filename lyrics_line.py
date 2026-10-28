"""歌词接龙：认出「下一句」，先查歌词库，查不到再问模型。

移植自原插件的 `lyrics.py` + `ai.py` 里那几段歌词逻辑，做了两处简化：

* 只用**网易云歌词库**做确定性查询（搜歌 → 拉完整 LRC → 本地找紧接的那句），
  没有再走「DeepSeek 搜索 + 模型」那套补救链路（要额外的搜索 key）；
* 模型兜底只跑**一轮**（低温度、只准回一行），失败就回兜底文案。

歌词库为什么可靠：它认的是**歌词本身**，返回完整 LRC，下一句是字符串匹配问题，
代码给出的答案不会编；模型只在歌词库里没有这首歌时才上场。
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
import urllib.parse
import urllib.request

# 触发约定：消息以半角 ~ 或全角 ～ 结尾
LYRIC_TRAILING = "~～"

# 回复时补在下一句后面的标记（和原插件一致，让人一眼看出是接龙）
LYRIC_SUFFIX = os.getenv("QQCHATBOT_LYRIC_SUFFIX", "").strip() or "~"
# 认不出时的整条兜底回复（自带 ~，不再拼 LYRIC_SUFFIX）
LYRIC_FALLBACK = (
    os.getenv("QQCHATBOT_LYRIC_FALLBACK", "").strip()
    or "哼，这句歌词我没听过，接不上~"
)

LYRIC_ENABLED = os.getenv("QQCHATBOT_LYRIC", "").strip().lower() not in {
    "0", "false", "no", "off",
}
LYRIC_LIBRARY_ENABLED = os.getenv("QQCHATBOT_LYRIC_LIBRARY", "").strip().lower() not in {
    "0", "false", "no", "off",
}
LYRIC_LIBRARY_LIMIT = int(os.getenv("QQCHATBOT_LYRIC_LIBRARY_LIMIT", "").strip() or 5)
LYRIC_LIBRARY_TIMEOUT = float(
    os.getenv("QQCHATBOT_LYRIC_LIBRARY_TIMEOUT", "").strip() or 8
)
LYRIC_MAX_TOKENS = int(os.getenv("QQCHATBOT_LYRIC_MAX_TOKENS", "").strip() or 200)

# 模型认不出时应当回的记号；它要是不按约定、直接说人话，下面那组整句匹配兜住
LYRIC_UNKNOWN_SENTINEL = "【不知道】"

LYRIC_SYSTEM_PROMPT = (
    "你是歌词接龙助手。用户会给你一句歌词，结尾的波浪号只是标记，不属于歌词。"
    "你只需要说出这首歌紧接着的下一句歌词，别的什么都不要。"
    "只回那一句歌词本身：不要引号、不要书名号、不要歌名、不要歌手、"
    "不要解释、不要寒暄、不要编号，除了这一句歌词什么都不要写。"
    f"如果你认不出这是哪首歌，或者不能确定下一句是什么，就只回 {LYRIC_UNKNOWN_SENTINEL}。"
    "绝对不要编一句听起来像的歌词来凑数。"
)

# 模型偶尔把「下一句是：」这类引导语带上，统一削掉（只削带冒号的）
_LYRIC_LABEL_RE = re.compile(
    r"^(?:(?:下一句歌词|下一句是|下一句|答案|回答|歌词|答)\s*[:：]\s*|下一句是\s*)"
)
_LYRIC_WRAPPERS = "\"'“”‘’《》「」『』 \t"
# 整句匹配的「我不知道」类回复（做包含判断会误杀歌词本身）
LYRIC_UNKNOWN_REPLIES = {
    "不知道", "不清楚", "不确定", "认不出", "认不出来", "听不出", "听不出来",
    "没听过", "没听过这首", "没听过这首歌", "无法确定", "不是歌词", "答不上来",
    "接不上", "接不上来", "我不会", "我不知道", "我也不知道", "我不知道下一句",
    "抱歉", "对不起", "不好意思",
}

# ---- 歌词库（网易云） ------------------------------------------------------

SEARCH_ENDPOINT = "https://music.163.com/api/search/get/web"
LYRIC_ENDPOINT = "https://music.163.com/api/song/lyric"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_HEADERS = {"User-Agent": USER_AGENT, "Referer": "https://music.163.com/"}

# LRC 时间戳：[00:12.345] / [01:02] / [12:34.5]，一行可能好几个
_TIMESTAMP = re.compile(r"\[\d{1,2}:\d{1,2}(?:[.:]\d{1,3})?\]")
# 作词/作曲这类署名行不是歌词
_CREDIT = re.compile(
    r"(作词|作曲|编曲|制作人|混音|母带|录音|吉他|贝斯|鼓|和声|出品|监制|OP|SP"
    r"|lyricist|composer|producer|arranger|written by)\s*[:：]",
    re.IGNORECASE,
)
# 归一化要抹掉的东西：空白、标点、括号、引号
_PUNCTUATION = re.compile(
    r"[\s\u3000·、。，！？；：“”‘’（）()《》〈〉「」『』【】\[\]{}<>~～\-—_/\\|,.!?;:'\"]+"
)


def lyric_line(text: str) -> str | None:
    """这条消息是不是一句歌词？是就返回去掉结尾波浪号的正文。

    整条只有一个波浪号（去掉后什么都不剩）不算歌词 —— 否则谁随手发个 ~
    就要白调一次接口。
    """
    stripped = (text or "").strip()
    if not stripped or stripped[-1] not in LYRIC_TRAILING:
        return None
    return stripped.rstrip(LYRIC_TRAILING).strip() or None


def normalize(text: str) -> str:
    """归一化成「只留字」，用来比对歌词。

    做全角/半角与大小写折叠：接口返回的歌词和用户手打的同一句，
    常差在标点、空格、全半角上。
    """
    folded = unicodedata.normalize("NFKC", text or "").casefold()
    return _PUNCTUATION.sub("", folded)


def clean_lrc(lyric: str) -> list[str]:
    """LRC 文本 → 只有歌词行的列表（去时间戳、去署名、去空行）。"""
    lines: list[str] = []
    for raw_line in (lyric or "").splitlines():
        line = _TIMESTAMP.sub("", raw_line).strip()
        if not line or _CREDIT.search(line):
            continue
        lines.append(line)
    return lines


def next_line_in(lyrics: list[str], needle: str) -> str:
    """在歌词里找到 ``needle`` 那一句，返回紧接它的下一句；找不到返回空串。

    先整句命中，再退化成包含命中（用户可能只记得半句）。
    只认第一处命中：副歌重复出现时，紧接着的下一句每次都一样。
    """
    target = normalize(needle)
    if not target:
        return ""
    normalized = [normalize(line) for line in lyrics]
    index = next((i for i, line in enumerate(normalized) if line == target), None)
    if index is None:
        index = next(
            (i for i, line in enumerate(normalized) if line and target in line),
            None,
        )
    if index is None or index + 1 >= len(lyrics):
        return ""
    return lyrics[index + 1]


def clean_lyric_reply(content: str) -> str:
    """把模型回复收拾成「只有一句歌词」；收拾不出东西时返回空串。

    「不要有其他回复」是硬要求：宁可返回空串去走兜底文案，
    也不把解释、寒暄或者「不知道」当成歌词发出去。
    """
    text = (content or "").strip()
    if not text or LYRIC_UNKNOWN_SENTINEL in text:
        return ""
    for raw_line in text.splitlines():
        line = _LYRIC_LABEL_RE.sub("", raw_line.strip()).strip(_LYRIC_WRAPPERS).strip()
        # 模型有时把结尾的波浪号也带回来，先削掉，免得拼出「歌词~~」
        line = line.rstrip(LYRIC_TRAILING + " \t").strip(_LYRIC_WRAPPERS).strip()
        if not line:
            continue
        if line.strip("，。！？、,.!?") in LYRIC_UNKNOWN_REPLIES:
            return ""
        return line
    return ""


def _post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    request = urllib.request.Request(
        url, data=body,
        headers={**_HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=LYRIC_LIBRARY_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _get_json(url: str, params: dict) -> dict:
    target = url + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(target, headers=_HEADERS)
    with urllib.request.urlopen(request, timeout=LYRIC_LIBRARY_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def _parse_songs(payload: dict) -> list[dict]:
    songs = (payload.get("result") or {}).get("songs") or []
    parsed: list[dict] = []
    for song in songs:
        if not isinstance(song, dict) or not song.get("id"):
            continue
        artists = "/".join(
            str(artist.get("name") or "")
            for artist in (song.get("artists") or [])
            if isinstance(artist, dict)
        )
        parsed.append({
            "id": song["id"],
            "name": str(song.get("name") or "").strip(),
            "artists": artists,
        })
        if len(parsed) >= LYRIC_LIBRARY_LIMIT:
            break
    return parsed


def lookup_next_line(line: str) -> tuple[str, str]:
    """查这句歌词的下一句，返回 ``(下一句, 说明)``。

    * 找到 → ``("老师们都已想不起", "老狼《同桌的你》")``
    * 没找到 → ``("", 原因)``，原因只进日志，不发到群里。

    任何网络/解析问题都退化成「没找到」，绝不让歌词接龙报错。
    """
    if not LYRIC_LIBRARY_ENABLED:
        return "", "歌词库已关闭"
    line = (line or "").strip()
    if not line:
        return "", "空歌词"
    try:
        payload = _post_form(SEARCH_ENDPOINT, {
            "s": line, "type": 1, "offset": 0,
            "limit": LYRIC_LIBRARY_LIMIT, "total": "true",
        })
        songs = _parse_songs(payload)
        if not songs:
            return "", f"歌词库没搜到这首歌：{line!r}"
        # 逐首试：第一首常常就是对的，同名翻唱排在前面时会漏
        for song in songs:
            try:
                lyrics_payload = _get_json(
                    LYRIC_ENDPOINT, {"id": song["id"], "lv": 1, "kv": 1, "tv": -1}
                )
            except Exception:  # noqa: BLE001 - 换下一首继续
                continue
            lyrics = clean_lrc(str((lyrics_payload.get("lrc") or {}).get("lyric") or ""))
            answer = next_line_in(lyrics, line)
            if answer:
                return answer, f"{song['artists']}《{song['name']}》"
        return "", f"歌词库里这几首都没有这一句：{line!r}"
    except Exception as error:  # noqa: BLE001 - 歌词库只是兜底，失败不能影响接龙
        return "", f"歌词库查询失败：{type(error).__name__}: {error}"
