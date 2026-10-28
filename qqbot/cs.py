"""CS2 赛事 / 赛果（数据来自 5EPlay 赛事数据中心）。

NapCat 版靠 Playwright 打开 event.5eplay.com 再读 DOM / 截图；官方版不装浏览器，
直接用它页面背后的 JSON 接口（app.5eplay.com），把时间戳、状态码、TBD 翻译成
人话。出图在 `cs_card.py`（Pillow，NapCat 同款三张卡），没装 Pillow / 画图失败时
由这里的 `brief_text` / `results_text` 退回文字。

命令：
    cs赛事 / 赛事 / cs2赛事 / csgo赛事   进行中 + 即将开始的比赛，附 S/A 级赛事
    赛果 / cs赛果 / 赛事赛果              最近完赛的比分

接口实测（2026-10-22，无需登录、无需 Cookie）：
    GET  https://app.5eplay.com/api/tournament/session_list
         ?game_status=1 进行中+未开始，=2 已结束；grades 过滤档次
    POST https://app.5eplay.com/api/csgo/tournament/csgo_event_list_v1
         {"tournaments_options": {...}} 赛事列表
"""
from __future__ import annotations

from dataclasses import dataclass

from .base import *  # noqa: F401,F403


CS_COMMANDS = ("cs赛事", "赛事", "cs2赛事", "csgo赛事")
CS_RESULT_COMMANDS = ("赛果", "cs赛果", "赛事赛果")

CS_MATCH_API = "https://app.5eplay.com/api/tournament/session_list"
CS_EVENT_API = "https://app.5eplay.com/api/csgo/tournament/csgo_event_list_v1"
CS_HEADERS = {
    "Referer": "https://event.5eplay.com/csgo/matches",
    "Accept": "application/json, text/plain, */*",
}
# 网站赛事页默认勾选的就是这一串档次（S/A 级为主）
CS_GRADES = "1,7,2,3,8,9"
CS_MATCH_LIMIT = 6       # 「即将开始」最多列几场
CS_LIVE_LIMIT = 5        # 「进行中」最多列几场
CS_EVENT_LIMIT = 5       # S/A 级赛事最多列几条
CS_RESULT_LIMIT = 10     # 赛果最多列几场
CS_LINK = "https://event.5eplay.com/csgo/matches"
CS_TIMEOUT = 12.0

_STATUS_BY_CODE = {"0": "upcoming", "1": "live", "2": "finished"}
_STATUS_LABELS = {
    "live": "进行中",
    "upcoming": "即将开始",
    "finished": "已结束",
    "past": "已结束",
}


@dataclass
class CSMatch:
    """一场比赛（从 session_list 的 mc_info / state / tt_info 里挑出来的）。"""

    start: datetime.datetime
    status: str          # live / upcoming / finished
    grade: str           # S级 / A级 / B级 …
    tournament: str
    round_name: str
    team1: str
    team2: str
    score1: str
    score2: str
    best_of: str
    logo1: str = ""
    logo2: str = ""

    @property
    def status_label(self) -> str:
        return _STATUS_LABELS.get(self.status, "未开始")


@dataclass
class CSEvent:
    """一项赛事（csgo_event_list_v1 的 basic_info）。"""

    name: str
    grade: str
    status: str          # live / upcoming / past
    start_date: str      # 10-24
    end_date: str        # 11-01
    city: str
    prize: str

    @property
    def status_label(self) -> str:
        return _STATUS_LABELS.get(self.status, "未开始")


# --------------------------------------------------------------------------
# 解析
# --------------------------------------------------------------------------


def _short_grade(label: object) -> str:
    """「S级赛事」→「S级」；「资格赛B级」这类原样保留。"""
    text = str(label or "").strip()
    if text.endswith("赛事") and len(text) > 2:
        return text[:-2]
    return text or "未分级"


def _best_of(raw: object) -> str:
    text = str(raw or "").strip()
    return f"BO{text}" if text.isdigit() and text != "0" else ""


def _score_text(value: object) -> str:
    text = str(value if value is not None else "").strip()
    return text if text.isdigit() else "0"


def _start_at(raw: object) -> datetime.datetime | None:
    try:
        value = int(raw)
        # 接口给的是秒；万一哪天改成毫秒，这里也能认。
        if value > 10 ** 12:
            value //= 1000
        return datetime.datetime.fromtimestamp(value)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _month_day(raw: object) -> str:
    """「2026-10-24 15:00:00」→「10-24」；认不出来就空着。"""
    text = str(raw or "").strip()
    return text[5:10] if len(text) >= 10 and text[4] == "-" else ""


