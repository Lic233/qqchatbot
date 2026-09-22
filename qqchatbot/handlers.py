"""NapCat event handlers and command dispatch."""
import json
import random
import time

from cs_matches import get_cs_matches
from attendance import record_attendance
from config import FACE_RULES, IMAGE_RULES, TEXT_RULES
from media import (
    save_custom_face, save_diaotu, send_custom_face, send_diaotu,
    send_group_message, send_image, send_named_diaotu, is_valid_diaotu_name,
)
from state import last_faces, last_images, last_messages, pending_catgirl_requests


def request_catgirl(ws, group_id):
    echo = f"catgirl-{group_id}-{time.time_ns()}"
    pending_catgirl_requests[echo] = group_id
    ws.send(json.dumps({"action": "get_group_member_list",
                        "params": {"group_id": group_id}, "echo": echo},
                       ensure_ascii=False))


def handle_catgirl_response(ws, event):
    group_id = pending_catgirl_requests.pop(str(event.get("echo", "")), None)
    if group_id is None:
        return False
    if event.get("status") != "ok":
        send_group_message(ws, group_id, "今日猫娘抽取失败了")
        return True
    members = event.get("data")
    if not isinstance(members, list) or not members:
        send_group_message(ws, group_id, "群里没有可抽取的群友")
        return True
    member = random.choice(members)
    member_id = member.get("user_id")
    if member_id is None:
        send_group_message(ws, group_id, "今日猫娘抽取失败了")
        return True
    member_name = member.get("card") or member.get("nickname") or str(member_id)
    send_group_message(ws, group_id, [
        {"type": "text", "data": {"text": "今日猫娘是"}},
        {"type": "at", "data": {"qq": str(member_id), "name": str(member_name)}},
        {"type": "text", "data": {"text": "哦！"}},
    ])
    print(f"[今日猫娘] group={group_id}, user={member_id}, name={member_name}")
    return True


def _image_segments(event, group_id):
    for segment in event.get("message", []):
        if segment.get("type") != "image":
            continue
        data = segment.get("data", {})
        url = data.get("url")
        if url:
            last_images[group_id] = {"url": url, "file": data.get("file") or "image.jpg"}
        if data.get("summary") == "[动画表情]" and url:
            last_faces[group_id] = {"url": url, "file": data.get("file", "face.jpg")}


def on_message(ws, message):
    try:
        event = json.loads(message)
    except json.JSONDecodeError:
        print("[错误] 收到无法解析的数据：", message)
        return
    if handle_catgirl_response(ws, event):
        return
    if event.get("post_type") != "message" or event.get("message_type") != "group":
        return
    group_id, user_id = event.get("group_id"), event.get("user_id")
    raw = str(event.get("raw_message", "")).strip()
    named_save = raw[len("保存吊图"):].strip() if raw.startswith("保存吊图") and raw != "保存吊图" else None
    named_send = raw[len("发送吊图"):].strip() if raw.startswith("发送吊图") and raw != "发送吊图" else None
    _image_segments(event, group_id)
    handled = (raw in {"大狗叫不叫", "大份比赛", "打卡", "变猫娘", "保存吊图", "发送吊图", "保存"}
               or named_save is not None or named_send is not None or raw in TEXT_RULES
               or raw in FACE_RULES or any(k in raw for k in IMAGE_RULES))
    if raw in TEXT_RULES:
        send_group_message(ws, group_id, TEXT_RULES[raw])
    if raw == "大份比赛":
        for text in get_cs_matches():
            send_group_message(ws, group_id, text)
    if raw == "大狗叫不叫":
        if random.random() < .7:
            send_group_message(ws, group_id, "才不叫！这种要求我才不答应呢！")
        else:
            send_group_message(ws, group_id, "叫！！！")
            send_custom_face(ws, group_id, "dagoujiao.jpg")
    if raw == "打卡":
        count = record_attendance(group_id, user_id)
        send_group_message(ws, group_id, f"就这点？才打卡{count}次吗？杂鱼，杂鱼！")
        send_custom_face(ws, group_id, "zayu.jpg")
    if raw == "变猫娘":
        request_catgirl(ws, group_id)
    if named_save is not None or raw == "保存吊图":
        name = named_save
        if name is not None and not is_valid_diaotu_name(name):
            send_group_message(ws, group_id, "吊图名称不能为空，且不能包含文件路径中的特殊字符")
        else:
            image = last_images.get(group_id)
            if image is None:
                send_group_message(ws, group_id, "没有找到上一张图片")
            else:
                success = save_diaotu(image["url"], image["file"], name)
                if name:
                    reply = f"“{name}”是吧～就这个名字？人家会好好保管的啦，才不会偷偷扔掉呢～❤️" if success else "吊图保存失败"
                else:
                    reply = ("哼，真是事多……行吧行吧，勉强帮你存好，别再烦我了。"
                             if success else "吊图保存失败")
                send_group_message(ws, group_id, reply)
    if named_send is not None or raw == "发送吊图":
        if named_send is not None and not is_valid_diaotu_name(named_send):
            send_group_message(ws, group_id, "吊图名称不能为空，且不能包含文件路径中的特殊字符")
        elif named_send is not None:
            send_group_message(ws, group_id, "诶～就这张？让我翻翻看……哦～找到了呀，喏，拿去拿去～❤️")
            send_named_diaotu(ws, group_id, named_send)
        else:
            send_group_message(ws, group_id, "啧……真麻烦啊。喏，就给你这一张，别得寸进尺了。")
            send_diaotu(ws, group_id)
    if raw == "保存":
        face = last_faces.get(group_id)
        if face is None:
            send_group_message(ws, group_id, "没有找到上一个表情")
        else:
            send_group_message(ws, group_id, "保存成功" if save_custom_face(face["url"], face["file"]) else "保存失败")
    if raw in FACE_RULES:
        send_custom_face(ws, group_id, FACE_RULES[raw])
    for keyword, filename in IMAGE_RULES.items():
        if keyword in raw:
            send_image(ws, group_id, filename)
            break
    if not handled and raw and raw == last_messages.get(group_id):
        send_group_message(ws, group_id, raw)
    last_messages[group_id] = raw
