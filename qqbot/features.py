"""功能列表、群友画像、名单、打卡、每日运势、老婆图。

依赖 base/config；都是被 Handler 调用的独立小功能。
"""
from __future__ import annotations

from .base import *  # noqa: F401,F403


# --------------------------------------------------------------------------
# 功能列表 / 更新日志
# --------------------------------------------------------------------------

# 正文一次发多少字、最多发几条（和原插件 config 的默认值一致）
CHANGELOG_CHARS = int(os.getenv("QQCHATBOT_CHANGELOG_CHARS", "").strip() or 1500)
CHANGELOG_MAX_MESSAGES = int(
    os.getenv("QQCHATBOT_CHANGELOG_MAX_MESSAGES", "").strip() or 8
)
DOC_COMMANDS = ("功能列表", "更新日志")
DOC_EMPTY_REPLY = {
    "功能列表": "哼，我还没写好功能列表呢，等写好了再给你看～",
    "更新日志": "哼，我还没写过更新日志呢，等写好了再给你看～",
}
DOC_TRUNCATED_REPLY = "……后面的太长了，我懒得念完，先到这儿吧。"
DOC_FILES = {"功能列表": "help.txt", "更新日志": "changelog.txt"}


def load_text_file(path: Path) -> str:
    """读一个由人维护的文本文件（去掉首尾空白）。

    用 ``utf-8-sig``：Windows 上记事本/PowerShell 写出来的文件常带 BOM，
    不认 BOM 的话发到群里第一行会多一个看不见的怪字符。
    文件不存在、读不出来、内容为空都返回空串，由调用方给兜底文案。
    """
    try:
        return path.read_text(encoding="utf-8-sig").strip()
    except FileNotFoundError:
        log(f"[文本] 还没有这个文件：{path}")
        return ""
    except OSError as error:
        log(f"[文本] 读取失败：{path} —— {error}")
        return ""


def split_changelog(text: str, limit: int, max_messages: int) -> tuple[list[str], bool]:
    """把正文切成能发的片段，返回 ``(片段列表, 是否被截掉)``。

    切片是字符级无损的：``"".join(片段) == text``。断开位置优先落在换行之后
    （整行超长才硬切），片段数封顶 ``max_messages``，被截掉的部分由调用方补说明。
    """
    limit = max(int(limit), 1)
    max_messages = max(int(max_messages), 1)
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + limit
        if end >= len(text):
            chunks.append(text[start:])
            break
        cut = text.rfind(chr(10), start + 1, end)
        if cut == -1:
            cut = end
        else:
            cut += 1
        chunks.append(text[start:cut])
        start = cut
    dropped = len(chunks) > max_messages
    return chunks[:max_messages], dropped


# --------------------------------------------------------------------------
# 群友画像（长期记忆）
# --------------------------------------------------------------------------

# 攒够多少条发言才总结一次、两次总结之间至少隔多久
MEMORY_SUMMARIZE_EVERY = int(os.getenv("QQCHATBOT_MEMORY_SUMMARIZE_EVERY", "").strip() or 25)
MEMORY_SUMMARIZE_COOLDOWN = float(
    os.getenv("QQCHATBOT_MEMORY_SUMMARIZE_COOLDOWN", "").strip() or 600
)
MEMORY_SAMPLES = int(os.getenv("QQCHATBOT_MEMORY_SAMPLES", "").strip() or 40)

SUMMARIZE_PROMPT = (
    "你是群聊记录整理助手。下面是一位群成员的发言样本，可能还附带一份旧画像。" + chr(10)
    + "请输出更新后的画像，2~3 句话，包含：说话风格（语气、口头禅、常用词）、"
    "关心或常聊的话题、以及和其他群友互动的特点。" + chr(10)
    + "只描述能观察到的语言习惯；不要评价外貌、不做道德评判、不写贬损或臆测隐私的内容，"
    "也不要写“这个人可能……”这类猜测。直接输出画像正文，不要任何前缀或标题。"
)


