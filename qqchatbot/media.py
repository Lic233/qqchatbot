"""Image, custom-face, and diaotu persistence and sending operations."""
import datetime
import json
import os
import tempfile
import urllib.error
import urllib.request

from config import (
    DIAOTU_DIR, FACE_DIR, IMAGE_DIR, NAMED_DIAOTU_DIR, NAMED_DIAOTU_FILE,
)

named_diaotu_records = {}


def load_named_diaotu_records():
    global named_diaotu_records
    if not os.path.exists(NAMED_DIAOTU_FILE):
        return
    try:
        with open(NAMED_DIAOTU_FILE, "r", encoding="utf-8") as file:
            records = json.load(file)
        if not isinstance(records, dict):
            raise ValueError("记录必须是对象")
        named_diaotu_records = {
            str(name): str(filename) for name, filename in records.items()
            if isinstance(name, str) and isinstance(filename, str)
        }
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"[吊图] 命名记录读取失败，将使用空记录：{error}")


def save_named_diaotu_records():
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=NAMED_DIAOTU_DIR,
            prefix="records_", suffix=".tmp", delete=False
        ) as file:
            temporary_path = file.name
            json.dump(named_diaotu_records, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(temporary_path, NAMED_DIAOTU_FILE)
        return True
    except OSError as error:
        print(f"[吊图] 命名记录保存失败：{error}")
        if temporary_path and os.path.exists(temporary_path):
            os.remove(temporary_path)
        return False


def is_valid_diaotu_name(name):
    invalid_characters = set('\\/:*?"<>|')
    return bool(name) and name not in {".", ".."} and not any(
        character in invalid_characters or ord(character) < 32 for character in name
    )


def _send_file(ws, group_id, path, label, echo):
    if not os.path.isfile(path):
        print(f"[图片] 文件不存在：{path}")
        return False
    ws.send(json.dumps({"action": "send_group_msg", "params": {
        "group_id": group_id,
        "message": [{"type": "image", "data": {"file": path}}],
    }, "echo": f"{echo}-{group_id}"}, ensure_ascii=False))
    print(f"[图片] group={group_id} 发送：{label}")
    return True


def send_group_message(ws, group_id, message):
    ws.send(json.dumps({"action": "send_group_msg", "params": {
        "group_id": group_id, "message": message, "auto_escape": False,
    }, "echo": f"send-{group_id}"}, ensure_ascii=False))


def send_custom_face(ws, group_id, filename):
    return _send_file(ws, group_id, os.path.join(FACE_DIR, filename), filename, "face")


def send_image(ws, group_id, filename):
    return _send_file(ws, group_id, os.path.join(IMAGE_DIR, filename), filename, "image")


def send_diaotu_file(ws, group_id, image_path, filename):
    return _send_file(ws, group_id, image_path, filename, "diaotu")


def save_diaotu(url, original_filename, name=None):
    extension = os.path.splitext(original_filename)[1] or ".jpg"
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{timestamp}{extension}" if name is not None else f"diaotu_{timestamp}{extension}"
    directory = NAMED_DIAOTU_DIR if name is not None else DIAOTU_DIR
    path = os.path.join(directory, filename)
    try:
        print(f"[吊图] 正在保存：{path}")
        urllib.request.urlretrieve(url, path)
        if name is not None:
            named_diaotu_records[name] = filename
            if not save_named_diaotu_records():
                named_diaotu_records.pop(name, None)
                os.remove(path)
                return False
        print(f"[吊图] 保存成功：{path}")
        return True
    except (OSError, urllib.error.URLError, ValueError) as error:
        print(f"[吊图] 保存失败：{error}")
        return False


def send_named_diaotu(ws, group_id, name):
    filename = named_diaotu_records.get(name)
    if filename is None:
        send_group_message(ws, group_id, f"根本没有什么叫做“{name}”的东西嘛！真是的，可恶！嗯？才、才没有生气呢！")
        return False
    path = os.path.join(NAMED_DIAOTU_DIR, filename)
    if not os.path.isfile(path):
        send_group_message(ws, group_id, f"名为“{name}”的吊图文件不存在")
        return False
    return send_diaotu_file(ws, group_id, path, name)


def send_diaotu(ws, group_id):
    extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
    paths = []
    for directory in (DIAOTU_DIR, NAMED_DIAOTU_DIR):
        paths.extend((os.path.join(directory, f), f) for f in os.listdir(directory)
                     if os.path.isfile(os.path.join(directory, f))
                     and os.path.splitext(f)[1].lower() in extensions)
    if not paths:
        send_group_message(ws, group_id, "吊图文件夹里还没有图片")
        return False
    import random
    path, filename = random.choice(paths)
    return send_diaotu_file(ws, group_id, path, filename)


def save_custom_face(url, original_filename):
    extension = os.path.splitext(original_filename)[1] or ".jpg"
    filename = f"saved_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{extension}"
    path = os.path.join(FACE_DIR, filename)
    try:
        print(f"[表情] 正在保存：{path}")
        urllib.request.urlretrieve(url, path)
        print(f"[表情] 保存成功：{path}")
        return True
    except Exception as error:
        print("[表情] 保存失败：", error)
        return False


load_named_diaotu_records()
