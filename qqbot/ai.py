"""联网搜索（DeepSeek Search）与 DeepSeek 对话（含工具调用循环）。

依赖 base/config；不碰 QQ 平台协议。
"""
from __future__ import annotations

from .base import *  # noqa: F401,F403


# --------------------------------------------------------------------------
# 联网搜索（DeepSeek Search）
# --------------------------------------------------------------------------

# 交给模型的工具定义。描述里把"什么时候必须搜"写清楚 —— 实测写得含糊时，
# 问新闻它也不搜，直接凭记忆答。
WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "联网搜索。凡是涉及近期事件、实时数据（天气/股价/赛果/价格）、"
            "最新版本、人事变动，或者你自己不确定的事实时，先调用它查证。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，尽量具体",
                },
            },
            "required": ["query"],
        },
    },
}


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str

    def as_text(self) -> str:
        return f"标题：{self.title}\n摘要：{self.snippet}\n链接：{self.url}"


# 这些词在几乎任何查询里都能撞上，算进相关性闸门等于没有闸门。
SEARCH_STOPWORDS = frozenset({
    "是谁", "什么", "为什么", "怎么", "如何", "哪些", "多少", "哪个",
    "今天", "昨天", "现在", "目前", "最新", "请问", "告诉", "一下", "知道",
    "有没有", "是不是", "可以", "帮我", "查查", "查一下",
})
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_ASCII_WORD = re.compile(r"[0-9a-zA-Z]{2,}")


def search_query_terms(query: str) -> set[str]:
    """把查询拆成判断"结果相不相关"的词元。

    引擎返回降级结果时（查诺奖给日历），光看"有没有结果"会把垃圾喂给模型；
    这里用 2~3 字滑窗近似分词，命中比例不够就当没搜到。
    纯数字（年份）不算词元：2026 几乎能撞上任何一页。
    """
    terms: set[str] = set()
    for word in _ASCII_WORD.findall(query or ""):
        word = word.lower()
        if word.isdigit():
            continue
        terms.add(word)
    for run in _CJK_RUN.findall(query or ""):
        for size in (2, 3):
            terms.update(
                run[index:index + size]
                for index in range(len(run) - size + 1)
            )
    return {term for term in terms if term and term not in SEARCH_STOPWORDS}


def search_relevance(query: str, results: list[SearchResult]) -> float:
    """结果里命中了多少比例的查询词元（0~1）。"""
    terms = search_query_terms(query)
    if not terms:
        return 1.0
    if not results:
        return 0.0
    haystack = " ".join(f"{item.title} {item.snippet}" for item in results).lower()
    return sum(1 for term in terms if term in haystack) / len(terms)


def search_is_relevant(query: str, results: list[SearchResult],
                       min_score: float) -> bool:
    """至少命中 2 个词元、且比例过线才算有效（查询本身只有一两个词元时放宽）。"""
    terms = search_query_terms(query)
    if not terms:
        return bool(results)
    if not results:
        return False
    haystack = " ".join(f"{item.title} {item.snippet}" for item in results).lower()
    hits = sum(1 for term in terms if term in haystack)
    return hits >= min(2, len(terms)) and hits / len(terms) >= min_score


def _truncate_search_text(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit] + "…"


def parse_search_results(payload: dict, limit: int = SEARCH_RESULT_LIMIT,
                         snippet_limit: int = SEARCH_SNIPPET_LIMIT
                         ) -> list[SearchResult]:
    """解析 DeepSeek Search 的响应（``results`` 数组）。

    摘要优先取 ``summary``（600~800 字，官方说就是给模型读的），没有再退回
    ``snippet``（100~200 字）。没标题的条目直接丢。
    """
    results: list[SearchResult] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        snippet = str(item.get("summary") or item.get("snippet") or "").strip()
        results.append(SearchResult(
            title=title,
            url=str(item.get("url") or "").strip(),
            snippet=_truncate_search_text(snippet, snippet_limit),
        ))
        if len(results) >= limit:
            break
    return results


async def deepseek_search(query: str, key: str, *,
                          limit: int = SEARCH_RESULT_LIMIT,
                          snippet_limit: int = SEARCH_SNIPPET_LIMIT
                          ) -> list[SearchResult]:
    """调一次 DeepSeek Search（``POST /v1/tools/search``）。

    官方 query 上限 128 字符、count 1~50；超了会回 400，这里先夹住。
    """
    query = (query or "").strip()[:128]
    if not query or not key:
        return []
    payload = {"query": query, "count": max(1, min(int(limit), 50))}
    data = await http_json_async(
        "POST", DEEPSEEK_SEARCH_URL, payload,
        {"Authorization": f"Bearer {key}"}, timeout=SEARCH_TIMEOUT,
    )
    return parse_search_results(data, limit, snippet_limit)


