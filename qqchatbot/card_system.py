"""Daily card drawing, card inventory, and card image management."""
import datetime
import json
import os
import random
import threading

from config import BOT_DIR
from media import send_group_message


CARD_DIRS = {
    "rare": os.path.join(BOT_DIR, "rare_card"),
    "epic": os.path.join(BOT_DIR, "epic_card"),
    "myth": os.path.join(BOT_DIR, "myth_card"),
    "legend": os.path.join(BOT_DIR, "legend_card"),
}
LIMITED_CARD_DIR = os.path.join(BOT_DIR, "limited_card")
LIMITED_CARD_FILE = os.path.join(LIMITED_CARD_DIR, "cards.json")
CARD_LABELS = {
    "rare": "稀有",
    "epic": "史诗",
    "myth": "神话",
    "legend": "传奇",
}
CARD_PROBABILITIES = {
    "rare": 0.45,
    "epic": 0.35,
    "myth": 0.15,
    "legend": 0.05,
}
CARD_STAGE_MESSAGES = {
    "stage_1": {
        "normal": "嗯……让本小姐瞧瞧。锁扣倒是挺精致，纹路也看不出什么名堂……箱缝里透出来的光嘛——",
        "legend": "等等——这纹路……金丝盘龙，锁扣是星辰砂，箱缝透出来的光居然在一吸一吐，像在呼吸？！",
    },
    "stage_2": {
        "rare": "唔，看不出来。得打开才知道。杂鱼，准备好了没？",
        "epic": "唔，看不出来。得打开才知道。杂鱼，准备好了没？",
        "myth": "哦？黄色的光……？！纹路是活的……你看，金丝在动。锁扣不用碰，自己转。",
        "legend": "七、七彩流光？！锁扣自己飞了？！箱盖还没碰就翘起来了——",
    },
    "stage_3": {
        "rare": "稀有品质，勉勉强强吧。杂鱼开出这种箱子，也算……符合你的水平？♡",
        "epic": "史诗品质，还不错嘛。看来你今天的运气，没我想的那么废呀～",
        "myth": "神话品质，这种级别的箱子，本小姐也没见过几次。上次出现是什么时候来着……算了，记不清了。",
        "legend": "传奇品质！本小姐蹲了这么多年箱子，头一回撞见！杂鱼你上辈子救了什么神仙啊！",
    },
}
CARD_DATA_FILE = os.path.join(BOT_DIR, "card_users.json")
card_users = {}
card_lock = threading.Lock()


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as file:
            value = json.load(file)
        return value if isinstance(value, type(default)) else default
    except (OSError, json.JSONDecodeError):
        print(f"[集卡] 数据读取失败：{path}")
        return default


