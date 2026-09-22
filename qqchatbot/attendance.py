"""Persistent monthly group attendance records."""
import datetime
import json
import os
import tempfile
import threading

from config import ATTENDANCE_FILE

attendance_records = {}
attendance_lock = threading.Lock()


def load_attendance_records():
    global attendance_records
    if not os.path.exists(ATTENDANCE_FILE):
        return
    try:
        with open(ATTENDANCE_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        records = data.get("records", {})
        if not isinstance(records, dict):
            raise ValueError("records 必须是对象")
        attendance_records = records
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f"[打卡] 记录文件读取失败，将使用空记录：{error}")


def save_attendance_records():
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=os.path.dirname(ATTENDANCE_FILE),
            prefix="attendance_", suffix=".tmp", delete=False
        ) as file:
            temporary_path = file.name
            json.dump({"records": attendance_records}, file, ensure_ascii=False, indent=2)
            file.write("\n")
        os.replace(temporary_path, ATTENDANCE_FILE)
    except OSError as error:
        print(f"[打卡] 记录文件保存失败：{error}")
        if temporary_path and os.path.exists(temporary_path):
            os.remove(temporary_path)


def record_attendance(group_id, user_id):
    month = datetime.date.today().strftime("%Y-%m")
    record_key = f"{group_id}:{user_id}:{month}"
    with attendance_lock:
        count = attendance_records.get(record_key, 0) + 1
        attendance_records[record_key] = count
        save_attendance_records()
    return count


load_attendance_records()
