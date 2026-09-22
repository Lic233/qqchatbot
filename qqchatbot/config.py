"""Static configuration and data directories for the bot."""
import os

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
WS_URL = "ws://127.0.0.1:3001"
TOKEN = ""

FACE_DIR = os.path.join(BOT_DIR, "faces")
IMAGE_DIR = os.path.join(BOT_DIR, "images")
DIAOTU_DIR = os.path.join(BOT_DIR, "diaotu")
NAMED_DIAOTU_DIR = os.path.join(BOT_DIR, "named_diaotu")
NAMED_DIAOTU_FILE = os.path.join(NAMED_DIAOTU_DIR, "records.json")
ATTENDANCE_FILE = os.path.join(BOT_DIR, "attendance.json")

for directory in (FACE_DIR, IMAGE_DIR, DIAOTU_DIR, NAMED_DIAOTU_DIR):
    os.makedirs(directory, exist_ok=True)

TEXT_RULES = {"我是奶龙": "我才是奶龙", "什么": "不不不"}
FACE_RULES = {
    "气笑了": "qixiaole.jpg",
    "结束了": "yiwuyan.jpg",
    "我是奶龙": "wocaishinailong.jpg",
}
IMAGE_RULES = {
    "这么强": "zhemeqiang.jpg",
    "这么弱": "zhemeruo.jpg",
    "猎鹰比赛": "lieyingbisai.jpg",
}
