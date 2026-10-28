"""抽卡 / 开箱 / 库存与卡池。

依赖 base/config；Handler 调这里的方法，卡池数据在 data/card/。
"""
from __future__ import annotations

from .base import *  # noqa: F401,F403


# --------------------------------------------------------------------------
# 抽卡 / 开箱
# --------------------------------------------------------------------------

# 卡池目录（和原插件 config.CARD_DIRS 一致）；"始源"只从箱子里出。
# 卡池都在 data/card/ 下面（2026-10-20 收进一个目录，省得 data 根目录被卡池淹了）
CARD_ROOT = "card"
CARD_DIRS = {
    "rare": "rare_card",
    "epic": "epic_card",
    "myth": "myth_card",
    "legend": "legend_card",
    "origin": "box_card",
}
LIMITED_CARD_DIRNAME = "limited_card"
CARD_LABELS = {
    "rare": "稀有", "epic": "史诗", "myth": "神话", "legend": "传奇",
    "origin": "始源", "limited": "限定",
}
# 库存图里各档的排列顺序：限定卡最特殊，紧跟在始源后面（两种库存视图都会列）。
CARD_GROUP_ORDER = ("origin", "limited", "legend", "myth", "epic", "rare")
CARD_PROBABILITIES = {"rare": 0.45, "epic": 0.35, "myth": 0.15, "legend": 0.05}
# 库存图里各档的徽章色（前五档和原插件 checkin_card.RARITY_BADGE 一致；限定是这边新加的紫色）
CARD_BADGE_COLORS = {
    "origin": (198, 74, 42),
    "limited": (139, 74, 176),
    "legend": (214, 62, 120),
    "myth": (233, 146, 47),
    "epic": (150, 100, 214),
    "rare": (106, 140, 194),
    "book": (94, 129, 172),
}
CARD_BADGE_FALLBACK = (150, 142, 158)
# 硬保底：连续 14 抽没神话，第 15 抽必出；连续 29 抽没传奇，第 30 抽必出。
CARD_MYTH_PITY = 15
CARD_LEGEND_PITY = 30
# 重复卡折算成奶龙碎片（库存不叠加）。
CARD_DUPLICATE_SHARDS = {"rare": 10, "epic": 20, "myth": 150, "legend": 500}
# 开箱：500 碎片一次，5% 始源卡 / 20% 附魔书 / 75% 碎片（100-300）。
CARD_BOX_COST = 500
CARD_BOX_CARD_PROBABILITY = 0.05
CARD_BOX_BOOK_PROBABILITY = 0.20
CARD_BOX_SHARDS = (100, 300)
CARD_BOX_TEN_COUNT = 10
ENCHANT_BOOKS = ("经验修补", "重构", "时运", "升格", "保护", "掠夺")
# 固定命令：任何时候都认（和原插件的「查看库存」等一致）
CARD_COMMANDS = ("抽卡", "开箱", "十连开箱", "查看库存", "查看全部库存")
# 今日猫娘 / 随机老婆（都发 data/wife 里的图）
WIFE_COMMANDS = ("随机猫娘", "今日猫娘", "随机老婆")
DRAWS_PER_DAY = 5
# 签到奖励：每天第一次 200-400 碎片
CARD_CHECK_IN_SHARDS = (200, 400)


@dataclass
class CardReply:
    text: str
    image: Path | None = None


