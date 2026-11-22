"""按钮面板的基础设施：把"标签 + 命令"拼成平台要的 keyboard 结构。

具体面板长什么样由调用方决定（行内容、高亮哪个按钮），这里只管
合规：行数、每行按钮数、label 长度都按平台上限卡死，别让整条消息被拒。

几条平台硬限制（改之前先看）：
* 按钮只能挂在 markdown 消息上（msg_type=2）；
* 最多 5 行、每行最多 5 个，超了报 40034029；
* ``render_data.label`` 最多 10 个字符；
  **实际是按宽度截的**：实测「强化合金 888」这种带数字的会被客户端切成
  「强化…」，光写「强化合金」就正常 —— 所以按钮上只放名字，别把价格塞进去；
* 群聊里**指令型按钮**（action.type=2）的 ``enter`` 只在单聊生效，群里点了
  只会把「@机器人 命令」填进输入框，用户还得自己点发送。所以这里一律用
  ``type=1`` 回调按钮，才算真·一键执行。
* 同一个 ``group_id`` 的按钮点一个后其它会变灰（仅 type=1 有效），适合
  "派遣"这种互斥选择。
"""
from __future__ import annotations

from .base import *  # noqa: F401,F403

MAX_ROWS = 5
MAX_BUTTONS_PER_ROW = 5
MAX_LABEL_CHARS = 10

# 临时测试入口：验证「发按钮 → 点击 → 回调」整条链路。
# 确认没问题、宠物面板接上以后，删掉这个常量和 handler 里的分支即可。
BUTTON_TEST_COMMAND = "按钮测试"


def make_button(label: str, data: str = "", style: int = 0, *,
                group_id: str = "", modal: str = "",
                user_ids: tuple[str, ...] | list[str] = ()) -> dict:
    """造一个回调型按钮。

    ``data`` 不传就用 label（面板按钮都是这么用的）。
    ``user_ids`` 非空时只有这些人能点（permission.type=0），用来做"自己的面板
    只有自己能按"；传空就是所有人可点。
    ``group_id`` 非空时同组按钮互斥变灰；``modal`` 非空时点击先弹二次确认
    （最多 40 字，不能带链接），适合花银币那种有代价的操作。
    """
    text = (label or "")[:MAX_LABEL_CHARS]
    allowed = [str(uid) for uid in user_ids if str(uid or "").strip()]
    action: dict = {
        "type": 1,
        # type=2 所有人可点；type=0 只给名单里的人点（自己的面板自己按）
        "permission": ({"type": 0, "specify_user_ids": allowed} if allowed
                       else {"type": 2}),
        "data": data or label,
        "unsupport_tips": f"客户端版本过低，直接发「{data or label}」也一样",
    }
    if modal:
        action["modal"] = {"content": modal[:40], "confirm_text": "好的",
                           "cancel_text": "算了"}
    button: dict = {
        "render_data": {"label": text, "visited_label": text, "style": style},
        "action": action,
    }
    if group_id:
        button["group_id"] = group_id
    return button


def build_rows(rows: list[list], highlight: bool = False,
               user_ids: tuple[str, ...] | list[str] = ()) -> list[dict]:
    """``[["喂食", "玩耍"], [("打工 4h", "宠物 做 写代码")]]`` → ``[{"buttons": [...]}]``。

    每一项可以是字符串（label 即 data），也可以是 ``(label, data)`` 二元组
    —— 按钮文字有字数上限（10），而命令往往更长，所以两者要能分开给。

    ``user_ids`` 非空时这些按钮只有名单里的人能点：谁唤出的面板谁按。

    超限的按钮直接丢掉（宁可少一行，也别整条消息被拒）。
    ``highlight`` 时第一行第一个按钮用蓝色线框，当主操作。
    """
    built: list[dict] = []
    for row_index, row in enumerate(rows):
        if row_index >= MAX_ROWS:
            break
        buttons = []
        for index, item in enumerate(row):
            if isinstance(item, (tuple, list)) and len(item) == 2:
                label, data = str(item[0] or ""), str(item[1] or "")
            else:
                label, data = str(item or ""), ""
            if not label.strip():
                continue
            style = 1 if highlight and row_index == 0 and index == 0 else 0
            buttons.append(make_button(label, data, style, user_ids=user_ids))
            if len(buttons) >= MAX_BUTTONS_PER_ROW:
                break
        if buttons:
            built.append({"buttons": buttons})
    return built