def parse_match(raw: dict) -> CSMatch | None:
    """把一条原始记录转成 CSMatch；缺关键字段的（没时间/TBD）也保留，只是不好看。"""
    info = raw.get("mc_info") or {}
    state = raw.get("state") or {}
    tournament = raw.get("tt_info") or {}
    start = _start_at(info.get("plan_ts"))
    if start is None:
        return None
    status = _STATUS_BY_CODE.get(str(state.get("status") or ""), "upcoming")
    team1 = str((info.get("t1_info") or {}).get("disp_name") or "TBD").strip() or "TBD"
    team2 = str((info.get("t2_info") or {}).get("disp_name") or "TBD").strip() or "TBD"
    return CSMatch(
        start=start,
        status=status,
        grade=_short_grade(tournament.get("grade_label")),
        tournament=str(tournament.get("disp_name") or "").strip(),
        round_name=str(info.get("round_name") or "").strip(),
        team1=team1,
        team2=team2,
        score1=_score_text(state.get("t1_score")),
        score2=_score_text(state.get("t2_score")),
        best_of=_best_of(info.get("format")),
        logo1=str((info.get("t1_info") or {}).get("logo") or "").strip(),
        logo2=str((info.get("t2_info") or {}).get("logo") or "").strip(),
    )


def parse_matches(payload: dict) -> list[CSMatch]:
    data = (payload or {}).get("data") or {}
    matches = []
    for raw in data.get("matches") or []:
        match = parse_match(raw if isinstance(raw, dict) else {})
        if match is not None:
            matches.append(match)
    return matches


def parse_events(payload: dict) -> list[CSEvent]:
    """只留 S/A 级、正在进行或即将开始的赛事。"""
    data = (payload or {}).get("data") or {}
    events = []
    for raw in data.get("items") or []:
        if not isinstance(raw, dict):
            continue
        info = raw.get("basic_info") or {}
        status = str(info.get("status") or "").strip()
        grade = _short_grade(info.get("grade_label"))
        if status not in ("live", "upcoming") or grade not in ("S级", "A级"):
            continue
        events.append(CSEvent(
            name=str(info.get("disp_name") or "未知赛事").strip(),
            grade=grade,
            status=status,
            start_date=_month_day(info.get("start_time")),
            end_date=_month_day(info.get("end_time")),
            city=str(info.get("city_name") or "").strip(),
            prize=str(info.get("bonus") or "").strip(),
        ))
    return events


# --------------------------------------------------------------------------
# 排版
# --------------------------------------------------------------------------


def _match_line(match: CSMatch) -> str:
    if match.status in ("live", "finished"):
        body = f"{match.team1} {match.score1}:{match.score2} {match.team2}"
    else:
        body = f"{match.team1} vs {match.team2}"
    meta = match.grade
    if match.tournament:
        meta += f" · {match.tournament}"
    if match.round_name:
        meta += f"（{match.round_name}）"
    if match.best_of and match.status == "upcoming":
        meta += f" {match.best_of}"
    if match.status == "upcoming":
        return f"· {match.start:%m-%d %H:%M} {body} ｜ {meta}"
    return f"· {body} ｜ {meta}"


def _event_line(event: CSEvent) -> str:
    when = event.start_date
    if event.end_date and event.end_date != event.start_date:
        when = f"{event.start_date}~{event.end_date}"
    parts = [
        f"{event.status_label}｜{event.name}（{event.grade}）",
        when,
        event.city,
        f"奖池 {event.prize}" if event.prize else "",
    ]
    return "· " + " ｜ ".join(part for part in parts if part)


def brief_text(matches: list[CSMatch], events: list[CSEvent],
               now: datetime.datetime | None = None) -> str:
    """「cs赛事」的文字版：进行中 + 即将开始 + 重点赛事。"""
    now = now or datetime.datetime.now()
    live = sorted((m for m in matches if m.status == "live"), key=lambda m: m.start)
    # 「TBD vs TBD」是还没出线的占位赛程，文字列表里直接跳过，省得满屏 TBD。
    upcoming = sorted(
        (
            m for m in matches
            if m.status == "upcoming" and not (m.team1 == "TBD" and m.team2 == "TBD")
        ),
        key=lambda m: m.start,
    )

    lines = [f"CS2 赛事 · {now:%m-%d %H:%M}"]
    if live:
        lines.append("")
        lines.append(f"【进行中 {len(live)} 场】")
        lines.extend(_match_line(m) for m in live[:CS_LIVE_LIMIT])
    if upcoming:
        lines.append("")
        if len(upcoming) > CS_MATCH_LIMIT:
            lines.append(
                f"【即将开始·共 {len(upcoming)} 场，列最近 {CS_MATCH_LIMIT} 场】"
            )
        else:
            lines.append(f"【即将开始·共 {len(upcoming)} 场】")
        lines.extend(_match_line(m) for m in upcoming[:CS_MATCH_LIMIT])
    if events:
        lines.append("")
        lines.append("【S/A 级赛事】")
        for event in events[:CS_EVENT_LIMIT]:
            lines.append(_event_line(event))
    if not live and not upcoming and not events:
        lines.append("")
        lines.append("5EPlay 那边暂时没有 S/A 级的赛程数据……过一会儿再试？")
    lines.append("")
    lines.append(f"数据：5EPlay · {CS_LINK}")
    return "\n".join(lines)