class Cards:
    """抽卡 / 开箱 / 库存，数据落在 data/card_users.json。

    和原插件一样按**用户**记账（官方这边键是 member_openid，和 NapCat 那边的
    QQ 号互不干扰）。重复卡不叠加，一律折成奶龙碎片。
    """

    def __init__(self, data_dir: Path, filename: str = "card_users_official.json") -> None:
        self.data = data_dir
        # 官方版单独一份文件：和 NapCat 版共用一份的话，两个进程各读一遍再整份写回，
        # 后写的会把先写的改动盖掉。键本来也不一样（openid vs QQ 号），分开更省心。
        self.users_file = data_dir / filename
        if not self.users_file.is_file():
            self._migrate_shared(data_dir)
        self._users = self._load_json(self.users_file)
        self._pools = self._load_pools()
        self._limited = self._load_limited_names()

    def _migrate_shared(self, data_dir: Path) -> None:
        """第一次启动时，把共用文件里属于官方版的记录（键不是纯数字）搬过来。"""
        shared = data_dir / "card_users.json"
        if not shared.is_file():
            return
        payload = self._load_json(shared)
        official = {
            str(key): value for key, value in payload.items()
            if not str(key).isdigit() and isinstance(value, dict)
        }
        if not official:
            return
        try:
            self.users_file.write_text(
                json.dumps(official, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as error:
            log(f"[抽卡] 迁移官方记录失败：{error}")
            return
        log(f"[抽卡] 已从 card_users.json 迁出 {len(official)} 个官方用户到 {self.users_file.name}")

    @staticmethod
    def _load_json(path: Path) -> dict:
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _load_pools(self) -> dict[str, list[tuple[str, Path]]]:
        pools: dict[str, list[tuple[str, Path]]] = {}
        for rarity, folder in CARD_DIRS.items():
            directory = self.data / CARD_ROOT / folder
            records = self._load_json(directory / "cards.json")
            pools[rarity] = [
                (str(name), directory / str(filename))
                for name, filename in records.items()
                if isinstance(name, str) and isinstance(filename, str)
                and (directory / filename).is_file()
            ]
        return pools

    def _load_limited_names(self) -> set[str]:
        """限定卡名单：只认 cards.json 里的卡名。

        限定卡有的只有名字没有图（值是 ``null``），所以不能像普通卡池那样按
        「文件存在」过滤 —— 只要名字在，库存里就得列出来。
        """
        directory = self.data / CARD_ROOT / LIMITED_CARD_DIRNAME
        records = self._load_json(directory / "cards.json")
        return {str(name) for name in records}

    def _save(self) -> None:
        temporary = self.users_file.with_name("card_users.tmp")
        try:
            temporary.write_text(
                json.dumps(self._users, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.users_file)
        except OSError as error:
            log(f"[抽卡] 记录保存失败：{error}")

    def user(self, user_id: str) -> dict:
        today = datetime.date.today().isoformat()
        record = self._users.setdefault(
            str(user_id), {"date": today, "draws": DRAWS_PER_DAY, "inventory": {}}
        )
        if record.get("date") != today:
            record["date"] = today
            record["draws"] = DRAWS_PER_DAY
        for key, default in (
            ("inventory", {}), ("shards", 0), ("books", {}),
            ("since_myth", 0), ("since_legend", 0),
        ):
            record.setdefault(key, default)
        return record

    @staticmethod
    def _pick_rarity() -> str:
        value = random.random()
        total = 0.0
        for rarity, probability in CARD_PROBABILITIES.items():
            total += probability
            if value < total:
                return rarity
        return "legend"

    def _pity_rarity(self, record: dict) -> str | None:
        """保底到期就返回强制品质；两档同时到期优先给更稀的传奇。"""
        if int(record.get("since_legend", 0)) >= CARD_LEGEND_PITY - 1:
            return "legend"
        if int(record.get("since_myth", 0)) >= CARD_MYTH_PITY - 1:
            return "myth"
        return None

    @staticmethod
    def _advance_pity(record: dict, rarity: str) -> None:
        record["since_myth"] = 0 if rarity == "myth" else int(record.get("since_myth", 0)) + 1
        record["since_legend"] = 0 if rarity == "legend" else int(record.get("since_legend", 0)) + 1

    def find_card_image(self, name: str) -> Path | None:
        """按名字查卡池里的图（「发送吊图 卡名」的回退用）。

        先翻全部卡池（稀有/史诗/神话/传奇/始源），再找限定卡 —— 限定卡有的只有
        名字没有图，所以必须真的存在文件才算命中。不做模糊匹配。
        """
        for entries in self._pools.values():
            for card_name, path in entries:
                if card_name == name:
                    return path
        directory = self.data / CARD_ROOT / LIMITED_CARD_DIRNAME
        records = self._load_json(directory / "cards.json")
        filename = records.get(name)
        if isinstance(filename, str):
            path = directory / filename
            if path.is_file():
                return path
        return None

    # ---- 抽卡 ----

    def draw(self, user_id: str) -> CardReply:
        record = self.user(user_id)
        if int(record["draws"]) <= 0:
            self._save()
            return CardReply(
                "等等，一次也不剩了，你还想抽卡？！明天记得攒够次数再来哦。"
                "我可不给空手的人开后门～"
            )
        record["draws"] = int(record["draws"]) - 1
        rarity = self._pity_rarity(record) or self._pick_rarity()
        pool = self._pools.get(rarity) or []
        if not pool:
            # 这一档没配卡：次数退回，也不算作一抽
            record["draws"] = int(record["draws"]) + 1
            self._save()
            return CardReply(f"{CARD_LABELS[rarity]}这一档还没配卡，这次机会退给你了。")

        self._advance_pity(record, rarity)
        name, image = random.choice(pool)
        if int(record["inventory"].get(name, 0)) > 0:
            amount = CARD_DUPLICATE_SHARDS.get(rarity, 0)
            record["shards"] = int(record["shards"]) + amount
            line = f"又是「{name}」……重复的，我给你折成奶龙碎片 +{amount}。"
        else:
            record["inventory"][name] = 1
            line = f"抽到了！{CARD_LABELS[rarity]}「{name}」——收好了，别弄丢。"
        remaining = int(record["draws"])
        self._save()
        return CardReply(f"{line}\n今天还剩 {remaining} 次抽卡机会。", image)

    def draw_all(self, user_id: str) -> list[dict]:
        """把今天剩下的次数一次用完（签到用），返回抽到的卡名列表。"""
        record = self.user(user_id)
        drawn: list[dict] = []
        while int(record["draws"]) > 0:
            record["draws"] = int(record["draws"]) - 1
            rarity = self._pity_rarity(record) or self._pick_rarity()
            pool = self._pools.get(rarity) or []
            if not pool:
                record["draws"] = int(record["draws"]) + 1
                break
            self._advance_pity(record, rarity)
            name, _ = random.choice(pool)
            is_new = int(record["inventory"].get(name, 0)) <= 0
            if is_new:
                record["inventory"][name] = 1
            else:
                record["shards"] = int(record["shards"]) + CARD_DUPLICATE_SHARDS.get(rarity, 0)
            drawn.append({"name": name, "rarity": rarity, "is_new": is_new})
        self._save()
        return drawn

    def grant_check_in_shards(self, user_id: str) -> int | None:
        """每天第一次签到给 200-400 碎片；当天第二次返回 None。"""
        record = self.user(user_id)
        today = datetime.date.today().isoformat()
        if record.get("last_check_in") == today:
            self._save()
            return None
        amount = random.randint(*CARD_CHECK_IN_SHARDS)
        record["shards"] = int(record["shards"]) + amount
        record["last_check_in"] = today
        self._save()
        return amount

    # ---- 碎片 / 附魔书（锻造用） ----

    def shards_of(self, user_id: str) -> int:
        """这个人现在有多少奶龙碎片。"""
        return int(self.user(user_id)["shards"])

    def spend_shards(self, user_id: str, amount: int) -> int | None:
        """扣碎片；不够返回 None（一分不扣），够就返回扣完还剩多少。"""
        record = self.user(user_id)
        shards = int(record["shards"])
        if shards < amount:
            self._save()
            return None
        record["shards"] = shards - amount
        self._save()
        return int(record["shards"])

    def spend_shards_or_free(self, user_id: str, amount: int) -> tuple[int, int]:
        """够就扣，不够就免费（石剑专用）。返回 ``(实扣, 剩余)``。"""
        record = self.user(user_id)
        shards = int(record["shards"])
        if shards >= amount:
            record["shards"] = shards - amount
            paid = amount
        else:
            paid = 0
        self._save()
        return paid, int(record["shards"])

    def grant_shards(self, user_id: str, amount: int) -> int:
        """发碎片，返回发完的总数。"""
        record = self.user(user_id)
        record["shards"] = int(record["shards"]) + max(0, int(amount))
        self._save()
        return int(record["shards"])

    def books_of(self, user_id: str) -> dict[str, int]:
        """这个人手里的附魔书（按 ENCHANT_BOOKS 顺序，只留数量大于 0 的）。"""
        books = self.user(user_id).get("books") or {}
        order = {name: index for index, name in enumerate(ENCHANT_BOOKS)}
        items = [
            (str(name), int(count))
            for name, count in books.items()
            if int(count) > 0
        ]
        items.sort(key=lambda item: (order.get(item[0], len(order)), item[0]))
        return dict(items)

    def consume_book(self, user_id: str, name: str) -> bool:
        """用掉一本附魔书；没有就返回 False（什么都不改）。"""
        record = self.user(user_id)
        books = record.setdefault("books", {})
        count = int(books.get(name, 0))
        if count <= 0:
            self._save()
            return False
        if count <= 1:
            books.pop(name, None)
        else:
            books[name] = count - 1
        self._save()
        return True

    # ---- 开箱 ----

    def _roll_box(self, record: dict) -> dict:
        pool = self._pools.get("origin") or []
        roll = random.random()
        if roll < CARD_BOX_CARD_PROBABILITY and pool:
            # 完全随机抽一张始源卡：抽到已有的就按重复卡折碎片（不再优先没出过的）。
            name, image = random.choice(pool)
            if int(record["inventory"].get(name, 0)) <= 0:
                record["inventory"][name] = 1
                return {"kind": "card", "name": name, "image": image}
            amount = random.randint(*CARD_BOX_SHARDS)
            record["shards"] = int(record["shards"]) + amount
            return {"kind": "duplicate", "name": name, "amount": amount}
        if roll < CARD_BOX_CARD_PROBABILITY + CARD_BOX_BOOK_PROBABILITY and ENCHANT_BOOKS:
            book = random.choice(ENCHANT_BOOKS)
            books = record.setdefault("books", {})
            books[book] = int(books.get(book, 0)) + 1
            return {"kind": "book", "name": book}
        amount = random.randint(*CARD_BOX_SHARDS)
        record["shards"] = int(record["shards"]) + amount
        return {"kind": "shards", "amount": amount}

    @staticmethod
    def _describe_box(result: dict) -> str:
        kind = result["kind"]
        if kind == "card":
            return f"开出来一张始源卡「{result['name']}」！运气不错嘛。"
        if kind == "duplicate":
            return (
                f"又是「{result['name']}」……这张你有了，折成奶龙碎片 +{result['amount']}。"
            )
        if kind == "book":
            return f"开出一本附魔书「{result['name']}」，锻造的时候能贴上。"
        return f"开出一堆奶龙碎片，+{result['amount']}。"

    def open_box(self, user_id: str) -> CardReply:
        record = self.user(user_id)
        shards = int(record["shards"])
        if shards < CARD_BOX_COST:
            self._save()
            return CardReply(
                f"开箱子要 {CARD_BOX_COST} 奶龙碎片，你手里只有 {shards}。"
                "先去抽卡攒点重复卡吧，我可不做无本买卖。"
            )
        record["shards"] = shards - CARD_BOX_COST
        result = self._roll_box(record)
        left = int(record["shards"])
        self._save()
        return CardReply(f"{self._describe_box(result)}\n奶龙碎片余额 {left}。", result.get("image"))

    def open_ten(self, user_id: str) -> CardReply:
        record = self.user(user_id)
        cost = CARD_BOX_COST * CARD_BOX_TEN_COUNT
        shards = int(record["shards"])
        if shards < cost:
            self._save()
            return CardReply(
                f"十连开箱要 {cost} 奶龙碎片，你手里只有 {shards}。"
                "先去多抽几次卡攒碎片吧，别在这儿耍赖。"
            )
        record["shards"] = shards - cost
        results = [self._roll_box(record) for _ in range(CARD_BOX_TEN_COUNT)]
        cards = [item["name"] for item in results if item["kind"] == "card"]
        duplicates = [item["name"] for item in results if item["kind"] == "duplicate"]
        books: dict[str, int] = {}
        for item in results:
            if item["kind"] == "book":
                books[item["name"]] = books.get(item["name"], 0) + 1
        gained = sum(item.get("amount", 0) for item in results
                     if item["kind"] in {"duplicate", "shards"})
        left = int(record["shards"])
        self._save()

        lines = [f"十个箱子开完了（花了 {cost} 碎片）："]
        if cards:
            lines.append("始源卡：" + "、".join(cards))
        if duplicates:
            lines.append("重复折碎片：" + "、".join(duplicates))
        if books:
            lines.append("附魔书：" + "、".join(f"{name}×{count}" for name, count in books.items()))
        lines.append(f"碎片回收 +{gained}")
        lines.append(f"奶龙碎片余额 {left}。")
        image = next((item["image"] for item in results if item["kind"] == "card"), None)
        return CardReply("\n".join(lines), image)

    # ---- 库存 ----

    def inventory_groups(
        self, user_id: str, show_all: bool = False
    ) -> tuple[list[tuple[str, tuple[int, int, int], list[str]]], int, int, int]:
        """整理库存：返回 (分组, 碎片, 卡总数, 被隐藏的种数)。

        分组是 ``[(档位名, 徽章色, [卡名…]), …]``，空的档位不出现；
        附魔书单独一组排在最后。限定卡两种视图都列（不是抽卡出的，攒到了就该看见）。
        """
        record = self.user(user_id)
        inventory = record["inventory"]
        shards = int(record["shards"])
        books = record["books"]
        rarity_by_name = {
            name: rarity for rarity, entries in self._pools.items() for name, _ in entries
        }
        # 限定卡不在普通卡池里，得单独认一下名字；和普通卡同名时以卡池的档位为准。
        highlight = {"origin", "limited", "legend", "myth"}
        grouped: dict[str, list[str]] = {}
        hidden = 0
        for name, count in sorted(inventory.items()):
            rarity = rarity_by_name.get(name)
            if rarity is None and name in self._limited:
                rarity = "limited"
            if rarity is None:
                continue
            if not show_all and rarity not in highlight:
                hidden += 1
                continue
            label = f"{name}×{count}" if int(count) > 1 else name
            grouped.setdefault(rarity, []).append(label)
        groups: list[tuple[str, tuple[int, int, int], list[str]]] = [
            (CARD_LABELS[rarity], CARD_BADGE_COLORS.get(rarity, CARD_BADGE_FALLBACK),
             grouped[rarity])
            for rarity in CARD_GROUP_ORDER
            if grouped.get(rarity)
        ]
        book_names = [
            f"{name}×{count}" for name, count in books.items() if int(count) > 0
        ]
        if book_names:
            groups.append(("附魔书", CARD_BADGE_COLORS["book"], book_names))
        total = sum(int(count) for count in inventory.values())
        return groups, shards, total, hidden

    def inventory_text(self, user_id: str, show_all: bool = False) -> str:
        record = self.user(user_id)
        inventory = record["inventory"]
        shards = int(record["shards"])
        books = record["books"]
        if not inventory and not books:
            self._save()
            return (
                "嗯……空的？你这是……出门忘带东西了？行吧行吧，先去弄点东西回来。"
                f"小鲸鱼在这儿等你，别等太久～\n奶龙碎片   *{shards}"
            )
        groups, shards, total, hidden = self.inventory_groups(user_id, show_all=show_all)
        lines = [f"{label}：" + "、".join(names) for label, _, names in groups]
        if hidden and not show_all:
            lines.append(f"（另有 {hidden} 种稀有/史诗没列出来，想看就发「查看全部库存」）")
        lines.append(f"共 {total} 张卡，奶龙碎片 *{shards}")
        self._save()
        return "\n".join(lines)
