"""QQ bot executable entry point.

The public callback names remain here so ``python bot.py`` and integrations
which import ``bot`` keep working; implementation is split by responsibility.
"""
import time
import websocket

from config import TOKEN, WS_URL
from handlers import (
    handle_catgirl_response, on_message, request_catgirl,
)
from media import (
    is_valid_diaotu_name, save_custom_face, save_diaotu, send_custom_face,
    send_diaotu, send_group_message, send_image, send_named_diaotu,
)
from attendance import (
    attendance_records, load_attendance_records, record_attendance,
    save_attendance_records,
)


def on_open(ws):
    print("=" * 40)
    print("QQ机器人已连接")
    print(f"WebSocket: {WS_URL}")
    print("=" * 40)


def on_error(ws, error):
    print("[WebSocket 错误]", error)


def on_close(ws, close_status_code, close_msg):
    print(f"[WebSocket 断开] code={close_status_code}, msg={close_msg}")


def create_websocket():
    headers = [f"Authorization: ******"] if TOKEN else []
    return websocket.WebSocketApp(
        WS_URL, header=headers, on_open=on_open, on_message=on_message,
        on_error=on_error, on_close=on_close,
    )


if __name__ == "__main__":
    while True:
        try:
            create_websocket().run_forever()
        except KeyboardInterrupt:
            print("\n机器人已退出。")
            break
        except Exception as error:
            print("[程序异常]", error)
        print("2 秒后重新连接...")
        time.sleep(2)