async def web_search(query: str, key: str) -> list[SearchResult]:
    """搜索并过相关性闸门；任何失败都退化成空列表（等于"没搜到"）。

    搜索失败绝不能把整条回答拖垮：模型拿到空结果就知道要老实说没查到。
    """
    query = (query or "").strip()
    if not SEARCH_ENABLED or not query or not key:
        return []
    try:
        results = await deepseek_search(query, key)
    except Exception as error:  # noqa: BLE001 - 搜索失败只影响这一轮
        log(f"[搜索] 失败：{error!r}")
        return []
    if not results:
        log(f"[搜索] 没搜到：{query!r}")
        return []
    score = search_relevance(query, results)
    if not search_is_relevant(query, results, SEARCH_MIN_SCORE):
        log(f"[搜索] 结果不相关（{score:.2f}），按没搜到处理：{query!r}")
        return []
    log(f"[搜索] 命中 {len(results)} 条（相关性 {score:.2f}）：{query!r}")
    return results


def format_search_results(results: list[SearchResult]) -> str:
    """把结果拼成给模型看的 tool 消息；空结果也明确说"没搜到"。"""
    if not results:
        return "（没有搜到可用的结果，请如实说明没查到，不要编造。）"
    text = "\n\n".join(result.as_text() for result in results)
    return text[:SEARCH_CONTEXT_LIMIT]


def search_tool_query(tool_call: dict) -> str:
    """从模型的工具调用参数里取出搜索词。"""
    try:
        arguments = json.loads(
            (tool_call.get("function") or {}).get("arguments") or "{}"
        )
    except (json.JSONDecodeError, TypeError):
        return ""
    query = arguments.get("query") if isinstance(arguments, dict) else None
    return str(query).strip() if query else ""


class DeepSeek:
    """DeepSeek 对话，标准库实现（不引 httpx）。

    ``search`` 给定时会把 ``web_search`` 工具交给模型，由它自己决定搜不搜；
    搜到的结果作为 tool 消息回喂，最多 ``SEARCH_MAX_ROUNDS`` 轮，最后一轮撤掉
    工具逼它基于已有资料作答。
    """

    def __init__(self, key: str, *, url: str = DEEPSEEK_API_URL,
                 model: str = DEEPSEEK_MODEL) -> None:
        self.key = key
        self.url = url
        self.model = model

    async def _complete(self, payload: dict) -> dict:
        """发一次 chat/completions，返回 choice 里的 message。"""
        data = await http_json_async(
            "POST", self.url, payload,
            {"Authorization": f"Bearer {self.key}"}, timeout=DEEPSEEK_TIMEOUT,
        )
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"DeepSeek 返回了空回复：{data}")
        choice = choices[0]
        if choice.get("finish_reason") == "length":
            log(
                f"[AI] 回复达到输出上限（{payload.get('max_tokens')} tokens）被截断"
            )
        return choice.get("message") or {}

    async def answer(self, system: str, text: str,
                     images: list[dict] | None = None, *,
                     temperature: float = 0.8,
                     max_tokens: int | None = None,
                     search=None) -> str:
        if not self.key:
            raise RuntimeError("未配置 DeepSeek API key（config/deepseek_api.txt）")
        # 图片只能放在 user 消息里，和文字一起按多模态内容块发。
        content: str | list[dict] = (
            [{"type": "text", "text": text}, *(images or [])] if images else text
        )
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ]
        payload: dict = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens or DEEPSEEK_MAX_TOKENS,
            "thinking": {"type": DEEPSEEK_THINKING},
        }
        for round_index in range(SEARCH_MAX_ROUNDS + 1):
            allow_search = search is not None and round_index < SEARCH_MAX_ROUNDS
            request = dict(payload)
            request["messages"] = list(messages)
            if allow_search:
                request["tools"] = [WEB_SEARCH_TOOL]
            message = await self._complete(request)
            tool_calls = message.get("tool_calls") or []
            reply = str(message.get("content") or "").strip()
            if not tool_calls or not allow_search:
                if not reply:
                    raise RuntimeError("DeepSeek 返回了空回复")
                return reply
            messages.append({
                "role": "assistant",
                "content": message.get("content"),
                "tool_calls": tool_calls,
            })
            for tool_call in tool_calls:
                query = search_tool_query(tool_call)
                results: list[SearchResult] = []
                if query:
                    try:
                        results = await search(query)
                    except Exception as error:  # noqa: BLE001 - 工具失败也要继续答
                        log(f"[搜索] 工具调用失败：{error!r}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.get("id") or "",
                    "content": format_search_results(results),
                })
            # 拿到资料后再降温度，减少对着资料编造
            payload["temperature"] = 0.3
        raise RuntimeError("DeepSeek 没能给出回答")