def results_text(matches: list[CSMatch],
                 now: datetime.datetime | None = None) -> str:
    """「赛果」的文字版：按日期分组，最近的在上面。"""
    now = now or datetime.datetime.now()
    finished = sorted(
        (m for m in matches if m.status == "finished"),
        key=lambda m: m.start,
        reverse=True,
    )[:CS_RESULT_LIMIT]
    lines = [f"CS2 赛果 · {now:%m-%d %H:%M}"]
    if not finished:
        lines.append("")
        lines.append("最近没有 S/A 级的完赛记录。")
    else:
        current_date = ""
        for match in finished:
            date = match.start.strftime("%m-%d")
            if date != current_date:
                lines.append("")
                lines.append(f"【{date}】")
                current_date = date
            meta = match.grade
            if match.tournament:
                meta += f" · {match.tournament}"
            if match.round_name:
                meta += f"（{match.round_name}）"
            lines.append(
                f"· {match.start:%H:%M} {match.team1} {match.score1}:{match.score2} "
                f"{match.team2} ｜ {meta}"
            )
    lines.append("")
    lines.append(f"数据：5EPlay · {CS_LINK}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 取数
# --------------------------------------------------------------------------


class CS:
    """取数 + 拼文字。``fetch`` 可注入（自检时塞假数据，不联网）。"""

    def __init__(self, fetch=None, timeout: float = CS_TIMEOUT) -> None:
        self._fetch = fetch or http_json
        self.timeout = timeout

    async def _request(self, method: str, url: str,
                       payload: dict | None = None) -> dict:
        return await asyncio.to_thread(
            self._fetch, method, url, payload, dict(CS_HEADERS), self.timeout
        )

    async def _matches_payload(self, game_status: int) -> dict:
        query = urllib.parse.urlencode({
            "game_status": game_status,
            "game_type": 1,
            "grades": CS_GRADES,
            "page": 1,
            "limit": 50,
        })
        return await self._request("GET", f"{CS_MATCH_API}?{query}")

    async def _events_payload(self) -> dict:
        now = datetime.datetime.now()
        options = {
            "cursor": "",
            "player_id": "",
            "time_value": (
                f"{now - datetime.timedelta(days=1):%Y-%m-%d 00:00:00}_"
                f"{now + datetime.timedelta(days=30):%Y-%m-%d 23:59:59}"
            ),
            "team_id": "",
            "time_type": "self",
            "tt_series": [],
            "grade": [],
            "tt_bonus": [],
            "page_token": "",
        }
        return await self._request("POST", CS_EVENT_API, {"tournaments_options": options})

    @staticmethod
    def _checked(payload: dict) -> dict:
        """接口用 ``success``/``errcode`` 表示成败；失败就抛，让调用方决定怎么兜。"""
        if not isinstance(payload, dict):
            raise RuntimeError("5EPlay 返回了看不懂的数据")
        if not payload.get("success"):
            raise RuntimeError(str(payload.get("message") or "5EPlay 接口返回失败"))
        return payload

    async def matches_data(self) -> tuple[list[CSMatch], list[CSEvent], list[str]]:
        """「cs赛事」原始数据：赛程和赛事列表并行拉，一边挂了另一边还能出。

        返回 ``(比赛, 赛事, 没拉到的部分)``；两边都挂就抛异常。
        """
        results = await asyncio.gather(
            self._matches_payload(1), self._events_payload(), return_exceptions=True
        )
        matches: list[CSMatch] = []
        events: list[CSEvent] = []
        failed: list[str] = []
        for name, payload, parser in (
            ("赛程", results[0], parse_matches),
            ("赛事", results[1], parse_events),
        ):
            if isinstance(payload, Exception):
                log(f"[CS] {name}拉取失败：{payload!r}")
                failed.append(name)
                continue
            try:
                parsed = parser(self._checked(payload))
            except Exception as error:  # noqa: BLE001 - 数据坏了也要给个说法
                log(f"[CS] {name}解析失败：{error!r}")
                failed.append(name)
                continue
            if name == "赛程":
                matches = parsed
            else:
                events = parsed
        if len(failed) == 2:
            raise RuntimeError("5EPlay 的赛程和赛事接口都没响应")
        return matches, events, failed

    async def results_data(self) -> list[CSMatch]:
        payload = await self._matches_payload(2)
        return parse_matches(self._checked(payload))

    async def matches_report(self) -> str:
        matches, events, failed = await self.matches_data()
        text = brief_text(matches, events)
        if failed:
            text += f"\n（{'、'.join(failed)}没拉到，过一会儿再试）"
        return text

    async def results_report(self) -> str:
        return results_text(await self.results_data())