def _save_users():
    temporary_path = f"{CARD_DATA_FILE}.tmp"
    try:
        with open(temporary_path, "w", encoding="utf-8") as file:
            json.dump(card_users, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(temporary_path, CARD_DATA_FILE)
    except OSError as error:
        print(f"[集卡] 用户数据保存失败：{error}")
        if os.path.exists(temporary_path):
            os.remove(temporary_path)


def _load_cards():
    cards = {}
    for rarity, directory in CARD_DIRS.items():
        os.makedirs(directory, exist_ok=True)
        records_path = os.path.join(directory, "cards.json")
        records = _load_json(records_path, {})
        cards[rarity] = [
            (name, os.path.join(directory, filename))
            for name, filename in records.items()
            if isinstance(name, str)
            and isinstance(filename, str)
            and os.path.isfile(os.path.join(directory, filename))
        ]
    return cards


def _load_limited_cards():
    """读取限定卡牌名称；限定卡牌不参与普通抽卡。"""
    os.makedirs(LIMITED_CARD_DIR, exist_ok=True)
    records = _load_json(LIMITED_CARD_FILE, {})
    return {
        name
        for name in records
        if isinstance(name, str)
    }


def _user(user_id):
    key = str(user_id)
    today = datetime.date.today().isoformat()
    record = card_users.setdefault(key, {"date": today, "draws": 5, "inventory": {}})
    if record.get("date") != today:
        record["date"] = today
        record["draws"] = 5
    record.setdefault("inventory", {})
    return record


def _pick_rarity():
    value = random.random()
    total = 0
    for rarity, probability in CARD_PROBABILITIES.items():
        total += probability
        if value < total:
            return rarity
    return "legend"


def _send_card_image(ws, group_id, image_path, card_name):
    if not os.path.isfile(image_path):
        print(f"[集卡] 卡片图片不存在：{image_path}")
        return
    ws.send(json.dumps({
        "action": "send_group_msg",
        "params": {
            "group_id": group_id,
            "message": [{"type": "image", "data": {"file": image_path}}],
        },
        "echo": f"card-{group_id}",
    }, ensure_ascii=False))
    print(f"[集卡] group={group_id} 获得：{card_name}")


def draw_card(ws, group_id, user_id, username):
    with card_lock:
        record = _user(user_id)
        if record["draws"] <= 0:
            send_group_message(ws, group_id, "等等，一次也不剩了，你还想抽卡？！明天记得攒够次数再来哦，杂鱼。本小姐可不给空手的人开后门～")
            _save_users()
            return True
        record["draws"] -= 1
        _save_users()

    rarity = _pick_rarity()
    cards = _load_cards().get(rarity, [])
    if not cards:
        send_group_message(ws, group_id, "这个品质暂时没有配置卡片，抽卡机会已退回。")
        with card_lock:
            _user(user_id)["draws"] += 1
            _save_users()
        return True
    card_name, image_path = random.choice(cards)

    send_group_message(ws, group_id, f"⚠⚠⚠注意！{username}先生开始抽卡了！")

    def stage_one():
        message = CARD_STAGE_MESSAGES["stage_1"]["legend" if rarity == "legend" else "normal"]
        send_group_message(ws, group_id, message)
        _start_timer(2, stage_two)

    def stage_two():
        send_group_message(ws, group_id, CARD_STAGE_MESSAGES["stage_2"][rarity])
        _start_timer(2, stage_three)

    def stage_three():
        send_group_message(ws, group_id, CARD_STAGE_MESSAGES["stage_3"][rarity])

        def send_result():
            with card_lock:
                record = _user(user_id)
                inventory = record["inventory"]
                inventory[card_name] = inventory.get(card_name, 0) + 1
                _save_users()
            send_group_message(ws, group_id, f"恭喜获得{card_name}!")
            _send_card_image(ws, group_id, image_path, card_name)

        _start_timer(2, send_result)

    _start_timer(2, stage_one)
    return True


def show_inventory(ws, group_id, user_id, username):
    with card_lock:
        record = _user(user_id)
        _save_users()
        inventory = record["inventory"]
    send_group_message(ws, group_id, f"让本小姐瞧瞧……杂鱼{username}都攒了些什么破烂——咦？这个、这个、还有这个……嗯，勉强有点看头。")
    if not inventory:
        send_group_message(ws, group_id, "嗯……空的？你这是……出门忘带东西了？行吧行吧，先去弄点东西回来。本小姐在这儿等你，别让我等太久哦～♡")
        return True
    lines = []
    cards = _load_cards()
    limited_cards = _load_limited_cards()
    labels = {
        name: CARD_LABELS[rarity]
        for rarity, entries in cards.items()
        for name, _ in entries
    }
    labels.update({name: "限定" for name in limited_cards})
    rarity_order = ("legend", "myth", "epic", "rare")
    rarity_by_name = {
        name: rarity
        for rarity, entries in cards.items()
        for name, _ in entries
    }
    ordered_inventory = sorted(
        inventory.items(),
        key=lambda item: (
            1 if item[0] in limited_cards else 0,
            rarity_order.index(rarity_by_name.get(item[0], "rare"))
            if rarity_by_name.get(item[0], "rare") in rarity_order
            else len(rarity_order),
            item[0],
        ),
    )
    for name, count in ordered_inventory:
        lines.append(f"{labels.get(name, '未知')}  {name}   *{count}")
    send_group_message(ws, group_id, "\n".join(lines))
    return True


def set_draws(user_id, draws):
    """管理员接口：设置用户今日剩余抽卡次数。"""
    with card_lock:
        record = _user(user_id)
        record["draws"] = max(0, int(draws))
        _save_users()


def add_draws_to_all(amount=5):
    """管理员接口：给所有已记录用户增加指定次数的今日抽卡机会。"""
    amount = int(amount)
    if amount < 0:
        raise ValueError("增加的抽卡次数不能为负数")

    with card_lock:
        for user_id in list(card_users):
            record = _user(user_id)
            record["draws"] += amount
        _save_users()

    return len(card_users)


def add_inventory(user_id, card_name, count=1):
    """管理员接口：增减用户卡牌库存。"""
    with card_lock:
        record = _user(user_id)
        current = record["inventory"].get(card_name, 0)
        record["inventory"][card_name] = max(0, current + int(count))
        _save_users()


card_users.update(_load_json(CARD_DATA_FILE, {}))


def _start_timer(delay, callback):
    timer = threading.Timer(delay, callback)
    timer.daemon = True
    timer.start()
    return timer
