import datetime
import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlencode


BOT_DIR = os.path.dirname(os.path.abspath(__file__))
PANDASCORE_MATCHES_URL = "https://api.pandascore.co/csgo/matches"
PANDASCORE_TOKEN_FILE = os.path.join(
    BOT_DIR,
    "pandascore_api.txt"
)


def _format_match_time(value):
    if not value:
        return "时间待定"

    try:
        parsed = datetime.datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone()
        return parsed.strftime("%m-%d %H:%M")
    except ValueError:
        return str(value)


def _match_date(match):
    value = match.get("begin_at")
    if not value:
        return None

    try:
        parsed = datetime.datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
    except ValueError:
        return None

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone()
    return parsed.date()


def _match_teams(match):
    opponents = match.get("opponents", [])
    if not isinstance(opponents, list):
        return []

    teams = []
    for opponent in opponents:
        if not isinstance(opponent, dict):
            continue
        team = opponent.get("opponent")
        if not isinstance(team, dict):
            continue
        team_id = team.get("id")
        team_name = team.get("name")
        if team_id is not None or team_name:
            teams.append((team_id, team_name or "待定"))
    return teams


def _match_scores(match):
    results = match.get("results", [])
    if not isinstance(results, list):
        return {}

    return {
        str(result["team_id"]): result.get("score", "?")
        for result in results
        if isinstance(result, dict) and result.get("team_id") is not None
    }


def _event_name(match):
    league = match.get("league")
    series = match.get("serie")
    tournament = match.get("tournament")

    league_name = league.get("name") if isinstance(league, dict) else None
    series_name = None
    if isinstance(series, dict):
        series_name = series.get("full_name") or series.get("name")
    tournament_name = (
        tournament.get("name") if isinstance(tournament, dict) else None
    )

    if league_name and series_name:
        return f"{league_name} {series_name}"
    return series_name or league_name or tournament_name or "赛事待定"


def _match_time_value(match, match_type):
    if match_type == "future":
        return match.get("scheduled_at") or match.get("begin_at")
    return match.get("end_at") or match.get("begin_at") or match.get("scheduled_at")


def _format_matches(title, matches, match_type, limit=None):
    lines = [title]
    selected_matches = matches if limit is None else matches[:limit]

    for match in selected_matches:
        if not isinstance(match, dict):
            continue

        teams = _match_teams(match)
        first_team = teams[0][1] if len(teams) > 0 else "待定"
        second_team = teams[1][1] if len(teams) > 1 else "待定"
        scores = _match_scores(match)
        first_score = (
            scores.get(str(teams[0][0]), "?")
            if len(teams) > 0 and teams[0][0] is not None
            else "?"
        )
        second_score = (
            scores.get(str(teams[1][0]), "?")
            if len(teams) > 1 and teams[1][0] is not None
            else "?"
        )
        event_name = _event_name(match)
        if match_type == "past":
            lines.append(
                f"{first_team} {first_score}:{second_score} "
                f"{second_team}  {event_name}"
            )
        else:
            lines.append(
                f"{first_team}：{second_team} {event_name} "
                f"{_format_match_time(_match_time_value(match, match_type))}"
            )

    if len(lines) == 1:
        lines.append("暂无比赛")
    return "\n".join(lines)


def _error_messages(previous_message, future_message=None):
    if future_message is None:
        future_message = previous_message
    return [
        f"之前 5 场 CS2 比赛：\n{previous_message}",
        f"未来 5 场 CS2 比赛：\n{future_message}",
    ]


def get_cs_matches():
    """查询并分别格式化当前时间之前和之后的 5 场 CS2 比赛。"""
    token = ""
    if os.path.exists(PANDASCORE_TOKEN_FILE):
        try:
            with open(
                PANDASCORE_TOKEN_FILE,
                "r",
                encoding="utf-8"
            ) as file:
                token = file.read().strip()
        except OSError as error:
            print(f"[CS比赛] API key 文件读取失败：{error}")

    if not token:
        token = os.environ.get("PANDASCORE_TOKEN", "").strip()

    if not token:
        print(
            f"[CS比赛] 未配置 API key，请创建："
            f"{PANDASCORE_TOKEN_FILE}"
        )
        return _error_messages(
            "比赛查询未配置 API key，请在 pandascore_api.txt 中填写"
        )

    def fetch_matches(path, sort):
        query = urlencode({"sort": sort, "per_page": "5"})
        request = urllib.request.Request(
            f"{PANDASCORE_MATCHES_URL}/{path}?{query}",
            headers={
                "User-Agent": "QQ-Ping-Pong-Bot",
                "Accept": "application/json",
                "Authorization": "Bearer " + token,
            }
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.load(response)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
            print(f"[CS比赛] {path} 查询失败：{error}")
            return None, "暂时查不到 CS2 比赛，请稍后再试"
        except json.JSONDecodeError as error:
            print(f"[CS比赛] {path} 返回数据不是有效 JSON：{error}")
            return None, "比赛数据格式异常，请稍后再试"

        matches = payload if isinstance(payload, list) else (
            payload.get("data") if isinstance(payload, dict) else None
        )
        if not isinstance(matches, list):
            return None, "比赛数据格式异常，请稍后再试"
        return matches, None

    previous_matches, previous_error = fetch_matches("past", "-begin_at")
    future_matches, future_error = fetch_matches("upcoming", "begin_at")
    if previous_matches is None or future_matches is None:
        return _error_messages(
            previous_error or "暂时没有查到 CS2 比赛",
            future_error or "暂时没有查到 CS2 比赛",
        )

    return [
        _format_matches(
            "之前 5 场 CS2 比赛：",
            previous_matches,
            "past",
            limit=5,
        ),
        _format_matches(
            "未来 5 场 CS2 比赛：",
            future_matches,
            "future",
            limit=5,
        ),
    ]
