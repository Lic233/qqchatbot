"""Static configuration and data directories for the bot."""
import os

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
WS_URL = "ws://127.0.0.1:3001"
TOKEN = ""

BOT_QQ_FILE = os.path.join(BOT_DIR, "bot_qq.txt")
DEEPSEEK_API_KEY_FILE = os.path.join(BOT_DIR, "deepseek_api.txt")


def read_config_file(path):
    """读取只放一个值的配置文件；文件不存在或为空时返回空字符串。"""
    try:
        with open(path, "r", encoding="utf-8") as file:
            return file.read().strip()
    except FileNotFoundError:
        return ""
    except OSError as error:
        print(f"[配置] {path} 读取失败：{error}")
        return ""


BOT_QQ = read_config_file(BOT_QQ_FILE) or os.getenv("NAPCAT_BOT_QQ", "").strip()
DEEPSEEK_API_KEY = (
    read_config_file(DEEPSEEK_API_KEY_FILE)
    or os.getenv("DEEPSEEK_API_KEY", "").strip()
)
DEEPSEEK_API_URL = (
    os.getenv("DEEPSEEK_API_URL", "").strip()
    or "https://api.deepseek.com/chat/completions"
)
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "").strip() or "deepseek-chat"

# 调试开关：排查“机器人为什么不回应”时改为 True，重启后会打印未命中的消息和失败的接口调用
DEBUG_MESSAGES = False

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