class Profiles:
    """每个 (群, 人) 的长期画像：攒发言 → 后台让模型总结 → 落盘。

    和原插件 memory.py 的长期层一个思路，但键用 ``member_openid``，
    存 ``data/profiles_official.json``，和 NapCat 那边互不影响。

    只有**被 @ 到的消息**才进样本 —— 闲聊不该被拿去画像（原插件默认也是这个范围）。
    """

    def __init__(self, data_dir: Path) -> None:
        self.file = data_dir / "profiles_official.json"
        payload = {}
        try:
            payload = json.loads(self.file.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            payload = {}
        self.records: dict[str, dict[str, dict]] = {}
        if isinstance(payload, dict):
            for group, members in payload.items():
                if isinstance(members, dict):
                    self.records[str(group)] = {
                        str(user): record for user, record in members.items()
                        if isinstance(record, dict)
                    }
        self._samples: dict[tuple[str, str], deque[str]] = {}
        self._pending: dict[tuple[str, str], int] = {}
        self._last_at: dict[tuple[str, str], float] = {}

    def summary_of(self, group: str, user: str) -> str:
        record = (self.records.get(group) or {}).get(user) or {}
        return str(record.get("summary") or "").strip()

    def remember(self, group: str, user: str, name: str, text: str) -> None:
        text = " ".join((text or "").split())
        if not group or not user or not text:
            return
        key = (group, user)
        self._samples.setdefault(key, deque(maxlen=MEMORY_SAMPLES)).append(text[:200])
        self._pending[key] = self._pending.get(key, 0) + 1
        record = self.records.setdefault(group, {}).setdefault(user, {})
        record["name"] = name or user[:8]
        record["messages"] = int(record.get("messages") or 0) + 1

    def should_summarize(self, group: str, user: str) -> bool:
        key = (group, user)
        if self._pending.get(key, 0) < MEMORY_SUMMARIZE_EVERY:
            return False
        last = self._last_at.get(key)
        if last is not None and time.monotonic() - last < MEMORY_SUMMARIZE_COOLDOWN:
            return False
        return len(self._samples.get(key) or ()) >= 3

    def _save(self) -> None:
        temporary = self.file.with_name("profiles_official.tmp")
        try:
            temporary.write_text(
                json.dumps(self.records, ensure_ascii=False, indent=2) + chr(10),
                encoding="utf-8",
            )
            temporary.replace(self.file)
        except OSError as error:
            log(f"[画像] 保存失败：{error}")

    async def summarize(self, group: str, user: str, chat) -> bool:
        """后台总结一个人的画像。失败只记日志，绝不把异常抛给调用方。"""
        key = (group, user)
        samples = list(self._samples.get(key) or ())
        if len(samples) < 3:
            return False
        name = ((self.records.get(group) or {}).get(user) or {}).get("name") or user[:8]
        previous = self.summary_of(group, user)
        # 先记时间、清零计数：就算这次失败，也不会马上又触发一次
        self._last_at[key] = time.monotonic()
        self._pending[key] = 0
        content = (
            (f"【旧画像】{previous}" + chr(10) if previous else "")
            + f"【{name} 最近的发言】" + chr(10)
            + chr(10).join(f"- {line}" for line in samples)
        )
        try:
            summary = await chat(SUMMARIZE_PROMPT, content, images=None)
        except Exception as error:  # noqa: BLE001 - 后台任务不能把异常抛回事件循环
            log(f"[画像] 总结「{name}」失败：{error!r}")
            return False
        summary = (summary or "").strip()
        if not summary:
            log(f"[画像] 「{name}」总结出空结果，保留旧画像")
            return False
        record = self.records.setdefault(group, {}).setdefault(user, {})
        record["name"] = name
        record["summary"] = summary
        record["updated_at"] = int(time.time())
        self._save()
        log(f"[画像] 已更新「{name}」：{summary[:60]}")
        return True

    def forget(self, group: str, user: str) -> bool:
        key = (group, user)
        removed = self._samples.pop(key, None) is not None
        self._pending.pop(key, None)
        self._last_at.pop(key, None)
        group_records = self.records.get(group)
        if group_records and group_records.pop(user, None) is not None:
            removed = True
        if removed:
            self._save()
        return removed


# --------------------------------------------------------------------------
# 群成员名册（@ 人用）
# --------------------------------------------------------------------------


class Roster:
    """记住每个群里见过的人：member_openid → 群名片。

    官方**没有**（也没开放）群成员列表接口，所以只能用「见过的算数」：
    全量消息模式下每条群消息都带 ``author.member_openid`` 和 ``username``，
    攒起来就够 @ 人了。落在 data/members_official.json，重启不丢。

    键是 openid，和 NapCat 那边 ``data/members.json``（画像）互不影响。
    """

    def __init__(self, data_dir: Path) -> None:
        self.file = data_dir / "members_official.json"
        try:
            payload = json.loads(self.file.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            payload = {}
        self.records: dict[str, dict[str, str]] = {}
        if isinstance(payload, dict):
            for group, members in payload.items():
                if isinstance(members, dict):
                    self.records[str(group)] = {
                        str(user): str(name) for user, name in members.items()
                        if isinstance(name, str)
                    }
        self._dirty = False
        self._last_save = 0.0

    def remember(self, group: str, user: str, name: str) -> None:
        if not group or not user:
            return
        members = self.records.setdefault(group, {})
        if members.get(user) != name:
            members[user] = name
            self._dirty = True

    def save(self, force: bool = False) -> None:
        """攒够 5 秒或强制时才落盘，免得每条消息都写一遍。"""
        if not self._dirty:
            return
        if not force and time.time() - self._last_save < 5:
            return
        temporary = self.file.with_name("members_official.tmp")
        try:
            temporary.write_text(
                json.dumps(self.records, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.file)
            self._dirty = False
            self._last_save = time.time()
        except OSError as error:
            log(f"[名册] 保存失败：{error}")

    def members(self, group: str) -> list[tuple[str, str]]:
        return list(self.records.get(group, {}).items())


# --------------------------------------------------------------------------
# 打卡 / 签到
# --------------------------------------------------------------------------


class Attendance:
    """按月记账的打卡次数，落在 data/attendance.json。

    键是 ``群:人:YYYY-MM``。官方版用 openid 拼键，和 NapCat 版那套数字 QQ 号
    不会撞，所以这份文件两版可以共用。
    """

    def __init__(self, data_dir: Path) -> None:
        self.file = data_dir / "attendance.json"
        self.records: dict[str, int] = {}
        try:
            payload = json.loads(self.file.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            payload = {}
        records = payload.get("records") if isinstance(payload, dict) else {}
        if isinstance(records, dict):
            self.records = {str(k): int(v) for k, v in records.items()
                            if isinstance(v, (int, float))}

    def _save(self) -> None:
        temporary = self.file.with_name("attendance.tmp")
        try:
            temporary.write_text(
                json.dumps({"records": self.records}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.file)
        except OSError as error:
            log(f"[打卡] 记录保存失败：{error}")

    def record(self, group: str, user: str) -> int:
        month = datetime.date.today().strftime("%Y-%m")
        key = f"{group}:{user}:{month}"
        count = int(self.records.get(key, 0)) + 1
        self.records[key] = count
        self._save()
        return count


LUCK_FLAVOR = {
    "大吉": "想什么都成，别浪费了。",
    "中吉": "稳稳当当的一天。",
    "小吉": "小的也算吉，别嫌少。",
    "吉": "平平常常，也还行吧。",
    "末吉": "末等的吉也是吉，拿着。",
    "凶": "……唔，今天就别乱来了。",
    "大凶": "别出门了，真的。",
}
LUCK_ADVICE = {
    "大吉": ("抽卡、开箱、表白", "跟小鲸鱼顶嘴"),
    "中吉": ("抽卡、攒碎片", "熬夜"),
    "小吉": ("抽卡", "乱花碎片"),
    "吉": ("签到、聊天", "想太多"),
    "末吉": ("先攒着", "冲动开箱"),
    "凶": ("安静待着", "抽卡"),
    "大凶": ("缩在被窝里", "出门、抽卡、说话"),
}


class DailyLuck:
    """每日运势：data/daily_luck/daily_luck.json（等级 → 图片文件名）。

    按 (群, 人, 日期) 定死：同一个人同一天永远是同一档，重启也不会变。
    """

    def __init__(self, data_dir: Path) -> None:
        self.directory = data_dir / "daily_luck"
        try:
            payload = json.loads(
                (self.directory / "daily_luck.json").read_text(encoding="utf-8-sig")
            )
        except (OSError, ValueError):
            payload = {}
        self.records = {
            str(name): str(filename)
            for name, filename in (payload.items() if isinstance(payload, dict) else [])
            if isinstance(filename, str) and filename
        }

    def options(self) -> list[str]:
        return [
            name for name, filename in self.records.items()
            if (self.directory / filename).is_file()
        ]

    def today(self, group: str, user: str) -> str | None:
        options = self.options()
        if not options:
            return None
        seed = f"luck:{group}:{user}:{datetime.date.today().isoformat()}"
        return random.Random(seed).choice(options)

    def image(self, name: str) -> Path | None:
        filename = self.records.get(name)
        if not filename:
            return None
        path = self.directory / filename
        return path if path.is_file() else None

    @staticmethod
    def flavor(name: str) -> str:
        return LUCK_FLAVOR.get(name, f"今天的运势是 {name}。")

    @staticmethod
    def advice(name: str) -> tuple[str, str]:
        return LUCK_ADVICE.get(name, ("抽卡", "开箱"))


def save_wife_image(data_dir: Path, image: ImageRef, name: str | None) -> bool:
    """把某张图片存进 data/wife；给了名字就记进 records.json。

    文件名一律用时间戳（和原插件一致），名字只存在 records.json 里 ——
    这样改名/重名都不会在磁盘上留下奇怪的文件名。
    """
    directory = data_dir / "wife"
    records_file = directory / "records.json"
    extension = Path(image.filename).suffix or ".jpg"
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    target = directory / f"{stamp}{extension}"
    try:
        data = fetch_bytes(image.url)
        if not data:
            log("[老婆] 下载到空内容")
            return False
        target.write_bytes(data)
    except (OSError, urllib.error.URLError, ValueError) as error:
        log(f"[老婆] 保存失败：{error!r}")
        return False
    if name is None:
        log(f"[老婆] 已保存（无名字）：{target}")
        return True

    try:
        records = json.loads(records_file.read_text(encoding="utf-8-sig"))
        if not isinstance(records, dict):
            records = {}
    except (OSError, ValueError):
        records = {}
    records[name] = target.name
    temporary = records_file.with_name("records.tmp")
    try:
        temporary.write_text(
            json.dumps(records, ensure_ascii=False, indent=2) + chr(10),
            encoding="utf-8",
        )
        temporary.replace(records_file)
    except OSError as error:
        log(f"[老婆] 记录保存失败：{error}")
        target.unlink(missing_ok=True)
        return False
    log(f"[老婆] 已保存：「{name}」→ {target.name}")
    return True


def random_wife(data_dir: Path) -> tuple[Path | None, str | None]:
    """从 data/wife 里随机抽一张，顺便查它的名字（records.json 反查）。"""
    directory = data_dir / "wife"
    if not directory.is_dir():
        return None, None
    files = [
        path for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    ]
    if not files:
        return None, None
    path = random.choice(files)
    try:
        records = json.loads((directory / "records.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        records = {}
    names = {
        str(filename): str(name)
        for name, filename in (records.items() if isinstance(records, dict) else [])
    }
    return path, names.get(path.name)
