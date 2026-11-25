"""离线自检：不联网，覆盖规则、命令、AI、搜索、复读、上传。

单独成文件，平时运行 bot 不用导入它（入口只在 --selftest 时延迟导入）。
"""
from __future__ import annotations

import math
import random

from .ai import *  # noqa: F401,F403
from .api import *  # noqa: F401,F403
from .base import *  # noqa: F401,F403
from .cards import *  # noqa: F401,F403
from .config import *  # noqa: F401,F403
from .cs import *  # noqa: F401,F403
from .devil_roulette import (
    ACT_ACCEPT,
    ACT_MENU,
    ACT_SELF,
    ACT_SHOOT,
    ACT_USE,
    ENTRY_FEE,
    INVITE_TTL,
    SESSION_TTL as DEVIL_SESSION_TTL,
    DevilRoulette,
    panel_data as devil_panel_data,
)
from .devil_roulette_data import (
    DEFEAT_LINES,
    FISH_NAME,
    HURT_LINES,
    ITEMS as DEVIL_ITEMS,
    MAX_HP as DEVIL_MAX_HP,
    TAUNTS as DEVIL_TAUNTS,
)
from .features import *  # noqa: F401,F403
from .forge import *  # noqa: F401,F403
from .forge_new import *  # noqa: F401,F403
from .forge_rank import *  # noqa: F401,F403
from .handler import *  # noqa: F401,F403
from .pet_sword import *  # noqa: F401,F403
# 只挑「弗一把」要用的几个名字：题库里的 ITEMS / MATERIALS 之类跟锻造的内容表
# 重名，用 * 会把别处正在用的表整个换掉。
from .mc_guess import (
    MAX_ROUNDS,
    MCGuess,
    weighted_pick,
    NUDGE_IDLE,
    SESSION_TTL,
)
from .mc_guess_data import (
    BANK_FILE as MC_BANK_FILE,
    COLORS as MC_COLORS,
    ITEMS as MC_ITEMS,
    Item as MC_Item,
    VERSION_ORDER,
    check_data,
    find_item,
    load_items as mc_load_items,
    version_newer,
)
from .mc_guess_data_hard import (
    HARD_ITEMS as MC_HARD_ITEMS,
    VERSION_ORDER_HARD,
    version_label,
    check_hard_data,
    find_hard_item,
)
from .panel import *  # noqa: F401,F403
from .pet import *  # noqa: F401,F403
from .voice import *  # noqa: F401,F403


# --------------------------------------------------------------------------
# 自检
# --------------------------------------------------------------------------

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _raises(call, error_type) -> bool:
    """跑一下 call，看是不是抛了指定异常（自检里不想为每条都写 try 块）。"""
    try:
        call()
    except error_type:
        return True
    except Exception:  # noqa: BLE001 - 抛别的类型也算不符合预期
        return False
    return False


class FakeSender:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []
        self.panels: list[list[dict]] = []     # 每次发面板时的按钮行

    async def text(self, group: str, content: str, msg_id: str | None = None) -> None:
        # 和真正的 GroupSender 一样过千分位，否则自检看不出区别
        self.events.append(("text", format_numbers(content)))

    async def image(self, group: str, path: Path, msg_id: str | None = None) -> None:
        self.events.append(("image", Path(path).name))

    async def voice(self, group: str, path: Path, msg_id: str | None = None) -> None:
        self.events.append(("voice", Path(path).name))

    async def markdown(self, group: str, content: str,
                       msg_id: str | None = None) -> None:
        self.events.append(("markdown", content))

    async def panel(self, group: str, content: str, rows: list[dict],
                    msg_id: str | None = None) -> None:
        self.panels.append(rows)
        self.events.append(("panel", content))

    async def text_long(self, group: str, content: str,
                        msg_id: str | None = None) -> None:
        for chunk in split_text(content):
            self.events.append(("text", chunk))


async def selftest() -> int:
    # 不用 mkdtemp：它的 0700 目录在部分沙箱/机器上会拒绝后续写入。
    temporary = Path(tempfile.gettempdir()) / f"qqbot-selftest-{os.getpid()}"
    temporary.mkdir(parents=True, exist_ok=True)
    paths = Paths(temporary)
    for directory, filename in (
        (paths.images, "wocaishinailong.jpg"),
        (paths.images, "qixiaole.jpg"),
        (paths.images, "zhemeqiang.jpg"),
        (paths.images, "eat.gif"),
        (paths.images, "play.gif"),
    ):
        (directory / filename).write_bytes(PNG_1PX)

    # 给"保存吊图"准备一个可以用 file:// 读的源图
    source = temporary / "source.png"
    source.write_bytes(PNG_1PX)

    sender = FakeSender()
    persona_file = temporary / "persona.txt"
    persona_file.write_text("你是测试人设，说话简短。", encoding="utf-8")
    handler = Handler(sender, paths, persona_path=persona_file)
    failures: list[str] = []

    # 语音条只在群友发「语音：…」时触发，AI 回复不再自动念，所以这里不用打桩；
    # 「== 语音 ==」那节会自己临时把合成换成假的（自检不联网）。

    async def feed(content: str, images: list[ImageRef] | None = None,
                   is_bot: bool = False, msg_id: str = "m1",
                   mentioned: bool = False, has_card: bool = False) -> None:
        await handler.handle(Incoming(
            group_openid="G1", user_openid="U1", username="测试",
            content=content, msg_id=msg_id, images=images or [], is_bot=is_bot,
            mentioned=mentioned, has_card=has_card,
        ))

    def expect(name: str, condition: bool) -> None:
        print(("  ok   " if condition else "  FAIL ") + name)
        if not condition:
            failures.append(name)

    print("== 关键词 ==")
    await feed("我是奶龙")
    expect("「我是奶龙」发文字", ("text", "我才是奶龙") in sender.events)
    expect("「我是奶龙」也发表情", ("image", "wocaishinailong.jpg") in sender.events)

    sender.events.clear()
    await feed("什么")
    expect("「什么」发文字", sender.events == [("text", "不不不")])

    sender.events.clear()
    await feed("气笑了")
    expect("「气笑了」发表情", sender.events == [("image", "qixiaole.jpg")])

    sender.events.clear()
    await feed("这也太这么强了吧")
    expect("包含「这么强」发图片", sender.events == [("image", "zhemeqiang.jpg")])

    sender.events.clear()
    await feed("今天天气不错")
    expect("普通聊天不回复", sender.events == [])

    sender.events.clear()
    await feed("我是奶龙", is_bot=True)
    expect("机器人自己发的消息忽略", sender.events == [])

    print("== @ 前缀 ==")
    # 实测踩到过：全量消息模式下 @ 标记剥掉后会残留一个前导 @。
    sender.events.clear()
    await feed("@什么")
    expect("前导 @ 被剥掉（'@什么'）", sender.events == [("text", "不不不")])

    sender.events.clear()
    await feed('<qqbot-at-user id="123" />什么')
    expect("@ 标记被剥掉（<qqbot-at-user/>）", sender.events == [("text", "不不不")])

    sender.events.clear()
    await feed('@<qqbot-at-user id="123"/> 我是奶龙')
    expect("@+标记+空格 的组合", ("text", "我才是奶龙") in sender.events)

    sender.events.clear()
    await feed("@")
    expect("只有一个 @ 时不回复", sender.events == [])

    print("== 名字前缀 ==")
    handler.bot_names = {"测试机器人"}
    sender.events.clear()
    await feed("测试机器人 什么")
    expect("名字前缀被剥掉（'测试机器人 什么'）", sender.events == [("text", "不不不")])

    sender.events.clear()
    await feed("@测试机器人 我是奶龙")
    expect("@名字 前缀组合", ("text", "我才是奶龙") in sender.events)

    sender.events.clear()
    await feed('<faceType=6,faceId="0",ext="eyJ0ZXh0IjoiIn0=">')
    expect("表情标签不触发规则", sender.events == [])

    print("== 吊图 ==")
    sender.events.clear()
    await feed("保存吊图 测试图", images=[ImageRef(url=source.as_uri(), filename="source.png")])
    expect("保存吊图 有回复", sender.events and sender.events[0][0] == "text")
    saved = handler.records.get("测试图")
    expect("记录里出现「测试图」", bool(saved))
    expect("文件真的落盘", bool(saved) and (paths.named_diaotu / saved).is_file())

    sender.events.clear()
    await feed("发送吊图 测试图")
    kinds = [kind for kind, _ in sender.events]
    expect("直接发图、不说话", kinds == ["image"])
    expect("发的是刚存的那张", saved is not None and sender.events[0][1] == saved)

    sender.events.clear()
    await feed("发送吊图 不存在的图")
    expect("名字不存在时给提示", bool(sender.events) and sender.events[0][0] == "text")

    sender.events.clear()
    await feed("发送吊图")
    kinds = [kind for kind, _ in sender.events]
    expect("随机发送先说话再发图", kinds == ["text", "image"])

    sender.events.clear()
    handler.last_images.clear()          # 模拟"群里从没出现过图片"
    await feed("保存吊图")
    expect("没有图时提示", sender.events == [("text", "没有找到上一张图片")])

    print("== AI 对话 ==")
    ai_calls: list[tuple[str, str]] = []
    image_calls: list[list] = []
    ai_tools: dict = {}

    async def fake_chat(system: str, text: str, images=None, **kwargs) -> str:
        ai_calls.append((system, text))
        image_calls.append(list(images or []))
        ai_tools.clear()
        ai_tools.update(kwargs)
        return "收到：" + text

    handler.chat = fake_chat
    sender.events.clear()
    ai_calls.clear()
    await feed("你好呀", mentioned=True)
    expect("@ 触发 AI", sender.events == [("text", "收到：你好呀")])
    expect("AI 回复只发文字、不自带语音条",
           all(kind == "text" for kind, _ in sender.events))
    expect("提示词带人设", bool(ai_calls) and "测试人设" in ai_calls[0][0])
    expect("提示词带说话人", bool(ai_calls) and "「测试」" in ai_calls[0][0])
    expect("没开搜索时提示词说没联网", bool(ai_calls) and "没有联网工具" in ai_calls[0][0])

    # 命令优先：@ + 命令仍然走命令，不会变成闲聊
    sender.events.clear()
    ai_calls.clear()
    await feed("保存吊图 测试图", images=[ImageRef(url=source.as_uri(), filename="source.png")],
               mentioned=True, msg_id="m3")
    expect("@ + 命令仍走命令（不进 AI）", not ai_calls and bool(sender.events))
    expect("@ + 命令有保存回复", sender.events[0][0] == "text")

    # 记忆按群共享：第二次对话能带上群里的上一次内容
    sender.events.clear()
    ai_calls.clear()
    await feed("我刚说了什么", mentioned=True)
    expect("记忆带进提示词", bool(ai_calls) and "你好呀" in ai_calls[0][0])

    # 换个人也看得到群里刚才聊的（同一个群共享），但要知道是谁说的
    sender.events.clear()
    ai_calls.clear()
    await handler.handle(Incoming(group_openid="G1", user_openid="U2", username="另一个人",
                                  content="你好呀", msg_id="m4", mentioned=True))
    expect("群内共享：别人的对话也带进来",
           bool(ai_calls) and "我刚说了什么" in ai_calls[0][0])
    expect("别人的行不带 → 标记",
           bool(ai_calls) and "\n[测试]" in ai_calls[0][0]
           and "→[测试]" not in ai_calls[0][0])

    # 同一个人再说一句：他这个人的行会被标成「正在和你说话」
    sender.events.clear()
    ai_calls.clear()
    await handler.handle(Incoming(group_openid="G1", user_openid="U2", username="另一个人",
                                  content="我又是谁", msg_id="m5", mentioned=True))
    expect("正在对话的人的行首有 →",
           bool(ai_calls) and "→[另一个人]" in ai_calls[0][0])
    expect("提示词说清 → 表示正在对话的人",
           bool(ai_calls) and "行首带 →" in ai_calls[0][0])

    # 记忆库：模型自己判断记不记，写进去的东西下一轮会进提示词
    remember = ai_tools.get("remember")
    expect("记忆库工具交给了模型", callable(remember))
    if callable(remember):
        await remember("毕设做的是太赫兹超材料传感器", "")
        notes = handler.memory_bank.notes("G1")
        expect("记忆库真的写进去了",
               any("太赫兹" in str(note.get("text")) for note in notes))
        expect("默认记在当前说话人名下",
               any(note.get("about") == "另一个人" for note in notes))
        expect("重复的同一句不再记",
               (await remember("毕设做的是太赫兹超材料传感器", "")).startswith("这条已经记过"))
        expect("重复后条数没涨", len(handler.memory_bank.notes("G1")) == len(notes))
        await remember("怕辣", "测试")
        expect("可以记到别人名下",
               any(note.get("about") == "测试" for note in handler.memory_bank.notes("G1")))
        await remember("群里不刷屏", "查无此人")
        expect("认不出的人就记成群级的",
               any(note.get("about") == "" and "不刷屏" in str(note.get("text"))
                   for note in handler.memory_bank.notes("G1")))

        sender.events.clear()
        ai_calls.clear()
        await handler.handle(Incoming(group_openid="G1", user_openid="U1", username="测试",
                                      content="我毕设是啥", msg_id="m5c", mentioned=True))
        expect("记忆库进了下一轮提示词",
               bool(ai_calls) and "太赫兹" in ai_calls[0][0])

    # 「忘掉我」功能已删除：这句话现在只是普通闲聊，不回复、也不动群里的记录
    sender.events.clear()
    ai_calls.clear()
    await feed("忘掉我", mentioned=False, msg_id="m6")
    expect("忘掉我 不再有专门回复", sender.events == [] and not ai_calls)
    expect("忘掉我 不动群里的对话",
           "我又是谁" in handler.memory.transcript("G1", "U1"))

    # 长回复自动分条
    sender.events.clear()

    async def long_chat(system: str, text: str, images=None, **kwargs) -> str:
        return "第一段。" * 400

    handler.chat = long_chat
    await feed("讲个长故事", mentioned=True, msg_id="m6")
    expect("长回复切成多条", len(sender.events) > 1)
    expect("每条都没超限", all(len(text) <= REPLY_CHUNK_CHARS for _, text in sender.events))
    expect("长回复也不念语音", all(kind == "text" for kind, _ in sender.events))

    # AI 失败要兜底，不能把异常抛出去
    sender.events.clear()

    async def broken_chat(system: str, text: str, images=None, **kwargs) -> str:
        raise RuntimeError("模拟 DeepSeek 挂了")

    handler.chat = broken_chat
    await feed("在吗", mentioned=True, msg_id="m7")
    expect("AI 失败有兜底文案", bool(sender.events) and "走丢" in sender.events[0][1])

    print("== 视频总结 ==")
    from .videosum import (
        BiliClient,
        Video,
        _BVID_IN_PAGE_RE,
        _parse_set_cookie,
        _pick_positions,
        clean_sessdata,
        clean_title,
        correspond_path,
        find_link_in_raw,
        find_video_link,
        parse_cookie,
        review_instruction,
        review_prompt,
        short_link,
        title_similarity,
    )

    expect(
        "整段 cookie 也能抠出 SESSDATA",
        clean_sessdata("  SESSDATA=abc%2Cdef; bili_jct=zzz ") == "abc%2Cdef",
    )
    expect("不把 %2C 解码成逗号", clean_sessdata("abc%2Cdef").count("%2C") == 1)

    # 整段 Cookie 比单个 SESSDATA 稳：B站 会滚动刷新，还认 buvid3 这些设备指纹
    expect(
        "整段 cookie 拆成多个字段",
        parse_cookie("SESSDATA=a%2Cb; buvid3=XYZ") ==
        {"SESSDATA": "a%2Cb", "buvid3": "XYZ"},
    )
    expect("裸值当 SESSDATA", parse_cookie("abc%2Cdef") == {"SESSDATA": "abc%2Cdef"})
    expect("buvid4 末尾的 = 不被切断",
           parse_cookie("buvid4=q==").get("buvid4") == "q==")
    expect(
        "整段 cookie 原样发给 B站",
        BiliClient("SESSDATA=a; buvid3=b")._headers().get("Cookie")
        == "SESSDATA=a; buvid3=b",
    )

    # F12「应用 → Cookie」表格全选复制出来是 Tab 分隔的多列，不是分号格式。
    # 这种行里没有 "="，按分号切会整行丢掉 —— 用户照步骤做却配不上，最难查。
    devtools_table = (
        "Name\tValue\tDomain\tPath\tExpires / Max-Age\tSize\n"
        "SESSDATA\taf%2C1808\t.bilibili.com\t/\t2027-04-23\t222\n"
        "buvid4\tXY%2Fzz==\t.bilibili.com\t/\t2027-04-23\t56\n"
        "   \t\t\t\t\t\n"
    )
    table_parsed = parse_cookie(devtools_table)
    expect("认得出 F12 表格复制的格式",
           table_parsed.get("SESSDATA") == "af%2C1808"
           and table_parsed.get("buvid4") == "XY%2Fzz==")
    expect("表格的表头不被当成 cookie", "Name" not in table_parsed)
    expect("空行不会解析出空字段", "" not in table_parsed)

    # 表格 Ctrl+A 只复制已渲染的行，SESSDATA 是 HttpOnly 且排在后面，很容易漏掉。
    # 官方推荐的取法是 Network 里复制 cookie 请求头（含 HttpOnly），所以也得认。
    curl_line = (
        "curl 'https://api.bilibili.com/x/web-interface/nav' "
        "-H 'cookie: SESSDATA=af%2C1; buvid3=XYZ' --compressed"
    )
    expect("从 cURL 里抠出 cookie 请求头",
           parse_cookie(curl_line).get("SESSDATA") == "af%2C1")
    expect("带 cookie: 前缀也能认",
           parse_cookie("cookie: SESSDATA=af%2C1; buvid3=X").get("SESSDATA") == "af%2C1")
    expect(
        "表格末尾手补一行也能收下",
        parse_cookie("SESSDATA\told\t.bilibili.com\t/\nbuvid3\tX\t/\nac_time_value=abc")
        == {"SESSDATA": "old", "buvid3": "X", "ac_time_value": "abc"},
    )

    # 登录态续期：B站 web 端会滚动换发 SESSDATA，不接着用就作废。
    demo = correspond_path(1750000000000)
    expect("续期路径是 128 字节的 hex", len(demo) == 256 and
           all(ch in "0123456789abcdef" for ch in demo))
    # OAEP 带随机种子，同样输入每次密文都不同（这正是它该有的行为），
    # 所以这里只能验「形状对、每次都不一样」。
    expect("每次加密结果都不同，但长度一致",
           demo != correspond_path(1750000000000)
           and len(correspond_path(1750000000000)) == 256)
    expect("换个时间戳也照样出 128 字节",
           len(correspond_path(1750000000001)) == 256)
    expect("续期页面能抠出 refresh_csrf",
           BiliClient._dom_value(
               '<div id="1-name" class="x">abc123</div>', "1-name") == "abc123")
    expect("抠不到时返回空串",
           BiliClient._dom_value('<div id="1-other">z</div>', "1-name") == "")
    expect("Set-Cookie 只取第一个分号前",
           _parse_set_cookie(["SESSDATA=abc; Path=/; Domain=x"]) == {"SESSDATA": "abc"})

    # 服务端换发的新 cookie 必须收下，否则下次还拿旧值问，就被判「未登录」
    rotated = BiliClient("SESSDATA=old; buvid3=dev")
    written: list[dict[str, str]] = []
    rotated.on_refresh = lambda cookies: written.append(dict(cookies))
    rotated._absorb({"SESSDATA": "new", "bili_jct": "jct"})
    expect("响应里的新 cookie 被收下",
           rotated.sessdata == "new" and rotated.cookies.get("bili_jct") == "jct")
    expect("新 cookie 立刻写回", bool(written) and written[-1].get("SESSDATA") == "new")
    rotated._absorb({"SESSDATA": "new"})
    expect("值没变就不重复写盘", len(written) == 1)

    expect(
        "认出 b23 短链",
        find_video_link("看这个 https://b23.tv/abc123 好笑") == "https://b23.tv/abc123",
    )
    expect("认出光秃秃的 BV 号", find_video_link("BV1GJ411x7h7") == "BV1GJ411x7h7")
    expect("别的站不误判", find_video_link("https://example.com/a") is None)
    expect("只是聊天不当视频", find_video_link("今天好累") is None)
    # 手机端分享的几种脏写法：链接后面直接粘中文、少了协议头、B站自己的短链域名
    expect(
        "短链后面粘中文也能认",
        find_video_link("https://b23.tv/abc123视频内容") == "https://b23.tv/abc123",
    )
    expect(
        "没协议头的短链也认",
        find_video_link("这个 b23.tv/abc123 好笑") == "https://b23.tv/abc123",
    )
    expect(
        "认 bili2233 短链",
        find_video_link("https://bili2233.cn/abc123") == "https://bili2233.cn/abc123",
    )
    expect(
        "分享文案里的链接能原样取出",
        find_video_link("【某某视频-哔哩哔哩】 https://b23.tv/abc123")
        == "https://b23.tv/abc123",
    )
    expect(
        "短链只留短码，参数和中文都丢掉",
        short_link("https://b23.tv/abc123?share_source=copy_web&vd_source=9啦啦")
        == "https://b23.tv/abc123",
    )
    # 按标题搜（手机端卡片只有标题）：标点 emoji 都得先清掉再比
    expect(
        "标题归一化去掉标签和标点",
        clean_title('[QQ小程序]根本没有这样的洛克！？②') == "根本没有这样的洛克2",
    )
    expect(
        "搜关键词时丢掉 ①②③（带上就搜不到）",
        clean_title("根本没有这样的洛克！？②", keep_numbers=False)
        == "根本没有这样的洛克",
    )
    expect(
        "搜索结果的高亮标签也能清掉",
        clean_title('<em class="keyword">洛克</em>王国')
        == "洛克王国",
    )
    expect("一样的标题算 1.0",
           title_similarity("洛克王国", "洛克王国") == 1.0)
    expect("不相干的标题分很低",
           title_similarity("洛克王国", "宝可梦朱紫") < 0.3)

    sample_video = Video(
        bvid="BV1GJ411x7h7", aid=1, cid=2, title="测试视频", up_name="测试UP",
        up_mid=3, duration=600, summary="这是一段摘要",
        text="文稿正文" * 50, source="AI 文稿",
    )
    prompt = review_prompt(sample_video, 1000)
    expect("资料里有标题和 UP", "测试视频" in prompt and "测试UP" in prompt)
    expect("资料里有文稿", "文稿正文" in prompt)
    expect("要求它别假装看过", "别假装看过内容" in prompt)

    # 画面截图：抽帧要均匀、掐头尾，措辞也要跟着「有没有截图」变
    picks = _pick_positions(100, 6)
    expect("抽帧数量对", len(picks) == 6)
    expect(
        "抽帧有序且避开首尾",
        picks == sorted(picks) and picks[0] > 0 and picks[-1] < 99,
    )
    expect("帧数不够时不重复", _pick_positions(3, 6) == [0, 1, 2])
    expect("没有截图时不许提画面",
           "别假装看过内容" in review_instruction(False)
           and "截图" not in review_instruction(False))
    expect("有截图时改口允许描述画面",
           "截图" in review_instruction(True)
           and "别假装看过内容" not in review_instruction(True))

    framed_video = Video(
        bvid="BV1aa411c7mD", aid=1, cid=2, title="带画面的视频", duration=120,
        frames=[(5, b"\xff\xd8one"), (60, b"\xff\xd8two")],
    )
    framed_prompt = review_prompt(framed_video)
    expect("资料里标明截图时间点",
           "【画面截图】" in framed_prompt and "00:05" in framed_prompt)

    video_calls: list[str] = []

    class FakeBili:
        def analyze(self, link):
            video_calls.append(link)
            return sample_video

        def snapshot(self, video, count=6):
            return 0

    handler.video = FakeBili()
    handler.vision_enabled = True
    handler.chat = fake_chat
    sender.events.clear()
    ai_calls.clear()
    await feed("看看这个 https://b23.tv/abc123", mentioned=True, msg_id="v1")
    expect("先回一句在看", bool(sender.events) and "看看" in sender.events[0][1])
    expect("链接交给了视频解析", video_calls == ["https://b23.tv/abc123"])
    expect("拿文稿去问了模型", any("测试视频" in text for _, text in ai_calls))
    expect("评价发出去了", len(sender.events) >= 2)

    # 实测的真实用法：先转发链接，再单独 @ 一句「看看这个」
    sender.events.clear()
    ai_calls.clear()
    video_calls.clear()
    await feed("https://b23.tv/zzz999", msg_id="v2")
    expect("光发链接不插嘴", sender.events == [])
    await feed("看看这个", mentioned=True, msg_id="v3")
    expect("用了群里最近的链接", video_calls == ["https://b23.tv/zzz999"])

    # 反过来也要防：群里留着链接时，别人聊别的话题顺嘴说了句「总结」，不该被
    # 劫持去总结那个旧视频（23:09 实测真发生过，还回了句「这个链接我没认出来」）。
    sender.events.clear()
    ai_calls.clear()
    video_calls.clear()
    await feed("和原神的优点对比一下，总结哪个更好玩", mentioned=True, msg_id="v3b")
    expect("聊别的顺嘴说总结不抢戏", not video_calls and bool(ai_calls))

    # 太长的直接拒绝，别把上下文顶爆
    class LongBili:
        def analyze(self, link):
            return Video(bvid="BV1xx411c7mD", aid=1, cid=2, title="超长视频",
                         duration=7200)

    handler.video = LongBili()
    sender.events.clear()
    ai_calls.clear()
    await feed("BV1xx411c7mD 总结一下", mentioned=True, msg_id="v4")
    expect("超长视频拒绝", not ai_calls
           and any("太长" in text for _, text in sender.events))

    # 纯画面视频（没口播、没字幕）也该能评：靠截图，别直接说看不到
    class FramedBili:
        def analyze(self, link):
            return framed_video

        def snapshot(self, video, count=6):
            return len(video.frames)

    handler.video = FramedBili()
    sender.events.clear()
    ai_calls.clear()
    image_calls.clear()
    await feed("看看 BV1aa411c7mD", mentioned=True, msg_id="v5")
    expect("只有画面时不拒绝", any("带画面的视频" in text for _, text in ai_calls))
    expect(
        "截图跟着一起发给模型",
        bool(image_calls) and len(image_calls[-1]) == 2
        and image_calls[-1][0].get("type") == "image_url",
    )

    # 认不出来 / 没内容时要说清楚，不能让模型瞎编
    class DumbBili:
        def analyze(self, link):
            return None

    handler.video = DumbBili()
    sender.events.clear()
    ai_calls.clear()
    await feed("https://b23.tv/none 看看", mentioned=True, msg_id="v5")
    expect("认不出链接时说清楚", not ai_calls
           and any("没认出来" in text for _, text in sender.events))

    # 分享卡片：正文是空的，链接在卡片 JSON 里（斜杠被转义成 \/）
    slash = chr(92)
    card_event = parse_group_event("GROUP_MESSAGE_CREATE", {
        "id": "v9", "group_openid": "G1", "content": "",
        "author": {"member_openid": "U1", "username": "群友"},
        "ark_messages": [{"kv": [{
            "key": "#JUMP_URL#",
            "value": "https:" + slash + "/" + slash + "/b23.tv/abc123",
        }]}],
    })
    expect("分享卡片能捞出链接", card_event.attached_url == "https://b23.tv/abc123")
    expect("卡片消息被认出来", card_event.has_card)

    # 手机端卡片的几种变体：转义叠两层（整个卡片被序列化两遍）、整条 URL 被
    # urlencode 塞进参数、以及只有「小程序中转页 + 哔哩哔哩」的形态。
    double = "https:" + slash * 2 + "/" + slash * 2 + "/b23.tv" + slash * 2 + "/abc123"
    expect(
        "两层转义的卡片也能捞",
        find_link_in_raw(json.dumps({"ark_messages": [{"value": double}]},
                                    ensure_ascii=False))
        == "https://b23.tv/abc123",
    )
    expect(
        "被 urlencode 的链接也能捞",
        find_link_in_raw('{"u": "https%3A%2F%2Fb23.tv%2Fabc123"}')
        == "https://b23.tv/abc123",
    )
    expect(
        "只有标题的卡片捞不到链接",
        find_link_in_raw(json.dumps({"ark_messages": [{"value": "【某视频】"}]},
                                    ensure_ascii=False)) == "",
    )
    relay = json.dumps({"ark_messages": [{"value": json.dumps({
        "app": "com.tencent.miniapp_01",
        "meta": {"detail_1": {"title": "哔哩哔哩",
                              "qqdocurl": "https://m.q.qq.com/a/s/abcDEF123"}},
    }, ensure_ascii=False)}]}, ensure_ascii=False)
    expect("小程序中转页（带哔哩哔哩）能认", find_link_in_raw(relay)
           == "https://m.q.qq.com/a/s/abcDEF123")
    other = json.dumps({"meta": {"detail_1": {
        "title": "某某", "qqdocurl": "https://m.q.qq.com/a/s/zzz"}}},
        ensure_ascii=False)
    expect("别的小程序不误判", find_link_in_raw(other) == "")
    # 实测踩过的坑：一条普通文字消息，事件里某个随机串凑出「BV + 10 位」，被当
    # 成视频链接存了 10 分钟，接着别人问「总结」直接被劫持，报 code=-400。
    noise = json.dumps({
        "id": "m1", "content": "这个确实没办法",
        "preview": "https://qq.ugcimg.cn/v1/BVqQDrsNYAeD/x.jpg",
    }, ensure_ascii=False)
    expect("没有 B站 痕迹时不认裸 BV 号", find_link_in_raw(noise) == "")
    expect(
        "有 B站 痕迹的裸 BV 号仍然认",
        find_link_in_raw(json.dumps({"title": "哔哩哔哩", "v": "BV1GJ411x7h7"},
                                    ensure_ascii=False)) == "BV1GJ411x7h7",
    )
    expect(
        "QQ 自己套的 url.cn 短链也能认",
        find_link_in_raw(json.dumps({"title": "哔哩哔哩", "u": "https://url.cn/AbCd123"},
                                    ensure_ascii=False))
        == "https://url.cn/AbCd123",
    )
    page_hit = _BVID_IN_PAGE_RE.search(
        '<script>window.location="/video/BV1GJ411x7h7/?p=1"</script>'
    )
    expect(
        "落地页里的 BV 号能挑出来",
        bool(page_hit) and page_hit.group(1) == "BV1GJ411x7h7",
    )

    # 手机端转发卡片、卡片里没有链接：接着说「总结视频」应该得到人话解释，
    # 而不是让模型瞎猜「我看不到视频」。
    handler.last_video_links.clear()
    handler.last_card.clear()
    sender.events.clear()
    ai_calls.clear()
    await feed("", has_card=True, msg_id="v10")
    await feed("总结视频", mentioned=True, msg_id="v11")
    expect("卡片没链接时说清楚怎么发",
           not ai_calls and any("复制链接" in text for _, text in sender.events))
    handler.last_card.clear()

    # 手机端真正发过来的那种卡片：平台把小程序卡片转成了纯文字，只有标题、
    # 没有链接（source: 哔哩哔哩）。这时按标题去 B站 搜。
    mobile_card = (
        "[卡片消息] 小程序\n"
        "摘要: [QQ小程序]根本没有这样的洛克！？②\n"
        "source_logo: http://miniapp.gtimg.cn/public/appicon/x_200.jpg\n"
        "title: 根本没有这样的洛克！？②\n"
        "preview: https://qq.ugcimg.cn/v1/90l2fj452ueusetgle7i3le8frdpemfh\n"
        "source: 哔哩哔哩"
    )
    expect("手机卡片能抠出视频标题",
           card_title(mobile_card) == "根本没有这样的洛克！？②")
    expect("没有 source 的卡片不当 B站",
           card_title("[卡片消息] 小程序\ntitle: 某某\nsource: 某音乐") == "")

    title_calls: list[str] = []

    class TitleBili(FakeBili):
        def analyze_by_title(self, title):
            title_calls.append(title)
            return sample_video

    handler.video = TitleBili()
    handler.last_video_links.clear()
    handler.last_card.clear()
    sender.events.clear()
    ai_calls.clear()
    card_event2 = parse_group_event("GROUP_MESSAGE_CREATE", {
        "id": "v12", "group_openid": "G1", "content": mobile_card,
        "author": {"member_openid": "U1", "username": "手机用户"},
    })
    expect("卡片事件认得出标题", card_event2.card_title == "根本没有这样的洛克！？②")
    await handler.handle(card_event2)
    await feed("看看这个视频", mentioned=True, msg_id="v13")
    expect("按标题去搜了", title_calls == ["根本没有这样的洛克！？②"])
    expect("搜到之后照样评价", any("测试视频" in text for _, text in ai_calls))
    expect("说清是按标题搜的",
           any("按标题" in text for _, text in sender.events))
    handler.last_card.clear()

    print("== 联网搜索 ==")
    sample_payload = {
        "results": [
            {
                "title": "DeepSeek 发布新版模型",
                "url": "https://example.com/news",
                "summary": "这是今天的新闻摘要",
                "snippet": "短摘要",
            },
            {"title": "", "url": "https://example.com/empty", "summary": "没标题"},
        ]
    }
    parsed = parse_search_results(sample_payload, limit=5, snippet_limit=600)
    expect("解析搜索结果（丢掉没标题的）", len(parsed) == 1)
    expect(
        "结果文本带标题摘要链接",
        "标题：DeepSeek 发布新版模型" in parsed[0].as_text()
        and "链接：https://example.com/news" in parsed[0].as_text(),
    )
    expect(
        "摘要超长会截断",
        parse_search_results(
            {"results": [{"title": "t", "summary": "字" * 100}]}, snippet_limit=10
        )[0].snippet.endswith("…"),
    )
    expect(
        "相关性闸门挡住降级结果",
        not search_is_relevant(
            "2026年诺贝尔物理学奖", [SearchResult("2026年日历", "", "放假安排")], 0.25
        ),
    )
    expect("相关结果能过闸门", search_is_relevant("DeepSeek 新版", parsed, 0.25))
    expect("空结果给模型的提示", "没有搜到" in format_search_results([]))

    class LoopChat(DeepSeek):
        def __init__(self) -> None:
            super().__init__("test-key")
            self.requests: list[dict] = []

        async def _complete(self, payload: dict) -> dict:
            self.requests.append(payload)
            if len(self.requests) == 1:
                return {
                    "content": "",
                    "tool_calls": [{
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "web_search",
                            "arguments": '{"query": "今天的新闻"}',
                        },
                    }],
                }
            return {"content": "搜到了：今天没什么大事。"}

    loop_chat = LoopChat()
    searched: list[str] = []

    async def fake_search(query: str) -> list[SearchResult]:
        searched.append(query)
        return [SearchResult("新闻标题", "https://example.com/news", "新闻摘要")]

    loop_reply = await loop_chat.answer("系统提示", "今天有什么新闻", search=fake_search)
    expect("模型会调用搜索工具", searched == ["今天的新闻"])
    expect("搜索结果回喂后作答", loop_reply.startswith("搜到了"))
    expect("第一轮带 tools", "tools" in loop_chat.requests[0])
    expect(
        "tool 消息带搜索结果",
        any(
            message.get("role") == "tool"
            and "新闻标题" in str(message.get("content"))
            for message in loop_chat.requests[1]["messages"]
        ),
    )

    # 两句空话的判定：放话去搜算，已经在讲结果的不算
    expect("「我去搜搜」算放话", looks_like_search_promise("等我一下，我去搜搜"))
    expect("「得查一下最近的赛程」算放话",
           looks_like_search_promise("诶……肘赢？你是说谁把 Faker 打了吧。\n\n这个我不能靠猜，得查一下最近的赛"))
    expect("「让我查一下」算放话", looks_like_search_promise("让我查一下"))
    expect("已经在讲结果的不算", not looks_like_search_promise("我查了一下，确实是 3:1"))
    expect("正常短回答不算", not looks_like_search_promise("好呀，那明天见"))
    expect("长回复不算（有正文）",
           not looks_like_search_promise("我去搜搜" + "，顺便说一句" * 10))

    class PromiseThenSearch(DeepSeek):
        """第一轮只放话不调工具：要被催一次，然后真的去查。"""

        def __init__(self) -> None:
            super().__init__("test-key")
            self.requests: list[dict] = []

        async def _complete(self, payload: dict) -> dict:
            self.requests.append(payload)
            if len(self.requests) == 1:
                return {"content": "这个我得查一下最近的比赛"}
            if len(self.requests) == 2:
                return {"tool_calls": [{
                    "id": "call-9",
                    "type": "function",
                    "function": {"name": "web_search",
                                 "arguments": '{"query": "谁赢了 faker"}'},
                }]}
            return {"content": "查到了：是肘子赢了。"}

    promised = PromiseThenSearch()
    notes: list[str] = []

    async def on_search(query: str) -> None:
        notes.append(query)

    promised_searches: list[str] = []

    async def promised_search(query: str) -> list[SearchResult]:
        promised_searches.append(query)
        return [SearchResult("赛果", "https://example.com/1", "肘子 3:1 Faker")]

    promised_reply = await promised.answer(
        "系统提示", "谁肘赢了faker", search=promised_search, on_search=on_search,
    )
    expect("只放话会被催着真去查", promised_searches == ["谁赢了 faker"])
    expect("催完拿到的是答案不是那句空话", promised_reply.startswith("查到了"))
    expect("催查只插了一条提示", len(notes) == 1)
    expect("催查第二轮带上了提醒",
           any("别只说要查" in str(message.get("content"))
               for message in promised.requests[1]["messages"]))

    # 联网时先单独发一句提示，第二条才是答案
    handler.search = fake_search
    sender.events.clear()

    async def notify_chat(system: str, text: str, images=None, search=None,
                          on_search=None, **kwargs) -> str:
        if callable(on_search):
            await on_search("今天的新闻")
        return "查到了：今天没什么大事。"

    handler.chat = notify_chat
    await feed("今天有什么新闻", mentioned=True, msg_id="m7c")
    expect("开搜时一共发两条", len(sender.events) == 2)
    expect("第一条是搜索提示",
           bool(sender.events) and sender.events[0][0] == "text"
           and sender.events[0][1] in SEARCH_NOTICE_LINES)
    expect("第二条才是答案",
           len(sender.events) == 2 and sender.events[1][1].startswith("查到了"))
    handler.search = None
    handler.chat = fake_chat

    handler.search = fake_search
    search_seen: dict = {}

    async def search_chat(system: str, text: str, images=None, search=None,
                          **kwargs) -> str:
        search_seen["system"] = system
        search_seen["search"] = search
        return "好"

    sender.events.clear()
    handler.chat = search_chat
    await feed("今天有什么新闻", mentioned=True, msg_id="m7b")
    expect("开搜索后提示词说可以搜", "web_search" in search_seen.get("system", ""))
    expect("搜索函数传给了模型", callable(search_seen.get("search")))
    handler.search = None
    handler.chat = fake_chat

    print("== 识图 ==")
    seen: dict = {}

    async def vision_chat(system: str, text: str, images=None, **kwargs) -> str:
        seen["system"] = system
        seen["text"] = text
        seen["images"] = list(images or [])
        return "我看到图了"

    handler.chat = vision_chat
    handler.vision_enabled = True
    handler.vision_max_bytes = 1024 * 1024
    sender.events.clear()
    await feed("这是什么", images=[ImageRef(url=source.as_uri(), filename="source.png")],
               mentioned=True, msg_id="m8")
    expect("图片进了请求", len(seen.get("images") or []) == 1)
    expect(
        "图片是 base64 data URL",
        (seen.get("images") or [{}])[0].get("image_url", {}).get("url", "")
        .startswith("data:image/png;base64,"),
    )
    expect("提示词说能看到画面", "你会直接看到画面" in seen.get("system", ""))

    sender.events.clear()
    await feed("", images=[ImageRef(url=source.as_uri(), filename="source.png")],
               mentioned=True, msg_id="m9")
    expect("只发图片时会说明", "只发了图片" in seen.get("text", ""))

    sender.events.clear()
    handler.vision_max_bytes = 10
    await feed("这是什么", images=[ImageRef(url=source.as_uri(), filename="source.png")],
               mentioned=True, msg_id="m10")
    expect("超限图片被跳过", seen.get("images") == [])
    handler.vision_max_bytes = 1024 * 1024

    sender.events.clear()
    handler.vision_enabled = False
    await feed("这是什么", images=[ImageRef(url=source.as_uri(), filename="source.png")],
               mentioned=True, msg_id="m11")
    expect("关掉识图不带图", seen.get("images") == [])
    expect("关掉识图提示词改口", "你看不到图片画面" in seen.get("system", ""))
    handler.vision_enabled = True

    # 实测用法：先发一张图，再单独发「这是什么」→ 附上群里上一张图
    sender.events.clear()
    await feed("", images=[ImageRef(url=source.as_uri(), filename="source.png")],
               msg_id="m12")
    await feed("这是什么", mentioned=True, msg_id="m13")
    expect("没带图时附上一张", len(seen.get("images") or []) == 1)
    expect("说明附的是上一张", "上一张图" in seen.get("text", ""))

    # 太久以前的图不附（避免拿别人十分钟前的图瞎答）
    handler.last_image_at["G1"] = 0
    await feed("这张图是什么", mentioned=True, msg_id="m14")
    expect("上一张图过期就不附", seen.get("images") == [])

    # 「先发图，再单独 @」也要能描述（平台把图和 @ 拆成两条消息）
    sender.events.clear()
    await feed("", images=[ImageRef(url=source.as_uri(), filename="source.png")],
               msg_id="m15")
    await feed("", mentioned=True, msg_id="m16")
    expect("只 @ 不说话也附上一张", len(seen.get("images") or []) == 1)

    # 没有新图时，光 @ 还是提醒它说话
    handler.last_image_at["G1"] = 0
    sender.events.clear()
    await feed("", mentioned=True, msg_id="m17")
    expect("没有图时提醒说话", bool(sender.events) and "逗我玩" in sender.events[0][1])

    print("== @ 判定 ==")
    expect("解析 <@ID>", mention_ids_in("<@ABC123> 你好") == ["ABC123"])
    expect("解析 qqbot-at-user", mention_ids_in('<qqbot-at-user id="XYZ" /> hi') == ["XYZ"])

    handler.bot_ids = {"BOT-ID"}
    handler.chat = fake_chat
    sender.events.clear()
    await handler.handle(Incoming(
        group_openid="G1", user_openid="U1", username="测试",
        content="你好呀", msg_id="m80", mentioned=True, mention_ids=["OTHER-ID"],
    ))
    expect("@ 别人时不触发 AI", sender.events == [])

    sender.events.clear()
    await handler.handle(Incoming(
        group_openid="G1", user_openid="U1", username="测试",
        content="你好呀", msg_id="m81", mentioned=True, mention_ids=["BOT-ID"],
    ))
    expect("@ 自己时触发 AI", bool(sender.events) and sender.events[0][0] == "text")

    # 宠物状态：只在真的在忙时进提示词，而且写清楚"别主动提"
    pet_u1 = handler.pets.get("U1")
    pet_u1["action"] = "写代码"
    pet_u1["action_start"] = int(time.time()) - 3600
    hint = handler._pet_state_hint("G1", "U1")
    expect("在打工时给出状态提示", "写代码" in hint and "1 小时" in hint)
    pet_u1["action"] = "发呆"
    expect("发呆时不打扰模型", handler._pet_state_hint("G1", "U1") == "")
    expect("没养宠物就不掺和", handler._pet_state_hint("G1", "查无此人") == "")

    pet_u1["action"] = "玩耍"
    pet_u1["play_kind"] = "CS"
    pet_u1["action_start"] = int(time.time()) - 1200
    play_hint = handler._pet_state_hint("G1", "U1")
    expect("AI 知道在玩什么", "CS" in play_hint and "玩耍" in play_hint)

    pet_u1["action"] = "写代码"
    pet_u1["action_start"] = int(time.time())
    ai_calls.clear()
    sender.events.clear()
    await handler.handle(Incoming(
        group_openid="G1", user_openid="U1", username="测试",
        content="在干嘛", msg_id="m82", mentioned=True, mention_ids=["BOT-ID"],
    ))
    system_now = ai_calls[-1][0] if ai_calls else ""
    expect("系统提示词里带上了手头的事",
           "你手头正在做的事" in system_now and "写代码" in system_now)
    expect("提示词明确要求别主动提",
           "不要主动提起" in system_now)

    print("== 千分位 ==")
    expect("六位以上切三位", format_numbers("现在价值 1234567") == "现在价值 1,234,567")
    expect("刚好六位才切", format_numbers("123456") == "123,456")
    expect("五位不动", format_numbers("价格 12345") == "价格 12345")
    expect("URL 里不动", format_numbers("https://x.com/123456789") == "https://x.com/123456789")
    expect("小数位不动", format_numbers("3.1415926") == "3.1415926")

    class FakeAPI:
        def __init__(self) -> None:
            self.texts: list[str] = []
            self.calls: list[tuple[str, str]] = []   # (msg_id, event_id)

        async def send_text(self, group: str, content: str,
                            msg_id: str | None = None, msg_seq: int = 1,
                            event_id: str = "") -> dict:
            self.texts.append(content)
            self.calls.append((msg_id or "", event_id))
            return {"id": "x"}

        async def send_image(self, *args, **kwargs) -> dict:
            return {"id": "y"}

    fake_api = FakeAPI()
    await GroupSender(fake_api).text("G1", "银币 1234567")
    expect("出群文本自动千分位", fake_api.texts == ["银币 1,234,567"])

    fake_api.calls.clear()
    await GroupSender(fake_api).text("G1", "普通回复", "ROBOT1.0_x")
    expect("普通消息用 msg_id 回", fake_api.calls == [("ROBOT1.0_x", "")])

    fake_api.calls.clear()
    await GroupSender(fake_api).text("G1", "按钮回复", event_reply_token("inter-9"))
    expect("按钮点击改用 event_id 回", fake_api.calls == [("", "inter-9")])

    print("== 抽卡 / 开箱 ==")
    for rarity, folder, card in (
        ("rare", "card/rare_card", "稀有测试卡"),
        ("epic", "card/epic_card", "史诗测试卡"),
        ("myth", "card/myth_card", "神话测试卡"),
        ("legend", "card/legend_card", "传奇测试卡"),
        ("origin", "card/box_card", "始源测试卡"),
        ("limited", "card/limited_card", "限定测试卡"),
    ):
        directory = temporary / folder
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{rarity}.png").write_bytes(PNG_1PX)
        (directory / "cards.json").write_text(
            json.dumps({card: f"{rarity}.png"}, ensure_ascii=False), encoding="utf-8"
        )
    # 限定卡池里还有只有名字、没有图的（原插件那边值是 null），库存也得列出来
    limited_cards = temporary / "card" / "limited_card" / "cards.json"
    limited_records = json.loads(limited_cards.read_text(encoding="utf-8"))
    limited_records["限定无图卡"] = None
    limited_cards.write_text(
        json.dumps(limited_records, ensure_ascii=False), encoding="utf-8"
    )
    cards = Cards(temporary)
    handler.cards = Cards(temporary)   # handler 是更早建的，卡池刚就位

    sender.events.clear()
    await feed("发送吊图 稀有测试卡")
    expect("命名吊图没有时回退卡池", any(kind == "image" for kind, _ in sender.events))
    expect("回退到卡池时直接发图、不废话",
           not any(kind == "text" for kind, _ in sender.events))

    sender.events.clear()
    await feed("发送吊图 完全不存在")
    expect("卡池也没有时给提示",
           any("根本没有什么叫做" in text for kind, text in sender.events if kind == "text"))
    reply = cards.draw("U-CARD")
    expect("抽卡有结果", "抽到了" in reply.text or "重复" in reply.text)
    expect("抽卡带图", reply.image is not None and reply.image.is_file())
    record = cards.user("U-CARD")
    expect("次数减一", int(record["draws"]) == DRAWS_PER_DAY - 1)
    expect("库存记了一张", sum(int(v) for v in record["inventory"].values()) == 1)

    # 单一卡池里再抽一定重复 → 折银币
    while int(cards.user("U-CARD")["draws"]) > 0:
        cards.draw("U-CARD")
    expect("重复卡折成银币", int(cards.user("U-CARD")["shards"]) > 0)
    expect("次数用完有提示", "明天" in cards.draw("U-CARD").text)

    # 开箱：银币不足
    poor = cards.user("U-POOR")
    poor["shards"] = 10
    expect("银币不够开箱", "要 500" in cards.open_box("U-POOR").text)

    # 开箱：扣 500 并给结果
    rich = cards.user("U-RICH")
    rich["shards"] = CARD_BOX_COST
    box = cards.open_box("U-RICH")
    expect("开箱有结果", any(word in box.text for word in ("始源卡", "银币")))
    expect("开箱扣了 500", int(cards.user("U-RICH")["shards"]) < CARD_BOX_COST)

    # 始源卡改为完全随机：抽到已有的就折银币，不再优先没出过的。
    from . import cards as cards_module

    class _StubBoxRandom:
        @staticmethod
        def random():
            return 0.0

        @staticmethod
        def choice(seq):
            return seq[0]

        @staticmethod
        def randint(low, high):
            return 100

    saved_pools, saved_random = cards._pools, cards_module.random
    cards_module.random = _StubBoxRandom()
    cards._pools = {"origin": [("已有始源", temporary / "a.png"),
                               ("没有始源", temporary / "b.png")]}
    try:
        owned_roll = cards._roll_box({"inventory": {"已有始源": 1}, "shards": 0})
        fresh_record = {"inventory": {}, "shards": 0}
        fresh_roll = cards._roll_box(fresh_record)
    finally:
        cards._pools, cards_module.random = saved_pools, saved_random
    expect(
        "开箱始源卡不再优先没出过的",
        owned_roll["kind"] == "duplicate"
        and owned_roll["name"] == "已有始源"
        and owned_roll["amount"] == 100,
    )
    expect(
        "开箱始源卡不重复时正常入库",
        fresh_roll["kind"] == "card"
        and fresh_record["inventory"].get("已有始源") == 1,
    )

    # 2026-11-19 起：奖池只剩「10% 始源卡 / 90% 银币」，附魔书不再出
    expect("始源卡概率改成 10%", abs(CARD_BOX_CARD_PROBABILITY - 0.10) < 1e-9)

    class _MidBoxRandom:
        @staticmethod
        def random():
            return 0.5

        @staticmethod
        def randint(low, high):
            return 100

    saved_mid_random = cards_module.random
    cards_module.random = _MidBoxRandom()
    try:
        plain_record = {"inventory": {}, "shards": 0, "books": {}}
        plain_roll = cards._roll_box(plain_record)
    finally:
        cards_module.random = saved_mid_random
    expect(
        "10% 以外只出银币、附魔书已经开不出来",
        plain_roll["kind"] == "shards"
        and plain_roll["amount"] == 100
        and plain_record["books"] == {},
    )

    # 十连：要 5000
    ten = cards.user("U-TEN")
    ten["shards"] = CARD_BOX_COST * CARD_BOX_TEN_COUNT
    reply_ten = cards.open_ten("U-TEN")
    expect("十连有汇总", "十个箱子" in reply_ten.text)
    expect("十连扣 5000", int(cards.user("U-TEN")["shards"]) < CARD_BOX_COST * CARD_BOX_TEN_COUNT)

    # 库存文案
    inventory = cards.inventory_text("U-CARD")
    expect("库存列了卡", "稀有" in inventory or "史诗" in inventory or "神话" in inventory)
    expect("库存报银币", "银币" in inventory)

    # 限定卡：精选和全部两种库存都要列出（包括只有名字没有图的）
    limited = cards.user("U-LIMITED")
    limited["inventory"]["限定测试卡"] = 1
    limited["inventory"]["限定无图卡"] = 1
    compact = cards.inventory_text("U-LIMITED")
    limited_lines = [line for line in compact.splitlines() if line.startswith("限定：")]
    expect("查看库存列限定卡", bool(limited_lines) and all(
        name in limited_lines[0] for name in ("限定测试卡", "限定无图卡")
    ))
    expect("限定卡不算进隐藏", "没列出来" not in compact)
    full = cards.inventory_text("U-LIMITED", show_all=True)
    expect(
        "查看全部库存列限定卡",
        any(line.startswith("限定：") and "限定测试卡" in line
            for line in full.splitlines()),
    )
    groups, _, _, _ = cards.inventory_groups("U-LIMITED")
    expect("限定组排在最前", bool(groups) and groups[0][0] == "限定")

    # 走一遍 Handler 命令
    sender.events.clear()
    await feed("抽卡")
    expect("「抽卡」命令能用", bool(sender.events) and sender.events[0][0] == "text")
    expect("命令抽卡真的发牌", bool(sender.events) and any(
        word in sender.events[0][1] for word in ("抽到了", "重复", "明天")
    ))

    if card_image is not None:
        # 精选视图只列始源/限定/传奇/神话，先塞一张始源卡进去，才走得到画图那条路
        handler.cards.user("U-CARD")["inventory"]["始源测试卡"] = 1
        sender.events.clear()
        await handler.handle(Incoming(
            group_openid="G1", user_openid="U-CARD", username="测试",
            content="查看库存", msg_id="m20",
        ))
        expect("库存发的是图", bool(sender.events) and sender.events[0][0] == "image")
        expect(
            "渲染图发完就删",
            bool(sender.events) and not any(handler.render_dir.glob("*.jpg")),
        )

    # 迁移：共用文件里的非数字键（openid）搬进官方文件，QQ 号不搬
    shared = temporary / "card_users.json"
    shared.write_text(
        json.dumps(
            {"999888": {"inventory": {}}, "OPENID-TEST": {"shards": 7}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    official_file = temporary / "card_users_official.json"
    if official_file.exists():
        official_file.unlink()
    migrated = Cards(temporary)
    expect("迁移出官方记录", int(migrated.user("OPENID-TEST").get("shards", 0)) == 7)
    expect("QQ 号没被搬过来", "999888" not in migrated._users)

    print("== 打卡 / 签到 ==")
    (temporary / "wife").mkdir(parents=True, exist_ok=True)
    (temporary / "wife" / "wife1.png").write_bytes(PNG_1PX)
    luck_dir = temporary / "daily_luck"
    luck_dir.mkdir(parents=True, exist_ok=True)
    (luck_dir / "大吉.png").write_bytes(PNG_1PX)
    (luck_dir / "daily_luck.json").write_text(
        json.dumps({"大吉": "大吉.png"}, ensure_ascii=False), encoding="utf-8"
    )
    handler.attendance = Attendance(temporary)
    handler.luck = DailyLuck(temporary)

    sender.events.clear()
    await feed("打卡", msg_id="m30")
    expect("打卡记次数", bool(sender.events) and "打卡1次" in sender.events[0][1])

    handler.cards = Cards(temporary)
    before = int(handler.cards.user("U1")["shards"])
    sender.events.clear()
    await feed("签到", msg_id="m31")
    if card_image is not None:
        expect("签到发的是图", bool(sender.events) and sender.events[0][0] == "image")
    else:
        expect("签到发的是文字", bool(sender.events) and sender.events[0][0] == "text")
    record = handler.cards.user("U1")
    expect("签到给银币", int(record["shards"]) > before)
    expect("签到用完次数", int(record["draws"]) == 0)
    expect(
        "记住今天签过",
        record.get("last_check_in") == datetime.date.today().isoformat(),
    )
    expect("当天第二次不给银币", handler.cards.grant_check_in_shards("U1") is None)

    print("== 今日猫娘 / 随机老婆 ==")
    sender.events.clear()
    await feed("随便说句话", msg_id="m40")     # 让名册记住这个人
    expect("名册记住发言人", bool(handler.roster.members("G1")))
    expect("名册能按 openid 反查名片", handler.roster.name_of("G1", "U1") == "测试")
    expect("名册查不到时返回空串", handler.roster.name_of("G1", "不存在的人") == "")
    sender.events.clear()
    await feed("随机老婆", msg_id="m41")
    expect("随机老婆发文字", bool(sender.events) and sender.events[0][0] == "text")
    expect("随机老婆配图", any(kind == "image" for kind, _ in sender.events))
    sender.events.clear()
    await feed("今日猫娘", msg_id="m42")
    bubbles = [text for kind, text in sender.events if kind in ("text", "markdown")]
    expect("今日猫娘带 @ 标记", any("qqbot-at-user" in text for text in bubbles))
    expect("走的是 markdown 卡片", any(kind == "markdown" for kind, _ in sender.events))
    expect("今日猫娘配图", any(kind == "image" for kind, _ in sender.events))

    print("== 按钮面板 ==")
    rows = build_rows([["喂食", "玩耍", "休息"], ["打工 1h", "打工 4h"]],
                      highlight=True, user_ids=["U1"])
    expect("按钮行数不超限", 0 < len(rows) <= MAX_ROWS)
    expect("每行按钮数不超限",
           all(len(row.get("buttons") or []) <= MAX_BUTTONS_PER_ROW for row in rows))
    buttons = [button for row in rows for button in (row.get("buttons") or [])]
    expect("首行首个按钮高亮", buttons[0]["render_data"]["style"] == 1)
    expect("其余按钮不高亮", all(b["render_data"]["style"] == 0 for b in buttons[1:]))
    expect("按钮文字不超过 10 字",
           all(len(b["render_data"]["label"]) <= MAX_LABEL_CHARS for b in buttons))
    expect("超长按钮文字被截断",
           build_rows([["一二三四五六七八九十十一"]])[0]["buttons"][0]
           ["render_data"]["label"] == "一二三四五六七八九十")
    expect("超过 5 行被截断", len(build_rows([["签到"]] * 7)) == MAX_ROWS)
    expect("按钮全部是回调型（群聊只有这种能一键执行）",
           all(b["action"]["type"] == 1 for b in buttons))
    expect("按钮 data 就是命令原文", buttons[0]["action"]["data"] == "喂食")
    expect("面板按钮只签名给唤出者",
           all(b["action"]["permission"]["type"] == 0
               and b["action"]["permission"]["specify_user_ids"] == ["U1"]
               for b in buttons))
    expect("不签名时所有人都能点",
           build_rows([["签到"]])[0]["buttons"][0]["action"]["permission"]["type"] == 2)

    sender.events.clear()
    await feed("按钮测试", msg_id="p1")
    expect("「按钮测试」发出带按钮的消息",
           bool(sender.events) and sender.events[0][0] == "panel")
    sender.events.clear()
    await feed("按钮测试 回执", msg_id="p2")
    expect("点「回执」能回话",
           bool(sender.events) and "回调通了" in sender.events[0][1])

    clicked = parse_interaction_event({
        "id": "inter-1",
        "type": 11,
        "scene": "group",
        "group_openid": "G1",
        "group_member_openid": "U1",
        "data": {"type": 11, "resolved": {"button_data": "签到"}},
    })
    expect("按钮点击能还原成命令", clicked is not None and clicked.content == "签到")
    expect("按钮回复锚点走 event_id",
           clicked is not None and clicked.event_id == "inter-1"
           and clicked.msg_id == "event:inter-1")
    # 平台只认带前缀的写法，裸 uuid 会被判 40034025；前缀在发送层补
    passive: dict = {}
    QQBotAPI._attach_passive(passive, event_id="inter-1")
    expect("event_id 自动补事件类型前缀",
           passive.get("event_id") == "INTERACTION_CREATE:inter-1")
    expect("回复锚点能拆回来",
           split_reply_token("event:abc") == ("event", "abc")
           and split_reply_token("ROBOT1.0_x") == ("msg", "ROBOT1.0_x"))
    expect("非按钮互动不处理", parse_interaction_event({"id": "x", "type": 13}) is None)

    sender.events.clear()
    if clicked is not None:
        await handler.handle(clicked)
    expect("按钮点击走的是同一条命令链路", bool(sender.events))

    print("== 宠物 ==")
    pets = handler.pets
    base = 1_700_000_000.0
    record = pets.get("P1", base)
    expect("新宠物满体力满心情",
           record["stamina"] == 100 and record["mood"] == 100)
    pets.switch("P1", "写代码", base)
    settled = pets.settle("P1", base + 60 * 60)
    expect("写代码 1 小时结算 3 块", settled["units"] == 3)
    expect("3 块给 144 银币", settled["coins"] == 144)
    expect("银币直接进钱包", handler.cards.shards_of("P1") == 144)
    expect("体力心情各掉 30", record["stamina"] == 70 and record["mood"] == 70)
    expect("不满 20 分钟的零头不算",
           pets.settle("P1", base + 60 * 60 + 11 * 60)["units"] == 0)

    record["stamina"] = 15.0
    pets.switch("P1", "写代码", base + 60 * 60)
    capped = pets.settle("P1", base + 60 * 60 + 80 * 60)
    expect("体力只够 1 块就只结算 1 块", capped["units"] == 1)
    expect("剩下的时间转成发呆",
           capped["idle_units"] == 3 and record["action"] == "发呆")

    record["exp"] = exp_need(1) - 2
    record["action"] = "写代码"
    record["action_start"] = base
    record["stamina"] = 100
    record["mood"] = 100
    up = pets.settle("P1", base + 20 * 60)
    expect("经验够了就升级", record["level"] == 2 and up["levels"] == 1)
    expect("30 级前是 20+5×等级",
           (exp_need(1), exp_need(2), exp_need(29)) == (25, 30, 165))
    expect("30 级起陡增 400+100×(等级-30)",
           (exp_need(30), exp_need(31), exp_need(39)) == (400, 500, 1300))
    expect("等级上限 40", MAX_LEVEL == 40)
    expect("每 5 级涨上限",
           (limits(4), limits(5), limits(10), limits(30), limits(40))
           == ((100, 100), (105, 110), (110, 120), (130, 160), (140, 180)))

    # 发呆：每块回 1 体力 1 心情（不至于软锁）
    record["stamina"] = 50
    record["mood"] = 50
    record["action"] = "发呆"
    record["action_start"] = base
    pets.settle("P1", base + 60 * 60)
    expect("发呆每块回 1 体力 1 心情", record["stamina"] == 53 and record["mood"] == 53)

    # 好感度：干活掉、玩耍回，归零后只能发呆/玩耍
    record["affection"] = 100
    record["stamina"] = 100
    record["mood"] = 100
    record["action"] = "写代码"
    record["action_start"] = base
    pets.settle("P1", base + 60 * 60)
    expect("工作每块掉 3 好感", record["affection"] == 91)

    record["affection"] = 50
    record["mood"] = 50
    record["stamina"] = 100        # 上一段写代码已经耗掉了体力，这里重置，便于算账
    record["action"] = "玩耍"
    record["action_start"] = base
    pets.settle("P1", base + 60 * 60)
    expect("玩耍每块回 10 好感 5 心情",
           record["affection"] == 80 and record["mood"] == 65)
    expect("玩耍每块掉 3 体力", record["stamina"] == 91)

    # 体力 0 时点不动玩耍：它现在也耗体力，否则会白点一下变发呆
    record["stamina"] = 0
    record["mood"] = 100
    record["affection"] = 100
    record["action"] = "发呆"
    record["action_start"] = base
    expect("体力 0 不能玩耍",
           pets.switch("P1", "玩耍", base).get("reason") == "exhausted")
    expect("体力 0 还能发呆",
           pets.switch("P1", "发呆", base).get("ok") is True)
    record["stamina"] = 100

    # 玩耍挂机也给经验：每块 3 点（3 块 = 9）
    pexp = pets.get("PEXP")
    pexp.update({"level": 1, "exp": 0, "stamina": 100, "mood": 100,
                 "affection": 50, "action": "玩耍", "action_start": base})
    pets.settle("PEXP", base + 60 * 60)
    expect("玩耍每 20 分钟给 3 经验", int(pexp["exp"]) == 9)

    # 摸鱼：不扣好感，但银币和经验照给
    pmoyu = pets.get("PMOYU")
    pmoyu.update({"level": 15, "exp": 0, "stamina": 100, "mood": 100,
                  "affection": 50, "action": "摸鱼", "action_start": base})
    pets.settle("PMOYU", base + 60 * 60)
    expect("摸鱼不消耗好感", float(pmoyu["affection"]) == 50)
    expect("摸鱼照给银币和经验",
           int(pmoyu.get("coins_earned") or 0) == 36 and int(pmoyu["exp"]) == 9)

    # 好感 0 也能接着摸，不会被踢去发呆
    pmoyu.update({"affection": 0, "action": "摸鱼", "action_start": base})
    pets.settle("PMOYU", base + 60 * 60)
    expect("好感 0 也能继续摸鱼", pmoyu["action"] == "摸鱼")

    # 好感 0 时面板上也点得动摸鱼，别的活儿照样拦
    pmoyu.update({"affection": 0, "stamina": 100, "mood": 100,
                  "action": "摸鱼", "action_start": base})
    expect("好感 0 也能点摸鱼", pets.switch("PMOYU", "摸鱼", base).get("ok") is True)
    pmoyu.update({"affection": 0, "stamina": 100, "mood": 100,
                  "action": "发呆", "action_start": base})
    expect("好感 0 还是不能写代码",
           pets.switch("PMOYU", "写代码", base).get("reason") == "exhausted")

    pets.switch("P1", "发呆", base)
    pets.switch("P1", "玩耍", base)
    expect("玩耍会随机一个花样", record.get("play_kind") in PLAY_KINDS)
    play_status = status_line(pets.snapshot("P1", base + 1200))
    expect("状态里写明在玩什么", "玩耍中：" in play_status)
    expect("玩耍状态也是冒号+换行", play_status.count("\n") == 1)

    record["affection"] = 0
    record["stamina"] = 100
    record["mood"] = 100
    blocked = pets.switch("P1", "写代码", base)
    expect("好感度归零就干不了活", blocked.get("reason") == "exhausted")
    allowed = pets.switch("P1", "玩耍", base)
    expect("好感度归零还能玩耍", allowed.get("ok") is True)

    # 睡觉：每块 +5 体力 / +3 心情 / +3 好感，不花任何东西
    psleep = pets.get("PSLEEP")
    psleep.update({"level": 1, "stamina": 50, "mood": 50, "affection": 50,
                   "action": "睡觉", "action_start": base})
    pets.settle("PSLEEP", base + 60 * 60)          # 3 块
    expect("睡觉每块回 5 体力 3 心情 3 好感",
           psleep["stamina"] == 65 and psleep["mood"] == 59
           and psleep["affection"] == 59)

    # 体力为 0 也能睡（它是回体力的，不该被体力门槛拦）
    psleep.update({"stamina": 0, "mood": 100, "affection": 100,
                   "action": "发呆", "action_start": base})
    expect("体力 0 能睡觉", pets.switch("PSLEEP", "睡觉", base).get("ok") is True)
    psleep.update({"action": "睡觉", "action_start": int(time.time())})
    expect("状态写明在睡觉", "睡觉中" in status_line(pets.snapshot("PSLEEP")))
    expect("面板有睡觉按钮",
           any(label == "睡觉" for row in handler._pet_main_rows()
               for label, _ in row))

    # 新解锁：摸鱼 15 级
    u1_pet = handler.pets.get("U1")
    u1_pet["level"] = 1
    sender.events.clear()
    await feed("宠物 做 摸鱼", msg_id="pet-5")
    expect("1 级摸不了鱼", any("Lv.15" in text for _, text in sender.events))
    u1_pet["level"] = 15
    sender.events.clear()
    await feed("宠物 做 摸鱼", msg_id="pet-6")
    expect("15 级能摸鱼", any("摸鱼" in text for _, text in sender.events))

    # 22 级解锁红石电子技术
    handler.pets.get("U1")["level"] = 21
    sender.events.clear()
    await feed("宠物 做 红石电子技术", msg_id="pet-8")
    expect("21 级上不了红石", any("Lv.22" in text for _, text in sender.events))
    handler.pets.get("U1")["level"] = 22
    sender.events.clear()
    await feed("宠物 做 红石电子技术", msg_id="pet-9")
    expect("22 级能上红石", any("红石" in text for _, text in sender.events))

    # 黄桃罐头：唯一能哄好感的食物
    handler.cards.user("U1")["shards"] = 200
    handler.pets.get("U1")["affection"] = 50
    handler.pets.get("U1")["stamina"] = 10
    sender.events.clear()
    await feed("宠物 吃 黄桃罐头", msg_id="pet-10")
    expect("黄桃罐头能回好感", handler.pets.get("U1")["affection"] == 55)

    # 吃饭已经 6 样，按钮要能换行
    sender.events.clear()
    sender.panels.clear()
    await feed("宠物 吃饭", msg_id="pet-11")
    food_rows = sender.panels[0] if sender.panels else []
    food_datas = [b["action"]["data"] for row in food_rows for b in row["buttons"]
                  if b["action"]["data"].startswith("宠物 吃")]
    expect("六样食物都排上了按钮", len(food_datas) == 6)
    expect("食物按钮分成两行", len(food_rows) == 3)
    expect("按钮三个一行", all(len(row["buttons"]) <= 3 for row in food_rows))

    sender.events.clear()
    sender.panels.clear()
    await feed("宠物面板", msg_id="pet-12")
    main_rows = sender.panels[0] if sender.panels else []
    expect("主面板六个按钮排成 3+3",
           [len(row["buttons"]) for row in main_rows] == [3, 3])

    sender.events.clear()
    sender.panels.clear()
    await feed("宠物面板", msg_id="pet-0")
    expect("宠物面板发出带按钮的消息", bool(sender.panels))
    expect("宠物面板盖了名字和等级",
           any("大肥鱼" in text for _, text in sender.events))

    sender.events.clear()
    sender.panels.clear()
    await feed("宠物 工作", msg_id="pet-1")
    expect("工作有二级菜单", bool(sender.panels))
    labels = [b["render_data"]["label"] for row in sender.panels[0]
              for b in row["buttons"]]
    expect("二级菜单列出全部工作",
           {"写代码", "直播", "摸鱼", "cos大肥鱼", "AI模型研发"} <= set(labels))
    datas = [b["action"]["data"] for row in sender.panels[0] for b in row["buttons"]]
    expect("二级按钮的 data 就是命令", "宠物 做 写代码" in datas)

    sender.events.clear()
    handler.pets.get("U1")["level"] = 1
    await feed("宠物 做 直播", msg_id="pet-2")
    expect("等级不够会提示", any("Lv.5" in text for _, text in sender.events))

    handler.cards.user("U1")["shards"] = 0
    handler.pets.get("U1")["stamina"] = 30
    sender.events.clear()
    await feed("宠物 吃 大白饭", msg_id="pet-3")
    expect("银币不够吃不了", any("银币不够" in text for _, text in sender.events))

    handler.cards.user("U1")["shards"] = 100
    sender.events.clear()
    await feed("宠物 吃 大白饭", msg_id="pet-4")
    expect("吃饭扣银币并回体力", handler.cards.shards_of("U1") == 50)
    expect("吃饭附带 eat.gif", ("image", "eat.gif") in sender.events)

    sender.events.clear()
    handler.cards.user("U1")["shards"] = 100
    handler.pets.get("U1")["mood"] = 10
    await feed("宠物 吃 joja可乐", msg_id="pet-7")
    expect("吃别的也发动图", ("image", "eat.gif") in sender.events)

    # 吃饭会结算上一段，并把计时重置到当下
    u1 = handler.pets.get("U1")
    mood_cap, stamina_cap = limits(int(u1["level"]))
    u1["action"] = "写代码"
    u1["action_start"] = start_ts = int(time.time()) - 3600
    u1["stamina"] = stamina_cap
    u1["mood"] = mood_cap
    handler.cards.user("U1")["shards"] = 200
    sender.events.clear()
    sender.panels.clear()
    await feed("宠物 吃 大白饭", msg_id="pet-13")
    expect("吃饭结算上一段（144 工钱 - 50 饭钱）",
           handler.cards.shards_of("U1") == 294)
    expect("吃饭把计时重置到当下", u1["action_start"] != start_ts)
    expect("吃饭发吃饭动图", ("image", "eat.gif") in sender.events)
    bubbles = [text for kind, text in sender.events
               if kind in ("panel", "text")]
    expect("吃饭只回一条结果", len(bubbles) == 1 and "吃完了" in bubbles[0])
    eat_lines = bubbles[0].splitlines() if bubbles else []
    expect("三行：结算 → 吃饭结果 → 余额",
           len(eat_lines) == 3 and eat_lines[0].startswith("结算了")
           and eat_lines[1].startswith("吃完了")
           and eat_lines[2].startswith("银币余额"))
    expect("吃完饭不再发按钮面板", sender.panels == [])

    # 玩耍附 play.gif（和 eat.gif 同一套机制），每次点都发
    u1.update({"stamina": 100, "mood": 100, "affection": 100,
               "action": "发呆", "action_start": int(time.time())})
    sender.events.clear()
    await feed("宠物 玩耍", msg_id="pet-play-1")
    expect("点玩耍发 play.gif", ("image", "play.gif") in sender.events)
    sender.events.clear()
    await feed("宠物 玩耍", msg_id="pet-play-2")
    expect("重复点玩耍也发动图", ("image", "play.gif") in sender.events)

    # 面板不再合成语音
    sender.events.clear()
    await feed("宠物面板", msg_id="pet-panel-novoice")
    expect("面板不再发语音", not any(kind == "voice" for kind, _ in sender.events))
    sender.panels.clear()          # 唤出面板本身会发按钮，别弄脏后面的断言

    # 闲着而且三项都满时才拦
    u1["action"] = "发呆"
    u1["action_start"] = int(time.time())
    u1["stamina"] = stamina_cap
    u1["mood"] = mood_cap
    sender.events.clear()
    await feed("宠物 吃 大白饭", msg_id="pet-14")
    expect("饱着就不吃了", any("吃不下" in text for _, text in sender.events))
    expect("失败也不发按钮面板", sender.panels == [])

    # 属性低于 10：发消息时顶一句，半小时内不重复
    u1 = handler.pets.get("U1")
    u1.update({"stamina": 9, "mood": 100, "affection": 100,
               "action": "发呆", "action_start": int(time.time()), "warn_at": 0})
    warning = handler.pets.warn_text("U1")
    expect("属性低于 10 会顶一句", warning in WARN_POOLS["stamina"])
    expect("冷却里不重复提醒", handler.pets.warn_text("U1") == "")
    # 直接把上次提醒时间往前拨，模拟"已经过了半小时"
    u1["warn_at"] = int(time.time()) - WARN_COOLDOWN - 1
    expect("过了冷却还能提醒", bool(handler.pets.warn_text("U1")))
    expect("没养宠物不提醒", handler.pets.warn_text("查无此人") == "")
    # 阈值边界：严格小于 10，等于 10 不算
    expect("9 会提醒", bool(low_warning(
        {"stamina": 9, "mood": 50, "affection": 50})))
    expect("刚好 10 不提醒", low_warning(
        {"stamina": 10, "mood": 50, "affection": 50}) == "")
    expect("11 不提醒", low_warning(
        {"stamina": 11, "mood": 50, "affection": 50}) == "")
    expect("0 仍然提醒", bool(low_warning(
        {"stamina": 0, "mood": 50, "affection": 50})))
    expect("两项低挑合并池", low_warning(
        {"stamina": 9, "mood": 5, "affection": 50}) in WARN_POOLS["all"])
    expect("只有心情低挑心情池", low_warning(
        {"stamina": 50, "mood": 9, "affection": 50}) in WARN_POOLS["mood"])
    expect("阈值常量是 10", WARN_THRESHOLD == 10)
    expect("提示文案池够厚", all(len(pool) >= 6 for pool in WARN_POOLS.values()))
    expect("提示文案不重复",
           len(set(sum((list(v) for v in WARN_POOLS.values()), []))) ==
           sum(len(v) for v in WARN_POOLS.values()))
    all_warn = sum((list(v) for v in WARN_POOLS.values()), [])
    expect("提示都在 20 字左右", all(17 <= len(x) <= 24 for x in all_warn))
    # 调子统一，句式不统一：别又写回清一色「……真的……先…吧」
    expect("提示句式不雷同",
           sum(x.endswith("吧。") for x in all_warn) < len(all_warn) // 3
           and sum("……" in x for x in all_warn) < len(all_warn) // 2
           and sum("真的" in x for x in all_warn) < len(all_warn) // 4
           and len({x[:3] for x in all_warn}) >= 20)
    expect("饿了会惦记大白饭",
           sum("白饭" in x for x in WARN_POOLS["stamina"]) >= 5)

    u1["warn_at"] = 0
    sender.events.clear()
    await feed("随便说句话", msg_id="pet-warn")
    expect("发消息会触发低属性提醒",
           any(kind == "text" and text in WARN_POOLS["stamina"]
               for kind, text in sender.events))

    print("== 群友画像 ==")
    profiles = Profiles(temporary)
    for index in range(MEMORY_SUMMARIZE_EVERY):
        profiles.remember("G1", "U9", "画像测试", f"第{index}句话")
    expect("攒够就触发总结", profiles.should_summarize("G1", "U9"))

    async def profile_chat(system: str, text: str, images=None) -> str:
        expect("总结走的是总结提示词", "画像" in system)
        return "说话简短，爱用省略号。"

    summarized = await profiles.summarize("G1", "U9", profile_chat)
    expect("总结成功", summarized)
    expect("画像已存", "省略号" in profiles.summary_of("G1", "U9"))
    expect("总结后计数清零", not profiles.should_summarize("G1", "U9"))

    prompt_with_profile = build_system_prompt(
        "测试人设", speaker_name="画像测试",
        speaker_profile=profiles.summary_of("G1", "U9"),
    )
    expect("提示词带画像", "省略号" in prompt_with_profile)

    print("== 记忆库 ==")
    bank = MemoryBank(temporary)
    expect("空库拼出来是空串", bank.prompt_for("G2") == "")
    expect("记一条", bank.add("G2", "周四晚上打本", about="初春", about_id="U1"))
    expect("同一个人重复内容不再记",
           not bank.add("G2", "周四晚上打本", about="初春", about_id="U1"))
    expect("同一句话记到别人名下算新的",
           bank.add("G2", "周四晚上打本", about="庞月", about_id="U2"))
    expect("群级记录不带「关于谁」", bank.add("G2", "周五固定开黑"))
    notes_text = bank.prompt_for("G2")
    expect("提示词标出是谁的事", "[关于初春] 周四晚上打本" in notes_text)
    expect("群级记录标成「群里的」", "[群里的] 周五固定开黑" in notes_text)
    expect("按时间先后排", notes_text.index("初春") < notes_text.index("群里的"))

    reloaded = MemoryBank(temporary)
    expect("落盘后新实例读得到", len(reloaded.notes("G2")) == len(bank.notes("G2")))
    capped = MemoryBank(temporary, limit=1)
    expect("条数上限只留最新的", [n["text"] for n in capped.notes("G2")] == ["周五固定开黑"])

    notes_for_prompt = build_system_prompt("测试人设", memory_notes=notes_text)
    expect("提示词里有记忆库段落", "【记忆库】" in notes_for_prompt)

    print("== 记忆库工具（模型自己写）==")

    class ScriptedDeepSeek(DeepSeek):
        """把 _complete 换掉，离线演练「调 remember → 再作答」这条链。"""

        def __init__(self) -> None:
            super().__init__("fake-key")
            self.payloads: list[dict] = []

        async def _complete(self, payload: dict) -> dict:
            self.payloads.append(payload)
            names = [
                str((tool.get("function") or {}).get("name") or "")
                for tool in payload.get("tools") or []
            ]
            if "remember" in names:
                return {"tool_calls": [{
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "remember",
                        "arguments": '{"content": "喜欢无糖可乐", "about": "初春"}',
                    },
                }]}
            return {"content": "好，记下了。"}

    written: list[tuple[str, str]] = []

    async def fake_remember(content: str, about: str) -> str:
        written.append((content, about))
        return "记下了。"

    scripted = ScriptedDeepSeek()
    reply = await scripted.answer("系统", "我叫初春，喜欢无糖可乐", remember=fake_remember)
    expect("调完 remember 还能正常作答", reply == "好，记下了。")
    expect("remember 参数解析对了", written == [("喜欢无糖可乐", "初春")])
    expect("没开搜索时只给记忆工具",
           [t["function"]["name"] for t in scripted.payloads[0].get("tools") or []]
           == ["remember"])
    expect("最后一轮撤掉工具", not (scripted.payloads[-1].get("tools") or []))

    async def broken_remember(content: str, about: str) -> str:
        raise RuntimeError("模拟写盘失败")

    scripted = ScriptedDeepSeek()
    reply = await scripted.answer("系统", "我叫初春", remember=broken_remember)
    expect("记忆写失败也不耽误回答", reply == "好，记下了。")

    print("== 功能列表 / 更新日志 ==")
    long_text = "第一行内容" + chr(10) + ("填充" * 40) + chr(10) + "最后一行"
    chunks, dropped = split_changelog(long_text, 20, 8)
    expect("切片不丢字", "".join(chunks) == long_text)
    expect("每片不超限", all(len(chunk) <= 20 for chunk in chunks))
    expect("没超条数就不截断", not dropped)
    capped, was_dropped = split_changelog("字" * 100, 10, 3)
    expect("超条数会被截断", was_dropped and len(capped) == 3)

    (temporary / "help.txt").write_text("【测试功能列表】" + chr(10) + "抽卡", encoding="utf-8")
    (temporary / "changelog.txt").write_text("v9.9 测试日志", encoding="utf-8")
    sender.events.clear()
    await feed("功能列表", msg_id="m50")
    expect("功能列表发正文", any("【测试功能列表】" in text for kind, text in sender.events if kind == "text"))
    sender.events.clear()
    await feed("更新日志", msg_id="m51")
    expect("更新日志发正文", any("v9.9" in text for kind, text in sender.events if kind == "text"))
    (temporary / "help.txt").unlink()
    sender.events.clear()
    await feed("功能列表", msg_id="m52")
    expect("文件没了给兜底", any("还没写好" in text for kind, text in sender.events if kind == "text"))

    print("== 歌词接龙 ==")
    expect("识别结尾 ~", lyrics_line.lyric_line("明天你是否会想起~") == "明天你是否会想起")
    expect("识别全角 ～", lyrics_line.lyric_line("明天你是否会想起～") == "明天你是否会想起")
    expect("单个 ~ 不算歌词", lyrics_line.lyric_line("~") is None)
    expect("没有 ~ 不算歌词", lyrics_line.lyric_line("明天你是否会想起") is None)

    sample_lrc = "[00:01.00]作词 : 某人" + chr(10) + "[00:02.00]第一句" + chr(10) + "[00:03.00]第二句"
    expect("LRC 去掉署名", lyrics_line.clean_lrc(sample_lrc) == ["第一句", "第二句"])
    expect("本地找下一句", lyrics_line.next_line_in(["甲", "乙", "丙"], "乙") == "丙")
    expect("清洗模型回复", lyrics_line.clean_lyric_reply("下一句是：『丙』~") == "丙")
    expect("拒绝不知道", lyrics_line.clean_lyric_reply("【不知道】") == "")

    handler.lyric_library = False      # 自检不联网

    async def fake_lyric(system: str, text: str, images=None) -> str:
        return "昨天你写的日记"

    handler.lyric_chat = fake_lyric
    sender.events.clear()
    await feed("明天你是否会想起~", msg_id="m60")
    expect("接出下一句", sender.events == [("text", "昨天你写的日记~")])

    async def unknown_lyric(system: str, text: str, images=None) -> str:
        return "【不知道】"

    handler.lyric_chat = unknown_lyric
    sender.events.clear()
    await feed("这是一句不存在的歌词~", msg_id="m61")
    expect("接不上给兜底", sender.events == [("text", lyrics_line.LYRIC_FALLBACK)])

    sender.events.clear()
    await feed("~", msg_id="m62")
    expect("单独 ~ 不回复", sender.events == [])

    print("== 保存老婆 ==")
    sender.events.clear()
    await feed("保存老婆 测试老婆",
               images=[ImageRef(url=source.as_uri(), filename="source.png")], msg_id="m70")
    expect("保存老婆有回复", any("测试老婆" in text for kind, text in sender.events if kind == "text"))
    wife_records = json.loads((temporary / "wife" / "records.json").read_text(encoding="utf-8"))
    saved_wife = wife_records.get("测试老婆")
    expect("记录里出现「测试老婆」", bool(saved_wife))
    expect("老婆文件真的落盘", bool(saved_wife) and (temporary / "wife" / saved_wife).is_file())

    sender.events.clear()
    await feed("保存老婆", msg_id="m71")     # 沿用上一张图
    expect("不带名字也存", any("勉强帮你收下" in text for kind, text in sender.events if kind == "text"))

    handler.last_images.clear()
    sender.events.clear()
    await feed("保存老婆 再来一张", msg_id="m72")
    expect("没有图时提示", any("没有找到上一张图片" in text for kind, text in sender.events if kind == "text"))

    sender.events.clear()
    await feed("保存老婆 ../坏名字", msg_id="m73")
    expect("非法名字被拒", any("特殊字符" in text for kind, text in sender.events if kind == "text"))

    print("== 分片上传 ==")
    from . import api as api_module

    real_json, real_put = api_module.http_json_async, api_module.http_put
    calls: list[tuple] = []

    async def fake_json(method: str, url: str, payload: dict | None = None,
                        headers: dict | None = None, timeout: float = 30) -> dict:
        calls.append((method, url, payload))
        if url.endswith("/upload_prepare"):
            return {
                "upload_id": "up1", "block_size": "4",
                "parts": [
                    {"index": 0, "presigned_url": "https://cos/0", "block_size": "4"},
                    {"index": 1, "presigned_url": "https://cos/1", "block_size": "3"},
                ],
            }
        if url.endswith("/files"):
            return {"file_info": "INFO", "ttl": 300}
        return {}

    def fake_put(url: str, data: bytes, timeout: float = 180) -> int:
        calls.append(("PUT", url, data))
        return 200

    api_module.http_json_async = fake_json
    api_module.http_put = fake_put
    try:
        api = QQBotAPI("id", "secret")
        api._token = "t"
        api._token_expire_at = time.time() + 999
        big = temporary / "big.jpg"
        big.write_bytes(b"x" * 7)
        merged = await api._chunked_upload("G1", big, big.read_bytes())
    finally:
        api_module.http_json_async = real_json
        api_module.http_put = real_put
    puts = [call for call in calls if call[0] == "PUT"]
    expect("分片上传拿到 file_info", merged.get("file_info") == "INFO")
    expect("两片都 PUT 了", len(puts) == 2)
    expect("分片内容没串", [call[2] for call in puts] == [b"xxxx", b"xxx"])
    expect(
        "每片都通知完成",
        sum(1 for call in calls if str(call[1]).endswith("upload_part_finish")) == 2,
    )

    print("== 锻造 / 附魔 / 排行榜 ==")

    class StubRng:
        def __init__(self, values):
            self.values = list(values)

        def random(self):
            return self.values.pop(0)

        def uniform(self, low, high):
            return self.values.pop(0)

        def randint(self, low, high):
            return self.values.pop(0)

        def choice(self, seq):
            return seq[0]

    forge = handler.forge
    # 前面的卡池测试换过 handler.cards，forge 还指着旧实例；这里对齐一下。
    forge.cards = handler.cards
    forge.clear()
    expect(
        "锻造概率表第 5 回合后沿用",
        outcome_table("stone", 9) == outcome_table("stone", 5),
    )
    expect("石剑倍率 1.2~1.4", SWORDS["stone"].factor == (1.2, 1.4))
    expect("钻石剑倍率 1.4~1.6", SWORDS["diamond"].factor == (1.4, 1.6))
    expect("幸运暴击 1.8~2.3", CRIT_FACTOR == (1.8, 2.3))
    expect(
        "s2 附魔书就是这六本",
        BOOK_NAMES == ("经验修补", "重构", "锋利", "治愈", "时运", "最后一舞"),
    )
    expect(
        "s2 下架的 s1 书抽不到也贴不上",
        parse_book("附魔 升格") is None
        and parse_book("附魔 保护") is None
        and parse_book("附魔 掠夺") is None,
    )
    expect(
        "下界合金剑概率恒定 20/50/30",
        outcome_table("netherite", 9) == (0.20, 0.50, 0.30),
    )
    expect(
        "下界合金剑 1.6~1.8、暴击 20%",
        SWORDS["netherite"].factor == (1.6, 1.8)
        and SWORDS["netherite"].crit_chance == 0.20,
    )
    expect("下界合金剑不能直接买", parse_sword("锻造 下界合金剑") is None)
    expect(
        "用力砸N 解析：不写数字/1/带空格都是 1 下",
        parse_strike("用力砸") == 1
        and parse_strike("用力砸1") == 1
        and parse_strike("用力砸 1") == 1,
    )
    expect(
        "用力砸5 解析成 5 下",
        parse_strike("用力砸5") == 5 and parse_strike("用力砸 5") == 5,
    )
    expect("用力砸0 解析成 0（文案层提示至少砸一下）", parse_strike("用力砸0") == 0)
    expect("用力砸abc 不算命令", parse_strike("用力砸abc") is None)
    expect(
        "石剑付不起也免费开局",
        forge.start("G1", "F1", SWORDS["stone"])["paid"] == 0
        and forge.active("G1", "F1") is not None,
    )
    expect("开局完成度 100", forge.active("G1", "F1").completion == 100)
    forge.clear()
    forged = forge.start("G1", "F1", SWORDS["iron"])
    expect("铁剑付不起明确拒绝", not forged["ok"] and forged["reason"] == "poor")
    handler.cards.grant_shards("F1", 1000)
    forged = forge.start("G1", "F1", SWORDS["iron"])
    expect(
        "铁剑扣 250 银币",
        forged["paid"] == 250 and handler.cards.shards_of("F1") == 750,
    )
    forge.clear()

    handler.cards.grant_shards("F1", 1000)
    forged = forge.start("G1", "F1", SWORDS["diamond"])
    expect(
        "钻石剑扣 500 银币、初始价值 500",
        forged["paid"] == 500 and forged["value"] == 500,
    )
    forge.clear()

    handler.cards.grant_shards("F1", 1000)
    forge.start("G1", "F1", SWORDS["stone"])
    forge.rng = StubRng([0.0, 40])
    result = forge.strike("G1", "F1")
    expect(
        "锻造失败只掉完成度、价值不变",
        result is not None
        and result.failed
        and not result.destroyed
        and abs(result.value - 50) < 1e-9
        and abs(result.completion - 60) < 1e-9
        and forge.active("G1", "F1") is not None,
    )
    forge.rng = StubRng([0.0, 40])
    forge.strike("G1", "F1")
    expect(
        "完成度继续掉",
        abs(forge.active("G1", "F1").completion - 20) < 1e-9,
    )
    forge.rng = StubRng([0.0, 50])
    result = forge.strike("G1", "F1")
    expect(
        "完成度归零剑毁、局消失",
        result is not None
        and result.destroyed
        and result.completion == 0
        and forge.active("G1", "F1") is None,
    )

    # 连砸：一条命令算 n 回合，结果合成一条消息。
    forge.clear()
    forge.start("G1", "F1", SWORDS["stone"])
    forge.rng = StubRng([0.5, 0.99, 1.2] * 3)
    batch = forge.strike_many("G1", "F1", 3)
    expect(
        "连砸3下按回合逐锤结算",
        len(batch) == 3
        and [item.turns for item in batch] == [1, 2, 3]
        and abs(batch[2].value - 86.4) < 1e-9,
    )
    batch_reply = strike_batch_text(batch)
    expect(
        "连砸结果一条消息三行",
        batch_reply.count("已进行") == 3
        and "（第 1 回合）" in batch_reply
        and "（第 3 回合）" in batch_reply,
    )

    forge.clear()
    forge.start("G1", "F1", SWORDS["stone"])
    forge.rng = StubRng([0.5, 0.99, 1.2, 0.0, 40])
    stopped = forge.strike_many("G1", "F1", 5)
    expect(
        "连砸碰到锻造失败就停",
        len(stopped) == 2
        and stopped[-1].failed
        and not stopped[-1].destroyed
        and [item.turns for item in stopped] == [1, 2],
    )
    expect(
        "停下来时剑还在、完成度照常扣",
        forge.active("G1", "F1") is not None
        and abs(forge.active("G1", "F1").completion - 60) < 1e-9,
    )

    forge.clear()
    forge.start("G1", "F1", SWORDS["stone"])
    forge.active("G1", "F1").completion = 40
    forge.rng = StubRng([0.0, 50])
    broken = forge.strike_many("G1", "F1", 5)
    expect(
        "连砸第一锤就崩也照常收尾",
        len(broken) == 1
        and broken[-1].destroyed
        and forge.active("G1", "F1") is None,
    )
    expect(
        "崩了的那锤在合并回复里写明",
        "剑身彻底崩了" in strike_batch_text(broken),
    )

    forge.start("G1", "F1", SWORDS["stone"])
    forge.rng = StubRng([0.5, 0.99, 1.2])
    result = forge.strike("G1", "F1")
    expect(
        "增加按倍率上涨",
        result is not None
        and abs(result.value - 60) < 1e-9
        and abs(result.completion - 100) < 1e-9
        and not result.crit,
    )

    # 锋利：本局每次「增加」都吃剑的最大倍率，暴击仍走 1.8~2.3。
    handler.cards.grant_shards("F1", 1000)
    forge.clear()
    forge.start("G1", "F1", SWORDS["stone"])
    handler.cards.user("F1")["books"] = {"锋利": 1}
    handler.cards._save()
    expect("贴锋利成功", forge.use_book("G1", "F1", "锋利")["ok"])
    forge.rng = StubRng([0.5, 0.99])
    sharp = forge.strike("G1", "F1")
    expect(
        "锋利把增加固定成石剑最大倍率 1.4",
        sharp is not None and abs(sharp.value - 70) < 1e-9 and not sharp.crit,
    )
    forge.rng = StubRng([0.5, 0.02, 2.3])
    sharp_crit = forge.strike("G1", "F1")
    expect(
        "锋利不影响暴击倍率（仍 1.8~2.3）",
        sharp_crit is not None and sharp_crit.crit
        and abs(sharp_crit.value - 161) < 1e-9,
    )
    expect(
        "锋利一局只能贴一次",
        forge.use_book("G1", "F1", "锋利")["reason"] == "already",
    )
    forge.clear()

    handler.cards.grant_shards("F1", 1000)
    forge.start("G1", "F1", SWORDS["stone"])
    handler.cards.user("F1")["books"] = {"重构": 1}
    handler.cards._save()
    expect("贴重构给两次重掷", forge.use_book("G1", "F1", "重构").get("left") == 2)
    # 这一锤被重构罩着：出「增加」就必暴击，连暴击判定都不掷。
    forge.rng = StubRng([0.5, 2.2])
    deferred = forge.strike("G1", "F1")
    expect(
        "重构挂着这一锤",
        deferred is not None and deferred.deferred and deferred.reforge_left == 2,
    )
    expect(
        "重构这一锤必定暴击",
        deferred.crit and deferred.reforge_crit and abs(deferred.value - 110) < 1e-9,
    )
    expect("重构暴击有提示", "重构生效" in strike_text(deferred))
    forge.rng = StubRng([0.5, 2.3])
    first = forge.reforge("G1", "F1")
    expect(
        "重掷出来的增加也必暴击",
        first["ok"] and first["left"] == 1
        and first["result"].reforge_crit and abs(first["result"].value - 115) < 1e-9,
    )
    forge.rng = StubRng([0.5, 2.4])
    second = forge.reforge("G1", "F1")
    expect(
        "第二次重掷落定",
        second["ok"] and second["left"] == 0
        and second["result"].reforge_crit and abs(second["result"].value - 120) < 1e-9,
    )
    expect("重掷落定后不残留额度", forge.active("G1", "F1").reforge_left == 0)
    forge.clear()

    # 时运：暴击率翻五倍，两次暴击后失效。
    handler.cards.grant_shards("F1", 1000)
    forge.start("G1", "F1", SWORDS["stone"])
    handler.cards.user("F1")["books"] = {"时运": 1}
    handler.cards._save()
    expect("贴时运成功", forge.use_book("G1", "F1", "时运")["ok"])
    forge.rng = StubRng([0.5, 0.1, 2.2])
    first = forge.strike("G1", "F1")
    expect(
        "时运把石剑暴击率抬到 15%",
        first is not None and first.crit and first.fortune_crit
        and abs(first.value - 110) < 1e-9,
    )
    forge.rng = StubRng([0.5, 0.1, 2.3])
    second = forge.strike("G1", "F1")
    expect(
        "时运第二次暴击后失效",
        second is not None and second.crit and second.fortune_crit
        and not forge.active("G1", "F1").fortune,
    )
    forge.rng = StubRng([0.5, 0.1, 1.2])
    third = forge.strike("G1", "F1")
    expect("时运失效后回到基础暴击率", third is not None and not third.crit)
    forge.clear()

    # 经验修补：增加也是 +5（取代基础 +3），不变 +5。
    handler.cards.grant_shards("F1", 1000)
    forge.start("G1", "F1", SWORDS["stone"])
    forge.rng = StubRng([0.0, 40])
    forge.strike("G1", "F1")
    handler.cards.user("F1")["books"] = {"经验修补": 1}
    handler.cards._save()
    expect("贴经验修补成功", forge.use_book("G1", "F1", "经验修补")["ok"])
    forge.rng = StubRng([0.5, 0.99, 1.2])
    up = forge.strike("G1", "F1")
    expect("经验修补：成功也只回 5（不是 8）", abs(up.completion - 65) < 1e-9)
    forge.rng = StubRng([0.95])
    same = forge.strike("G1", "F1")
    expect("经验修补：不变时 +5 完成度", abs(same.completion - 70) < 1e-9)
    forge.clear()

    # 治愈：暴击时额外回 15 完成度，一局最多两次。
    handler.cards.grant_shards("F1", 1000)
    forge.start("G1", "F1", SWORDS["stone"])
    handler.cards.user("F1")["books"] = {"治愈": 1}
    handler.cards._save()
    expect("贴治愈成功", forge.use_book("G1", "F1", "治愈")["ok"])
    forge.active("G1", "F1").completion = 50.0
    forge.rng = StubRng([0.5, 0.02, 2.2])
    healed = forge.strike("G1", "F1")
    expect(
        "治愈：暴击时基础 +3 之外再 +15",
        healed is not None and healed.healed and healed.heal_left == 1
        and abs(healed.completion - 68) < 1e-9,
    )
    expect("治愈在回复里有提示", "治愈" in strike_text(healed))
    forge.rng = StubRng([0.5, 0.02, 2.2])
    healed2 = forge.strike("G1", "F1")
    expect(
        "治愈第二次仍然生效",
        healed2 is not None and healed2.healed and healed2.heal_left == 0
        and abs(healed2.completion - 86) < 1e-9,
    )
    forge.rng = StubRng([0.5, 0.02, 2.2])
    healed3 = forge.strike("G1", "F1")
    expect(
        "治愈两次用尽后不再回",
        healed3 is not None and not healed3.healed
        and abs(healed3.completion - 89) < 1e-9,
    )
    forge.clear()

    # 最后一舞：立刻 +30，三回合后 -30，那之前收工收益减半。
    handler.cards.grant_shards("F1", 1000)
    forge.start("G1", "F1", SWORDS["stone"])
    handler.cards.user("F1")["books"] = {"最后一舞": 2}
    handler.cards._save()
    forge.active("G1", "F1").completion = 60.0
    dance = forge.use_book("G1", "F1", "最后一舞")
    expect(
        "最后一舞立刻 +30 完成度",
        dance["ok"] and abs(forge.active("G1", "F1").completion - 90) < 1e-9,
    )
    expect("最后一舞贴完说清了代价", "最后一舞" in book_text(dance, "最后一舞"))
    expect(
        "最后一舞一局只能贴一次",
        forge.use_book("G1", "F1", "最后一舞")["reason"] == "already",
    )
    # 三锤「不变」，第三锤落地时正好到期，完成度从 90 扣回 60。
    for _ in range(2):
        forge.rng = StubRng([0.95])
        forge.strike("G1", "F1")
    expect(
        "最后一舞没到三回合不扣",
        abs(forge.active("G1", "F1").completion - 90) < 1e-9,
    )
    forge.rng = StubRng([0.95])
    dropped = forge.strike("G1", "F1")
    expect(
        "最后一舞三回合到点扣回 30",
        dropped is not None and dropped.dance_drop
        and abs(dropped.completion - 60) < 1e-9,
    )
    expect("最后一舞扣减有提示", "最后一舞" in strike_text(dropped))
    forge.clear()

    # 扣回之前收工：收益减半。
    handler.cards.grant_shards("F1", 1000)
    forge.start("G1", "F1", SWORDS["stone"])
    handler.cards.user("F1")["books"] = {"最后一舞": 1}
    handler.cards._save()
    for _ in range(3):
        forge.rng = StubRng([0.95])
        forge.strike("G1", "F1")
    forge.use_book("G1", "F1", "最后一舞")
    dance_end = forge.end_forge("G1", "F1", "最后一舞测试")
    expect(
        "三回合内收工收益减半",
        dance_end["ok"] and dance_end["halved"]
        and dance_end["reward"] == round(reward_for(50, 100) * LAST_DANCE_PENALTY),
    )
    expect("收工回复里写明减半", "最后一舞" in end_text(dance_end))
    expect(
        "减半后的收益不会被排行榜按公式算回去",
        any(
            item["name"] == "最后一舞测试"
            and item["value"] == round(reward_for(50, 100) * LAST_DANCE_PENALTY)
            for item in handler.forge_rank.leaderboard()
        ),
    )
    forge.clear()

    handler.cards.grant_shards("F1", 1000)
    forge.start("G1", "F1", SWORDS["stone"])
    forge.active("G1", "F1").books_used = 6
    handler.cards.user("F1")["books"] = {"时运": 1}
    handler.cards._save()
    denied = forge.use_book("G1", "F1", "时运")
    expect(
        "只剩 1 个次数时还能再贴一本",
        denied["ok"] and denied["books_left"] == 0,
    )
    handler.cards.user("F1")["books"] = {"时运": 1}
    handler.cards._save()
    denied = forge.use_book("G1", "F1", "时运")
    expect("用满 7 次后拒绝并保留书", denied["reason"] == "limit")
    forge.clear()

    handler.cards.grant_shards("F1", 1000)
    forge.start("G1", "F1", SWORDS["stone"])
    forge.rng = StubRng([0.5, 0.99, 1.2] * 3)
    for _ in range(3):
        forge.strike("G1", "F1")
    ended = forge.end_forge("G1", "F1", "测试锻造人")
    expect(
        "收工按收益曲线发银币",
        ended["ok"] and ended["reward"] == 86 and ended["completion"] == 100,
    )
    expect("收工记进排行榜", ended["rank"] == 1)
    records = handler.forge_rank.leaderboard()
    expect(
        "排行榜记录正确",
        records
        and records[0]["value"] == 86
        and records[0]["name"] == "测试锻造人"
        and records[0]["sword"] == "石剑",
    )
    reloaded = ForgeRank(paths.data / "forge_rank.json")
    expect("排行榜落盘、重启不丢", reloaded.leaderboard()[0]["value"] == 86)
    expect("排行榜文字版有名次", "1st" in rank_text(records))

    # 排行榜存了「锻造价值 + 完成度」，读盘时按当前公式重算（改 K 不用手动改榜）。
    recalc_path = paths.data / "forge_rank_recalc.json"
    recalc_path.write_text(
        json.dumps(
            [
                {"value": 999999, "forge_value": 10000, "completion": 100,
                 "user_id": "U9", "name": "重算", "time": "2026-10-24 12:00"},
                {"value": 1234, "user_id": "U8", "name": "老格式",
                 "time": "2026-10-24 11:00"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    recalc = ForgeRank(recalc_path)
    recalc_rows = recalc.leaderboard()
    expect(
        "排行榜读盘时按当前公式重算",
        recalc_rows
        and recalc_rows[0]["value"] == reward_for(10000, 100) == 5493,
    )
    expect(
        "没源数据的老记录沿用存下来的收益",
        any(item["user_id"] == "U8" and item["value"] == 1234 for item in recalc_rows),
    )
    recalc.clear()
    rank2 = ForgeRank(recalc_path)
    rank2.record(1, "U7", "带源", when=datetime.datetime(2026, 10, 24, 12, 0),
                 forge_value=10000, completion=100)
    saved = json.loads(recalc_path.read_text(encoding="utf-8"))
    expect(
        "新记录存下价值/完成度并按公式算收益",
        saved and saved[0]["value"] == 5493
        and saved[0]["forge_value"] == 10000.0
        and saved[0]["completion"] == 100.0,
    )
    recalc.clear()

    # 完成度不够 100 时，收益按比例打折；锻造成功会回复 3 完成度。
    handler.cards.grant_shards("F1", 1000)
    forge.start("G1", "F1", SWORDS["stone"])
    forge.rng = StubRng([0.0, 40, 0.5, 0.99, 1.2, 0.5, 0.99, 1.2])
    forge.strike("G1", "F1")  # 失败：完成度 100 → 60
    expect("失败后完成度 60", forge.active("G1", "F1").completion == 60)
    forge.strike("G1", "F1")  # ×1.2 → 价值 60，完成度 60 → 63
    expect("锻造成功回复 3 完成度", forge.active("G1", "F1").completion == 63)
    forge.strike("G1", "F1")  # ×1.2 → 价值 72，完成度 63 → 66
    expect("完成度回复有上限", forge.active("G1", "F1").completion == 66)
    ended = forge.end_forge("G1", "F1", "测试锻造人")
    expect(
        "收益按完成度打折",
        ended["ok"] and ended["completion"] == 66
        and ended["reward"] == round(0.66 * 5000 * math.log1p(72 / 5000)),
    )
    forge.clear()

    # 收益曲线：小分数≈原值，大分数被对数压住，完成度是等比折扣。
    expect(
        "小分局收益几乎不变",
        reward_for(462, 100) == 442 and reward_for(1098, 100) == 993,
    )
    expect(
        "高分局被对数压住",
        reward_for(682494, 13) == 3200 and reward_for(23653522, 100) == 42310,
    )
    expect(
        "完成度乘在 log 外面",
        abs(reward_for(1_000_000, 100) - 2 * reward_for(1_000_000, 50)) <= 1,
    )

    print("== 新锻造系统（按钮面板） ==")
    new_forge = handler.forge_new
    # 前面的卡池测试换过 handler.cards，新锻造还指着旧实例；这里对齐一下。
    new_forge.cards = handler.cards
    new_forge.clear()
    handler.checkin_renderer = None
    handler.forge.rng = random

    expect(
        "四种材料的价格与初始属性（强度/硬度/韧性）",
        [(m.name, m.price, m.attrs) for m in MATERIALS.values()]
        == [("草钢", 140, (20, 15, 15)), ("陨铁", 280, (25, 30, 20)),
            ("弹簧钢", 620, (35, 30, 45)), ("强化合金", 1288, (60, 55, 40))],
    )
    expect(
        "每种材料的刀型概率加起来是 1",
        all(abs(sum(m.knives) - 1.0) < 1e-9 for m in MATERIALS.values()),
    )
    expect(
        "八种刀型、价值依次上升（骷髅 275 / 锯齿 450 / 蝴蝶 650 / 爪子 900）",
        [k.name for k in KNIVES]
        == ["廓尔喀刀", "折叠刀", "骷髅匕首", "刺刀", "锯齿爪刀",
            "蝴蝶刀", "爪子刀", "M9刺刀"]
        and [k.base for k in KNIVES] == [120, 230, 310, 390, 490, 680, 920, 1200],
    )
    expect(
        "每种材料的刀型概率表和刀型数量对得上",
        all(len(m.knives) == len(KNIVES) for m in MATERIALS.values()),
    )
    expect(
        "十二个基础模板 + 四个特殊模板（全蓝淬火 15×、三种宝石 10×）",
        len(PATTERNS) == 12
        and PATTERN_MULTIPLIER["全蓝淬火"] == 15.0
        and PATTERN_MULTIPLIER["蓝宝石"] == 10.0
        and PATTERN_MULTIPLIER["红宝石"] == 10.0
        and PATTERN_MULTIPLIER["绿宝石"] == 10.0
        and all(name not in {p.name for p in PATTERNS}
                for name in ("蓝宝石", "红宝石", "绿宝石", "全蓝淬火")),
    )
    expect(
        "水淬 / 油淬的图案概率各自加起来是 1",
        all(abs(sum(QUENCH_PROBABILITIES[name]) - 1.0) < 1e-9
            for name in QUENCH_NAMES),
    )
    expect(
        "测试改成正态：分数 ~ N(属性, 属性/10)（属性 100 平均 100 分、150 平均 150 分）",
        mean_score(0) == 0 and mean_score(50) == 50
        and mean_score(100) == 100 and mean_score(150) == 150
        and score_sigma(100) == 10 and score_sigma(50) == 5,
    )
    rnd = random.Random(7)
    samples = [score_for(75, rnd) for _ in range(600)]
    expect(
        "正态出分：均值贴着 75，而且不是死数",
        abs(sum(samples) / len(samples) - 75) < 4 and len(set(samples)) > 10,
    )
    expect(
        "标准差 = 属性的 1/10：反复测，分差能拉开 20 分以上",
        max(samples) - min(samples) >= 20,
    )
    expect(
        "出分没有上限（能考过 100）、下限仍是 0",
        max(score_for(100, random.Random(i)) for i in range(300)) > 100
        and all(score_for(-50, random.Random(i)) >= 0 for i in range(50)),
    )
    expect(
        "高分不再爆炸：300 分给满 T，超过 300 的部分按 35% 折算",
        round(performance(300), 3) == 4.35
        and effective_score(400) == 335.0
        and round(performance(400), 3) == 5.955,
    )
    expect(
        "总价值 = B×P×T×材料系数（M9刺刀 + 红宝石 + 300 分 = 52200）",
        value_of(MATERIALS["强化合金"], "M9刺刀", "红宝石", 300) == 52200,
    )
    expect(
        "0 分总价值为 0（不保底）",
        value_of(MATERIALS["强化合金"], "M9刺刀", "红宝石", 0) == 0,
    )
    expect(
        "价格反推后材料系数全是 1.00",
        all(m.payout == 1.0 for m in MATERIALS.values()),
    )
    expect(
        "波动半径 ±10 起步、逐锤 +1、封顶 ±15",
        [hammer_radius(i) for i in (0, 1, 5, 6, 7, 40)]
        == [10, 11, 15, 15, 15, 15],
    )
    expect(
        "线性曲线：塑性 0/20/50/80/100 → 期望 -10 / -6 / 0 / +6 / +10",
        (hammer_expect(0), hammer_expect(20), hammer_expect(50),
         hammer_expect(80), hammer_expect(100)) == (-10, -6, 0, 6, 10),
    )
    expect(
        "磨损：三项越均匀越新（全同 → 崭新，差一大截 → 战痕）",
        wear_value((80, 80, 80)) <= 0.07
        and wear_value((30, 60, 90)) >= 0.45
        and wear_grade(0.02)[1] == 1.15
        and wear_grade(0.10)[1] == 1.05
        and wear_grade(0.30)[1] == 1.00
        and wear_grade(0.40)[1] == 0.95
        and wear_grade(0.60)[1] == 0.85,
    )
    expect(
        "塑性期望直接平移范围（塑性 60、半径 10 → -8 ~ +12）",
        hammer_range(10, 60) == (-8, 12)
        and hammer_range(10, 50) == (-10, 10)
        and hammer_range(10, 100) == (0, 20),
    )
    expect("开局塑性是区间，而且贵料不一定高",
           [m.plasticity for m in MATERIALS.values()]
           == [(62, 78), (52, 68), (52, 72), (45, 60)])

    class FixedRng:
        """random() 恒为 0（刀型/图案都抽第一个），randint 取上限、gauss 取均值。

        ``choice`` 不能死给第一个 —— 锻造 id 是靠 choice 拼的，全给同一个字符
        会让 id 一直撞、白白卡住。
        """

        def __init__(self):
            self.turn = 0

        def random(self):
            return 0.0

        def choice(self, seq):
            self.turn += 1
            return seq[self.turn % len(seq)]

        def randint(self, low, high):
            return high

        def gauss(self, mu, sigma):
            return mu

    class CrashRng(FixedRng):
        """randint 取下限：每锤都把属性往下砸，用来测归零报废。"""

        def randint(self, low, high):
            # 比下限还低 100：确保盖过塑性加成，直接砸穿
            return low - 100

    def nf_button(label):
        rows = sender.panels[-1] if sender.panels else []
        for row in rows:
            for button in row["buttons"]:
                if button["render_data"]["label"] == label:
                    return button["action"]["data"]
        return ""

    def nf_labels():
        rows = sender.panels[-1] if sender.panels else []
        return [button["render_data"]["label"]
                for row in rows for button in row["buttons"]]

    async def nf(content, user="N1", name="锻造测试"):
        sender.events.clear()
        sender.panels.clear()
        await handler.handle(Incoming(
            group_openid="G1", user_openid=user, username=name,
            content=content, msg_id="nf",
        ))

    async def nf_click(action, argument="", user="N1", name="锻造测试"):
        session = new_forge.active("G1", user)
        await nf(panel_data(session, action, argument), user=user, name=name)

    handler.cards.grant_shards("N1", 3000)
    new_forge.rng = FixedRng()

    await nf("锻造")
    expect(
        "「锻造」发的是带按钮的选材面板",
        bool(sender.panels) and bool(sender.events) and sender.events[0][0] == "panel",
    )
    expect(
        "选材面板 = 四种材料（按钮上只写材料名，不带价格）",
        nf_labels() == ["草钢", "陨铁", "弹簧钢", "强化合金"],
    )
    expect(
        "选材按钮排两行两列（一行四个太窄会被截）",
        bool(sender.panels) and len(sender.panels[-1]) == 2
        and all(len(row["buttons"]) == 2 for row in sender.panels[-1]),
    )
    session = new_forge.active("G1", "N1")
    expect("开局建好了，第一块面板的序号是 1", session is not None and session.seq == 1)

    shards_before = handler.cards.shards_of("N1")
    await nf(nf_button("草钢"))
    session = new_forge.active("G1", "N1")
    expect("选材扣 140 银币", handler.cards.shards_of("N1") == shards_before - 140)
    expect(
        "买完料进锻造阶段，刀型和初始属性都定下来",
        session.stage == STAGE_FORGE
        and session.knife == "廓尔喀刀"
        and session.attrs == [20, 15, 15],
    )
    expect("锻造面板 = 用力砸 / 结束锻造", nf_labels() == ["用力砸", "结束锻造"])
    expect(
        "面板写着下一锤的实际范围（±10 被塑性 +6 平移成 -4~+16）",
        bool(sender.events) and "下一锤 -4 ~ +16" in sender.events[0][1],
    )

    _session = new_forge.active("G1", "N1")
    _rejected = new_forge.act(
        "G1", "N1", _session.forge_id, _session.seq, ACTION_RECOVER, "",
    )
    expect(
        "没砸够 5 锤不能回火",
        not _rejected["ok"] and "回火还差" in _rejected["reply"],
    )

    old_strike = nf_button("用力砸")
    await nf(old_strike)
    session = new_forge.active("G1", "N1")
    expect(
        "用力砸一次：次数 +1、三项属性各 +16（半径 10 + 塑性期望 6）",
        session.hammers == 1 and session.attrs == [36, 31, 31],
    )
    expect(
        "面板写出这一锤的增减（+16 = 半径 10 + 塑性 6）",
        bool(sender.events)
        and "强度 36（+16）" in sender.events[0][1],
    )
    expect(
        "锻造面板不再写「-5~+5、砸够了就结束锻造」那行说明",
        bool(sender.events) and "砸够了就" not in sender.events[0][1],
    )
    expect(
        "删掉说明后面板不空：底下有一句随机闲话",
        any(line in sender.events[0][1]
            for line in FORGE_FLAVOR + FORGE_FLAVOR_OPEN + FORGE_FLAVOR_DANGER),
    )
    await nf(old_strike)
    expect(
        "同一块面板点第二次不生效（面板只能点一次）",
        new_forge.active("G1", "N1").hammers == 1
        and any("用过" in text for kind, text in sender.events if kind == "text"),
    )

    for _ in range(4):
        await nf_click(ACTION_HAMMER)
    session = new_forge.active("G1", "N1")
    expect(
        "连砸 5 锤：半径 10/11/12/13/14 + 线性加成（6/5/4/4/3），属性 102/97/97",
        session.hammers == 5 and session.attrs == [102, 97, 97],
    )
    expect("没有次数上限：面板照样给「用力砸」", "用力砸" in nf_labels())
    expect("砸够 5 锤后出现「回火」按钮", "回火" in nf_labels())
    expect("每砸一锤塑性 -3（78 → 63）", new_forge.active("G1", "N1").plasticity == 63)

    await nf_click(ACTION_RECOVER)
    session = new_forge.active("G1", "N1")
    expect(
        "回火按正态重摇（均值固定 55），并记一次",
        session.recoveries == 1 and session.plasticity == 55,
    )
    expect("回火不动属性", session.attrs == [102, 97, 97])
    expect("刚回火完不能马上再回火", "回火" not in nf_labels())

    await nf_click(ACTION_FINISH)
    expect("结束锻造进淬火面板", nf_labels() == ["水淬", "油淬"])
    expect(
        "淬火面板写着当前属性",
        bool(sender.events) and "强度 102" in sender.events[0][1],
    )

    before_quench = handler.cards.shards_of("N1")
    await nf_click(ACTION_WATER)
    result = sender.events[0][1] if sender.events else ""
    expect("淬火后只回一条文字结果", bool(sender.events) and sender.events[0][0] == "text")
    expect(
        "结果里三项得分 102/97/97、总分 296、总价值 463（磨损崭新 ×1.15）",
        "强度 102 → 102 分" in result
        and "硬度 97 → 97 分" in result
        and "测试得分 296（基准满分 300）" in result
        and "崭新出厂" in result
        and "463" in result,
    )
    expect(
        "总价值直接加进余额",
        handler.cards.shards_of("N1") == before_quench + 463,
    )
    expect("一局结束局面就清掉", new_forge.active("G1", "N1") is None)

    mine = next(
        (item for item in handler.forge_rank.leaderboard()
         if item["name"] == "锻造测试"), None,
    )
    expect(
        "排行榜记下刀型 / 图案 / 分数 / 总价值",
        mine is not None
        and mine["knife"] == "廓尔喀刀"
        and mine["pattern"] == "狩猎网格"
        and mine["score"] == 296
        and mine["value"] == 463,
    )

    # 属性归零：这一炉直接报废，材料钱不退、一分收益都没有
    handler.cards.grant_shards("N3", 1000)
    new_forge.rng = CrashRng()
    await nf("锻造", user="N3", name="报废测试")
    await nf(nf_button("草钢"), user="N3", name="报废测试")
    before_crash = handler.cards.shards_of("N3")
    for _ in range(6):
        if new_forge.active("G1", "N3") is None:
            break
        await nf_click(ACTION_HAMMER, user="N3", name="报废测试")
    expect("任一属性归零 → 这一局当场结束", new_forge.active("G1", "N3") is None)
    expect(
        "失败提示写明报废、没有任何收益",
        any("报废" in text and "没有任何收益" in text
            for kind, text in sender.events if kind == "text"),
    )
    expect(
        "报废不返材料钱、也不发收益",
        handler.cards.shards_of("N3") == before_crash,
    )

    # 银币不足：面板先摆出来，选贵的料被拒，但局面和面板都不作废
    new_forge.rng = FixedRng()
    handler.cards.user("N2")["shards"] = 10
    handler.cards._save()
    await nf("锻造", user="N2", name="穷鬼")
    expect("银币不够也能先把面板摆出来", nf_labels()[:1] == ["草钢"])
    await nf(nf_button("强化合金"), user="N2", name="穷鬼")
    expect(
        "买不起的料直接拒绝",
        any("银币不够" in text for kind, text in sender.events if kind == "text"),
    )
    expect(
        "被拒后还停在选材、面板可以接着点",
        new_forge.active("G1", "N2") is not None
        and new_forge.active("G1", "N2").stage == STAGE_PICK,
    )

    await nf("锻造", user="N2", name="穷鬼")
    expect(
        "已有没做完的一局时再开被拒",
        any("没做完" in text for kind, text in sender.events if kind == "text"),
    )
    new_forge.clear()

    for command in ("锻造 石剑", "用力砸", "结束锻造", "收工", "附魔 锋利", "重构"):
        await nf(command)
        expect(f"旧锻造命令「{command}」完全没反应", sender.events == [])

    await nf("锻造排行榜")
    expect(
        "排行榜文字兜底",
        any("锻造排行榜" in text for kind, text in sender.events if kind == "text"),
    )
    new_forge.rng = random

    print("== 自动复读 +1 ==")
    sender.events.clear()
    await feed("这是一条复读测试消息", msg_id="r1")
    expect("第一条不复读", sender.events == [])
    await feed("这是一条复读测试消息", msg_id="r2")
    expect("连发两次复读原话",
           sender.events == [("text", "这是一条复读测试消息")])
    sender.events.clear()
    await feed("换一句普通消息", msg_id="r3")
    expect("不同消息不复读", sender.events == [])
    sender.events.clear()
    await feed("什么", msg_id="r4")
    await feed("什么", msg_id="r5")
    expect("命令命中的消息不复读",
           [text for kind, text in sender.events] == ["不不不", "不不不"])
    sender.events.clear()
    await feed("这是一条复读测试消息", is_bot=True, msg_id="r6")
    expect("机器人自己的消息不复读", sender.events == [])

    print("== CS2 赛事 ==")
    live_ts = str(int(datetime.datetime(2026, 10, 22, 19, 0).timestamp()))
    next_ts = str(int(datetime.datetime(2026, 10, 24, 15, 0).timestamp()))
    done_ts = str(int(datetime.datetime(2026, 10, 21, 23, 5).timestamp()))
    parsed = parse_matches({"success": True, "data": {"matches": [
        {
            "mc_info": {"plan_ts": live_ts, "format": "3", "round_name": "决赛",
                        "t1_info": {"disp_name": "BIG"},
                        "t2_info": {"disp_name": "Mongolz"}},
            "state": {"status": "1", "t1_score": "1", "t2_score": "1"},
            "tt_info": {"disp_name": "1win Private Club 第2季",
                        "grade_label": "A级赛事"},
        },
        {
            "mc_info": {"plan_ts": next_ts, "format": "3", "round_name": "第一轮",
                        "t1_info": {"disp_name": "FUT"},
                        "t2_info": {"disp_name": "TYLOO"}},
            "state": {"status": "0"},
            "tt_info": {"disp_name": "PGL 布加勒斯特大师赛 2026",
                        "grade_label": "S级赛事"},
        },
        {
            "mc_info": {"plan_ts": next_ts, "format": "3", "round_name": "待定",
                        "t1_info": {"disp_name": "TBD"},
                        "t2_info": {"disp_name": "TBD"}},
            "state": {"status": "0"},
            "tt_info": {"disp_name": "PGL 布加勒斯特大师赛 2026",
                        "grade_label": "S级赛事"},
        },
    ]}})
    expect("解析赛程", len(parsed) == 3)
    expect("进行中状态", parsed[0].status == "live")
    expect("BO 格式", parsed[1].best_of == "BO3")

    parsed_events = parse_events({"success": True, "data": {"items": [
        {"basic_info": {
            "disp_name": "PGL 布加勒斯特大师赛 2026", "grade_label": "S级赛事",
            "status": "upcoming", "start_time": "2026-10-24 15:00:00",
            "end_time": "2026-11-01 23:00:00",
            "city_name": "布加勒斯特，罗马尼亚", "bonus": "$1,250,000",
        }},
        {"basic_info": {
            "disp_name": "某个 B 级小比赛", "grade_label": "B级赛事",
            "status": "upcoming", "start_time": "2026-10-24 15:00:00",
            "end_time": "2026-10-25 23:00:00", "city_name": "线上", "bonus": "$1,000",
        }},
        {"basic_info": {
            "disp_name": "已经完赛的 A 级赛", "grade_label": "A级赛事",
            "status": "past", "start_time": "2026-10-10 15:00:00",
            "end_time": "2026-10-11 23:00:00", "city_name": "线上", "bonus": "$9,999",
        }},
    ]}})
    expect("赛事只留 S/A 级且未结束",
           len(parsed_events) == 1 and parsed_events[0].grade == "S级")

    brief = brief_text(parsed, parsed_events, now=datetime.datetime(2026, 10, 22, 22, 0))
    expect("赛事文案有进行中",
           "【进行中 1 场】" in brief and "BIG 1:1 Mongolz" in brief)
    expect("赛事文案跳过 TBD 占位", "TBD vs TBD" not in brief)
    expect("赛事文案有赛程", "FUT vs TYLOO" in brief and "BO3" in brief)
    expect("赛事文案有奖池", "奖池 $1,250,000" in brief)

    results = results_text(parse_matches({"success": True, "data": {"matches": [
        {
            "mc_info": {"plan_ts": done_ts, "format": "3", "round_name": "决赛",
                        "t1_info": {"disp_name": "BIG"},
                        "t2_info": {"disp_name": "PARIVISION"}},
            "state": {"status": "2", "t1_score": "0", "t2_score": "2"},
            "tt_info": {"disp_name": "1win Private Club 第2季",
                        "grade_label": "A级赛事"},
        },
    ]}}), now=datetime.datetime(2026, 10, 22, 22, 0))
    expect("赛果文案", "BIG 0:2 PARIVISION" in results and "【10-21】" in results)

    try:
        CS._checked({"success": False, "message": "接口炸了"})
        raised = False
    except RuntimeError as error:
        raised = "接口炸了" in str(error)
    expect("接口失败会抛错", raised)

    def half_broken_fetch(method, url, payload=None, headers=None, timeout=0):
        if "session_list" in url:
            raise RuntimeError("模拟赛程挂了")
        return {"success": True, "data": {"items": [
            {"basic_info": {
                "disp_name": "PGL 布加勒斯特大师赛 2026", "grade_label": "S级赛事",
                "status": "upcoming", "start_time": "2026-10-24 15:00:00",
                "end_time": "2026-11-01 23:00:00",
                "city_name": "布加勒斯特，罗马尼亚", "bonus": "$1,250,000",
            }},
        ]}}

    partial = await CS(fetch=half_broken_fetch).matches_report()
    expect("赛程挂了赛事还能出",
           "没拉到" in partial and "PGL 布加勒斯特大师赛" in partial)

    def dead_fetch(method, url, payload=None, headers=None, timeout=0):
        raise RuntimeError("全挂了")

    try:
        await CS(fetch=dead_fetch).matches_report()
        raised = False
    except RuntimeError:
        raised = True
    expect("两边都挂会抛错", raised)

    class FakeCS:
        def __init__(self) -> None:
            self.live = CSMatch(
                start=datetime.datetime(2026, 10, 22, 19, 0), status="live",
                grade="A级", tournament="测试杯", round_name="决赛",
                team1="BIG", team2="Mongolz", score1="1", score2="1",
                best_of="BO3",
            )
            self.done = CSMatch(
                start=datetime.datetime(2026, 10, 21, 23, 5), status="finished",
                grade="A级", tournament="测试杯", round_name="决赛",
                team1="BIG", team2="PARIVISION", score1="0", score2="2",
                best_of="BO3",
            )
            self.event = CSEvent(
                name="测试大师赛", grade="S级", status="upcoming",
                start_date="10-24", end_date="11-01", city="北京",
                prize="$100,000",
            )

        async def matches_data(self):
            return [self.live], [self.event], []

        async def results_data(self):
            return [self.done]

    fake_cs = FakeCS()
    real_cs = handler.cs
    handler.cs = fake_cs

    if cs_card is not None:
        sender.events.clear()
        await feed("cs赛事", msg_id="cs-img-1")
        expect("cs赛事命令出图", any(kind == "image" for kind, _ in sender.events))
        sender.events.clear()
        await feed("赛果", msg_id="cs-img-2")
        expect("赛果命令出图", any(kind == "image" for kind, _ in sender.events))

    # 没装 Pillow（或渲染失败）时必须退回文字；顺便把命令的各种写法都走一遍
    from . import handler as handler_module

    original_card = handler_module.cs_card
    handler_module.cs_card = None
    try:
        for command_text in (
            "cs赛事", "CS赛事", "/cs赛事", "cs赛事 今天",
            "赛事", "赛果", "cs赛果",
        ):
            sender.events.clear()
            await feed(command_text, msg_id=f"cs-{command_text}")
            expect(
                f"「{command_text}」命令能回",
                any(kind == "text" and "CS2" in text for kind, text in sender.events),
            )
    finally:
        handler_module.cs_card = original_card
    handler.cs = real_cs

    print("== 语音 ==")
    # 命令解析：必须带分隔符。全量消息模式下，群里随口一句「说得好」不该被当成命令。
    expect("「语音：你好呀」解析出内容", tts_payload("语音：你好呀") == "你好呀")
    expect("「语音 你好」也认（空格）", tts_payload("语音 你好") == "你好")
    expect("「/语音:你好」带斜杠也认", tts_payload("/语音:你好") == "你好")
    expect("「说 你好」是短写法", tts_payload("说 你好") == "你好")
    expect("「说话 你好」认", tts_payload("说话 你好") == "你好")
    expect("「说得好」不算命令", tts_payload("说得好") is None)
    expect("只写「语音」返回空（给用法）", tts_payload("语音") == "")
    expect("「保存吊图 测试」不会被当语音", tts_payload("保存吊图 测试") is None)
    expect("「发语音 xxx」不再是命令", tts_payload("发语音 xxx") is None)
    cleaned = clean_for_tts("**看** <qqbot-at-user id=\"1\" /> https://b23.tv/x 喵~\n第二行")
    expect("洗掉 markdown / @ 标记 / 链接",
           "**" not in cleaned and "http" not in cleaned
           and "<qqbot" not in cleaned and "喵" in cleaned)

    # 引擎顺序：自训的 GPT-SoVITS 优先，挂了自动退 edge / sapi
    from . import voice as voice_module

    expect("auto 顺序是 gsv → edge → sapi", engine_order() == ["gsv", "edge", "sapi"])
    expect("指定 edge 就只用 edge", engine_order("edge") == ["edge"])
    expect("gsv 可用性跟着配置走",
           gsv_available() == (GSV_ENABLED and Path(GSV_DIR, "api_v2.py").is_file()))
    if gsv_available():
        expect("describe 里写了 GPT-SoVITS", "GPT-SoVITS" in describe())

    # 群消息换嗓子：解析 / 列表 / 切换 / 持久化。状态文件指到临时目录，别动真的。
    expect("「语音模型」是看列表", voice_model_payload("语音模型") == ("list", ""))
    expect("「语音模型列表」也认",
           voice_model_payload("语音模型列表") == ("list", ""))
    expect("「语音模型 铃兰」是切换",
           voice_model_payload("语音模型 铃兰") == ("switch", "铃兰"))
    expect("「换语音 能天使」也认",
           voice_model_payload("换语音 能天使") == ("switch", "能天使"))
    expect("「换语音模型 铃兰」不被「换语音」截断",
           voice_model_payload("换语音模型 铃兰") == ("switch", "铃兰"))
    expect("「语音：你好」不算换嗓子", voice_model_payload("语音：你好") is None)
    expect("「说 你好」不算换嗓子", voice_model_payload("说 你好") is None)

    original_state = voice_module.GSV_MODEL_STATE
    voice_module.GSV_MODEL_STATE = str(temporary / "voice_model.json")
    voice_module._MODEL_CACHE = None
    try:
        models = scan_models()
        expect("音色目录扫得到角色", bool(models))
        if models:
            before = current_model().name
            expect("当前音色在扫描结果里", before in [m.name for m in models])
            other = next((m for m in models if m.name != before), None)
            if other is not None:
                switched = switch_model(other.name)
                expect("切换后当前音色变了",
                       current_model().name == switched.name)
                expect("切换写进了状态文件",
                       (temporary / "voice_model.json").is_file())
                voice_module._MODEL_CACHE = None
                expect("重读状态文件还是新音色",
                       current_model().name == switched.name)
                expect("重复切同一个不报错",
                       switch_model(switched.name).name == switched.name)
                expect("换不存在的角色会报错",
                       _raises(lambda: switch_model("不存在的角色"), VoiceError))
                expect("列表文案说清了当前音色",
                       "现在用的是" in models_text())
    finally:
        voice_module.GSV_MODEL_STATE = original_state
        voice_module._MODEL_CACHE = None

    visited: list[str] = []

    async def fake_gsv(text, directory):
        visited.append("gsv")
        raise VoiceError("假装挂了")

    async def fake_edge(text, directory):
        visited.append("edge")
        out = temporary / "fallback.mp3"
        out.write_bytes(b"ID3" + b"\x00" * 2048)
        return out

    originals = (
        voice_module._synth_gsv, voice_module._synth_edge, voice_module.engine_available,
    )
    voice_module._synth_gsv = fake_gsv
    voice_module._synth_edge = fake_edge
    voice_module.engine_available = lambda name: True
    try:
        fallback_path = await synthesize("你好呀")
        expect("gsv 失败自动退到 edge",
               visited == ["gsv", "edge"] and fallback_path.name == "fallback.mp3")
        fallback_path.unlink(missing_ok=True)
    finally:
        (voice_module._synth_gsv, voice_module._synth_edge,
         voice_module.engine_available) = originals

    # 现场合成：自检不联网、也不该真去开 PowerShell，把 synthesize 换成假的
    from . import handler as handler_module

    synthesised: list[str] = []

    async def fake_synthesize(text, **kwargs):
        synthesised.append(text)
        out = temporary / "tts.wav"
        out.write_bytes(b"RIFF" + b"\x00" * 2048)
        return out

    original_synth = handler_module.synthesize
    handler_module.synthesize = fake_synthesize
    try:
        sender.events.clear()
        await feed("语音：你好呀", msg_id="voice-1")
        expect("「语音：你好呀」发语音条", sender.events == [("voice", "tts.wav")])
        expect("念的正是冒号后面那句", synthesised == ["你好呀"])

        sender.events.clear()
        await feed("语音", msg_id="voice-2")
        expect("只写「语音」提示用法",
               any(kind == "text" and "语音：你好呀" in text for kind, text in sender.events))

        sender.events.clear()
        await feed("说得好", msg_id="voice-3")
        expect("「说得好」不合成语音", sender.events == [])

        sender.events.clear()
        await feed("发语音 xxx", msg_id="voice-4")
        expect("「发语音」不再有任何反应", sender.events == [])

        # 换嗓子：群消息 → 列表 / 换 / 冷却。状态文件指临时目录。
        original_state2 = voice_module.GSV_MODEL_STATE
        voice_module.GSV_MODEL_STATE = str(temporary / "handler_voice_model.json")
        voice_module._MODEL_CACHE = None
        handler.last_voice_switch = 0.0
        try:
            sender.events.clear()
            await feed("语音模型", msg_id="model-1")
            expect("「语音模型」回列表",
                   any(kind == "text" and "能换的" in text
                       for kind, text in sender.events))

            sender.events.clear()
            await feed("语音模型 不存在的角色", msg_id="model-2")
            expect("换不存在的角色会明说",
                   any(kind == "text" and "没有" in text
                       for kind, text in sender.events))

            sender.events.clear()
            await feed("语音模型 能天使", msg_id="model-3")
            expect("换嗓子成功并回复名字",
                   any(kind == "text" and "能天使" in text
                       for kind, text in sender.events))
            expect("换嗓子写了状态文件",
                   (temporary / "handler_voice_model.json").is_file())

            sender.events.clear()
            await feed("语音模型 铃兰", msg_id="model-4")
            expect("60 秒内再换被冷却拦住",
                   any(kind == "text" and "秒后再来" in text
                       for kind, text in sender.events))
        finally:
            voice_module.GSV_MODEL_STATE = original_state2
            voice_module._MODEL_CACHE = None
            handler.last_voice_switch = 0.0

        # 长文本：按标点切成几条连着发，不硬念成一条几分钟的语音
        long_text = (
            "那是科隆Major赛场，一场足以载入CS史册的巅峰加冕。场馆万众屏息，"
            "喧嚣与沉寂反复更迭，每一次枪声、每一回残局，都是追梦路上最滚烫的注脚。"
            "十余载浮沉逐梦，无数次决赛折戟、无数轮遗憾离场，命运无数次将希望与重担，"
            "压在孤身前行的NiKo肩上。"
        ) * 2
        pieces = split_for_voice(long_text)
        expect("短句不拆段", split_for_voice("你好呀") == ["你好呀"])
        expect("空文本不产段", split_for_voice("   ") == [])
        expect(f"长文拆成多段（{len(long_text)} 字 → {len(pieces)} 段）", len(pieces) > 1)
        expect(f"每段不超过 {VOICE_CHUNK_CHARS} 字",
               all(len(piece) <= VOICE_CHUNK_CHARS for piece in pieces))
        expect("都在标点处断开，不拦腰砍",
               all(piece[-1] in "。！？!?，,、：:" for piece in pieces[:-1]))
        expect("内容没丢",
               sum(len(piece) for piece in pieces) >= len(long_text) - 2 * len(pieces))

        sender.events.clear()
        await feed("语音：" + long_text, msg_id="voice-6")
        voices = [name for kind, name in sender.events if kind == "voice"]
        expect(f"长文本连发 {len(pieces)} 条语音", len(voices) == len(pieces))

        sender.events.clear()
        await feed("语音：" + "啊" * (VOICE_MAX_CHARS + 1), msg_id="voice-7")
        expect("超过总上限时只回文字、不发语音",
               all(kind == "text" for kind, _ in sender.events)
               and any(str(VOICE_MAX_CHARS) in text for kind, text in sender.events))

        handler_module.VOICE_ENABLED = False
        sender.events.clear()
        await feed("语音：你好呀", msg_id="voice-5")
        expect("关掉 QQCHATBOT_VOICE 后不响应", sender.events == [])
    finally:
        handler_module.synthesize = original_synth
        handler_module.VOICE_ENABLED = True

    print("== 弗一把 ==")

    # ---- 题库 ----
    expect("题库自检全过", check_data() == [])
    expect("题库至少 700 个（1.20.2 截止，含生物）", len(MC_ITEMS) >= 700)
    expect("物品名不重复",
           len({item.name for item in MC_ITEMS}) == len(MC_ITEMS))
    expect("每件物品六维齐全、都有介绍",
           all(item.version and item.type and item.tags and item.world
               and item.note for item in MC_ITEMS))
    expect("标签都是 1~4 个的细分类",
           all(1 <= len(item.tags) <= 4 for item in MC_ITEMS))
    expect("版本档位从小到大排好",
           all(version_newer(before, after) == -1 for before, after
               in zip(VERSION_ORDER, VERSION_ORDER[1:])))
    expect("1.20.2 之后的东西不收",
           VERSION_ORDER[-1] == "1.20.2"
           and all(find_item(name) is None for name in
                   ("重锤", "风弹", "铜灯", "试炼钥匙")))
    expect("1.20.2 / 1.20 的新东西都在",
           find_item("锻造模板") is not None
           and find_item("饰纹陶罐") is not None
           and find_item("刷子") is not None
           and find_item("悬挂式樱花木告示牌") is not None)
    expect("木质变体按官方名字收全",
           find_item("云杉木楼梯").name == "云杉木楼梯"
           and find_item("深色橡木台阶").name == "深色橡木台阶"
           and find_item("诡异木门").name == "诡异木门"
           and find_item("橡木船").name == "橡木船")
    expect("石头变体按官方名字收全",
           all(find_item(name).name == name for name in
               ("切制砂岩", "切制红砂岩", "雕纹石砖", "磨制安山岩",
                "深板岩瓦", "石英楼梯", "平滑石英台阶", "石化橡木台阶")))
    mobs = [item for item in MC_ITEMS if item.type == "生物"]
    expect("生物不少于 70 种", len(mobs) >= 70)
    expect("生物用行为标签",
           find_item("苦力怕").type == "生物"
           and "敌对" in find_item("苦力怕").tags
           and "被动" in find_item("绵羊").tags
           and "亡灵" in find_item("僵尸").tags)
    expect("生物旧名字也认",
           find_item("羊").name == "绵羊"
           and find_item("爬行者").name == "苦力怕"
           and find_item("僵尸猪人").name == "僵尸猪灵")
    expect("Boss 级生物标了稀有",
           "稀有" in find_item("末影龙").tags
           and find_item("末影龙").world == "末地")
    expect("英文 id 也能猜", find_item("diamond_sword").name == "钻石剑")
    expect("别名也能猜", find_item("地狱岩").name == "下界岩")
    expect("空格和标点不影响", find_item(" 钻 石 剑！ ").name == "钻石剑")
    expect("带颜色的猜后缀就算",
           find_item("羊毛").name == "羊毛"
           and find_item("红色羊毛").name == "羊毛"
           and find_item("淡蓝色陶瓦").name == "陶瓦")
    expect("乱七八糟的输入查不到", find_item("这个物品不存在喵") is None)

    # ---- 困难模式题库（到 26.3 为止）----
    expect("困难题库自检全过", check_hard_data() == [])
    expect("题库扩到 800 件以上", len(MC_HARD_ITEMS) >= 800)
    expect("困难题库把简单题库整个包进去",
           all(any(a is b for b in MC_HARD_ITEMS) for a in MC_ITEMS))
    expect("1.21 的新东西都在困难题库里",
           all(find_hard_item(name) is not None for name in
               ("重锤", "风弹", "铜灯", "试炼钥匙", "犰狳", "沼骸")))
    expect("1.20.5 到 26.3 每个版本都有新内容",
           all(any(item.version == version for item in MC_HARD_ITEMS)
               for version in ("1.20.5", "1.21", "1.21.2", "1.21.4",
                               "1.21.5", "1.21.6", "1.21.9", "1.21.11",
                               "26.1", "26.2", "26.3")))
    expect("困难档位接在简单档位后面",
           VERSION_ORDER_HARD[:len(VERSION_ORDER)] == VERSION_ORDER
           and len(VERSION_ORDER_HARD) > len(VERSION_ORDER))
    expect("新版本比 1.20.2 新",
           version_newer("1.21", "1.20.2", VERSION_ORDER_HARD) == 1
           and version_newer("1.21.11", "1.21.4", VERSION_ORDER_HARD) == 1
           and version_newer("1.20.5", "1.20.2", VERSION_ORDER_HARD) == 1)
    expect("困难模式查得到新生物",
           find_hard_item("焦骸").type == "生物"
           and find_hard_item("小恶魂").name == "小恶魂"
           and find_hard_item("嘎枝").world == "主世界")
    expect("新物品的别名也认",
           find_hard_item("parched").name == "焦骸"
           and find_hard_item("红色收纳袋").name == "收纳袋"
           and find_hard_item("钻石矛").name == "矛")
    expect("同种类只留一条：七种矛合成「矛」",
           find_hard_item("木矛").name == "矛"
           and find_hard_item("下界合金矛").name == "矛"
           and sum(1 for item in MC_HARD_ITEMS
                   if item.name.endswith("矛")) == 1)
    expect("动物变种并回同一只动物",
           find_hard_item("寒带猪").name == "猪"
           and find_hard_item("热带牛").name == "牛"
           and find_hard_item("寒带鸡").name == "鸡"
           and not any(item.name in ("寒带猪", "热带猪", "寒带牛",
                                     "热带牛", "寒带鸡", "热带鸡")
                       for item in MC_HARD_ITEMS))
    expect("鸡蛋变种并回「蛋」",
           find_hard_item("鸡蛋").name == "蛋"
           and find_hard_item("蓝色鸡蛋").name == "蛋"
           and find_hard_item("棕色鸡蛋").name == "蛋")
    family_suffix = ("楼梯", "台阶", "告示牌", "栅栏", "栅栏门", "墙",
                     "活板门", "按钮", "压力板", "门", "船", "筏")
    expect("楼梯 / 台阶 / 告示牌 / 栅栏 / 墙 / 门 / 按钮 / 船这些族系权重是 0.3",
           find_item("橡木楼梯").weight == 0.3
           and find_item("石头台阶").weight == 0.3
           and find_item("橡木栅栏门").weight == 0.3
           and find_item("圆石墙").weight == 0.3
           and find_item("橡木告示牌").weight == 0.3
           and find_item("橡木门").weight == 0.3
           and find_item("橡木活板门").weight == 0.3
           and find_item("橡木按钮").weight == 0.3
           and find_item("橡木压力板").weight == 0.3
           and find_item("橡木船").weight == 0.3
           and find_item("竹筏").weight == 0.3
           and all(item.weight == 0.3 for item in MC_HARD_ITEMS
                   if item.name.endswith(family_suffix)))
    expect("族系之外还是 1（没有误伤别的题）",
           all(item.weight == 1 for item in MC_ITEMS
               if not item.name.endswith(family_suffix))
           and all(item.weight == 1 for item in MC_HARD_ITEMS
                   if not item.name.endswith(family_suffix))
           and find_item("钻石剑").weight == 1)
    mc_light = MC_Item("轻题", "远古", "方块", ("地形",), "无", note="x")
    mc_heavy = MC_Item("重题", "远古", "方块", ("地形",), "无", note="x",
                       weight=9)
    weight_rng = random.Random(2026)
    draws = [weighted_pick([mc_light, mc_heavy], weight_rng).name
             for _ in range(2000)]
    expect("权重大的题目更容易被抽到",
           draws.count("重题") > draws.count("轻题") * 5)
    mc_light2 = MC_Item("另一道轻题", "远古", "方块", ("地形",), "无", note="x")
    even_draws = {weighted_pick([mc_light, mc_light2], weight_rng).name
                  for _ in range(200)}
    expect("权重一样时两道题都能抽到（均匀）",
           even_draws == {"轻题", "另一道轻题"})

    class _RngSpy:
        def __init__(self):
            self.calls = []

        def choice(self, items):
            self.calls.append("choice")
            return items[0]

        def choices(self, items, weights, k):
            self.calls.append("choices")
            return [items[0]]

    spy = _RngSpy()
    weighted_pick([mc_light, mc_light2], spy)
    expect("权重全等也走加权抽（不再走 choice）", spy.calls == ["choices"])
    try:
        mc_load_items(Path("bad.json"), MC_COLORS, {"items": [{
            "name": "测试物品", "version": "远古", "type": "方块",
            "tags": ["地形"], "world": "无", "note": "x", "weight": 0}]})
        bad_weight_ok = False
    except RuntimeError as error:
        bad_weight_ok = "weight" in str(error)
    expect("权值写 0 或负数会当场报错", bad_weight_ok)
    expect("一物一条：同名的物品不会出现两次",
           len({item.name for item in MC_HARD_ITEMS}) == len(MC_HARD_ITEMS))
    expect("切制铜楼梯 / 台阶也收进来了",
           find_hard_item("切制铜楼梯").version == "1.17"
           and find_hard_item("切制铜台阶").version == "1.17")
    expect("涂蜡 / 氧化 / 斑驳的铜方块都认",
           find_hard_item("涂蜡的切制铜台阶").name == "切制铜台阶"
           and find_hard_item("斑驳的切制铜台阶").name == "切制铜台阶"
           and find_hard_item("涂蜡的氧化切制铜台阶").name == "切制铜台阶"
           and find_hard_item("斑驳的铜块").name == "铜块"
           and find_hard_item("涂蜡的斑驳铜门").name == "铜门"
           and find_hard_item("涂蜡的氧化铜箱子").name == "铜箱子")
    expect("铜变种不单列条目",
           not any(item.name.startswith(("涂蜡", "斑驳", "锈蚀", "氧化"))
                   for item in MC_HARD_ITEMS))
    expect("老物品的新写法挂在老条目上",
           find_hard_item("温带猪").name == "猪"
           and find_hard_item("涡流纹样陶片").name == "纹样陶片")
    expect("简单题库没被新内容污染",
           find_item("重锤") is None and find_item("焦骸") is None)
    expect("题库是 JSON 文件，不是写死在代码里",
           MC_BANK_FILE.endswith(".json")
           and config_file(MC_BANK_FILE).exists()
           and config_file("mc_guess_hard.json").exists())
    try:
        mc_load_items(Path("bad.json"), MC_COLORS, {"items": [{
            "name": "测试物品", "version": "远古", "type": "方块",
            "tags": ["地形"], "world": "无", "note": "x", "tagsx": 1}]})
        bad_json_ok = False
    except RuntimeError as error:
        bad_json_ok = "认不出的字段" in str(error)
    expect("JSON 写错字段名会当场报错", bad_json_ok)
    expect("之前漏收的老东西也补进来了",
           all(find_hard_item(name) is not None for name in
               ("去皮原木", "珊瑚", "幽匿感测体", "木棍", "TNT", "海绵",
                "唱片机", "树苗", "小麦", "运输船")))
    expect("按需求去掉的条目确实不在",
           all(find_hard_item(name) is None for name in
               ("珊瑚扇", "管珊瑚扇", "鱼桶", "鳕鱼桶", "靶标",
                "绯红菌索", "诡异菌索", "缠怨藤", "垂泪藤"))
           and find_hard_item("珊瑚") is not None)
    expect("补漏的系列按一个名字收",
           find_hard_item("去皮樱花原木").name == "去皮原木"
           and find_hard_item("管珊瑚").name == "珊瑚"
           and find_hard_item("橡树树苗").name == "树苗"
           and find_hard_item("小麦种子").name == "种子"
           and find_hard_item("红色蘑菇").name == "蘑菇")

    # ---- 六维比对 ----
    mc_target = find_item("下界合金剑")
    nails = MCGuess._cells(find_item("钻石剑"), mc_target)
    expect("名称重合的字要标出来",
           nails[0].startswith("🟨") and "重合 1 字" in nails[0])
    expect("远古猜 1.16 亮 ⬆️", nails[1].startswith("⬆️"))
    expect("同类型亮绿", nails[2].startswith("🟩") and "武器" in nails[2])
    expect("标签有重合亮 🟨 并列出重合的",
           nails[3].startswith("🟨") and "战斗" in nails[3])
    expect("标签一个都不沾边亮 ⬜",
           MCGuess._cells(find_item("苹果"), mc_target)[3].startswith("⬜"))
    expect("答案更长亮 ⬆️ 并写差几个字",
           nails[4].startswith("⬆️") and "多 2 字" in nails[4])
    expect("生成世界相同亮绿", nails[5].startswith("🟩"))
    expect("工具 / 武器算沾边",
           MCGuess._cells(find_item("铁镐"), mc_target)[2].startswith("🟨"))
    expect("方块和装备不沾边",
           MCGuess._cells(find_item("圆石"), mc_target)[2].startswith("⬜"))
    expect("答案更早的版本亮 ⬇️",
           MCGuess._cells(find_item("下界合金剑"), find_item("铁剑"))[1]
           .startswith("⬇️"))
    expect("版本反馈带更新主题名",
           MCGuess._cells(find_item("下界合金锭"), find_item("下界合金剑"))[1]
           == "🟩 1.16 下界更新"
           and version_label("1.13") == "1.13 水域更新"
           and version_label("26.1") == "26.1 小鬼当家"
           and version_label("远古") == "远古")

    # ---- 对局：难度面板 / 猜错 / 去重 / 猜中结算 ----
    handler.mc_guess.clear()
    handler.mc_guess._pick = lambda *args, **kwargs: find_item("下界合金剑")

    async def mc(content, user="MC1", name="曼波", group="G-MC"):
        sender.events.clear()
        sender.panels.clear()
        await handler.handle(Incoming(
            group_openid=group, user_openid=user, username=name,
            content=content, msg_id="mc",
        ))
        return sender.events

    def mc_text() -> str:
        return sender.events[-1][1] if sender.events else ""

    async def mc_start(user="MC1", name="曼波", group="G-MC", mode="简单"):
        """发「弗一把」→ 点难度按钮，两步走完才算开局。"""
        await mc("弗一把", user=user, name=name, group=group)
        await mc(f"弗一把 {mode}模式", user=user, name=name, group=group)

    await mc("弗一把")
    expect("「弗一把」先给难度面板",
           "简单模式" in mc_text() and "困难模式" in mc_text()
           and "26.3" in mc_text())
    panel = sender.panels[-1] if sender.panels else []
    labels = [button["render_data"]["label"]
              for row in panel for button in row["buttons"]]
    data = [button["action"]["data"] for row in panel for button in row["buttons"]]
    expect("面板就两个按钮：简单 / 困难",
           labels == ["简单模式", "困难模式"] and data == ["弗一把 简单模式",
                                                          "弗一把 困难模式"])
    expect("面板按钮只签给唤出面板的人",
           panel and panel[0]["buttons"][0]["action"]["permission"]["type"] == 0)
    expect("选难度之前不开局", handler.mc_guess.active("G-MC") is None)

    await mc("弗一把 简单模式")
    expect("点了简单模式才开局",
           "简单模式" in mc_text() and "20 轮" in mc_text()
           and handler.mc_guess.active("G-MC") is not None)
    expect("开局后这局是活的",
           handler.mc_guess.active("G-MC") is not None
           and handler.mc_guess.active("G-MC").mode == "简单")
    await mc("弗一把")
    expect("没打完再开会被拦下", "还没打完" in mc_text())
    await mc("弗一把 困难模式")
    expect("没打完不能换难度", "已经开着" in mc_text())

    await mc("弗一把 状态")
    expect("状态报出第 0/20 轮", "第 0/20 轮" in mc_text())

    await mc("钻石剑", user="MC2", name="庞月")
    expect("猜错也回六维反馈",
           all(dim in mc_text() for dim in
               ("名称", "加入版本", "类型", "标签", "字数", "生成世界")))
    expect("猜错报剩余次数", "还剩 19 次" in mc_text())

    await mc("宠物", user="MC4", name="路人")
    expect("玩的时候别的命令照旧管用", bool(sender.panels))

    await mc("猜 钻石剑", user="MC3", name="群友")
    expect("同一件反复猜不烧轮数",
           "已经猜过" in mc_text()
           and handler.mc_guess.active("G-MC").rounds == 1)

    await mc("猜 下界合金套", user="MC3", name="群友")
    expect("题库里没有的也不烧轮数",
           "题库里没有" in mc_text()
           and handler.mc_guess.active("G-MC").rounds == 1)

    await mc("今天天气不错", user="MC3", name="群友")
    expect("局内普通闲聊不会被当成猜词", sender.events == [])

    await mc("下界合金剑", user="MC3", name="群友")
    win_text = mc_text()
    expect("猜中报答案和介绍",
           "猜中" in win_text and "下界合金剑" in win_text
           and "下界合金制的剑" in win_text)
    expect("猜中不再发宠物经验", "宠物经验" not in win_text and "经验 +" not in win_text)
    expect("列出参与过的人",
           "本局参与者" in win_text and "庞月" in win_text and "群友" in win_text)
    expect("猜中后局面关闭", handler.mc_guess.active("G-MC") is None)

    # ---- 二十轮用完：大肥鱼难过 ----
    handler.mc_guess._pick = lambda *args, **kwargs: find_item("蜂蜜块")
    await mc_start(user="MC9", name="阿曼")
    wrong_guesses = (
        "铁剑", "木剑", "石剑", "金剑", "钻石剑", "弓", "弩", "盾牌",
        "剪刀", "鞍", "皮革", "苹果", "面包", "桶", "时钟", "地图",
        "火把", "梯子", "箱子", "熔炉",
    )
    for wrong in wrong_guesses:
        await mc(f"猜 {wrong}", user="MC9", name="阿曼")
    loss_text = mc_text()
    expect("第二十轮猜错说大肥鱼难过",
           "这么简单都没猜到，大肥鱼很难过(；′⌒`)" in loss_text)
    expect("失败局揭晓答案", "蜂蜜块" in loss_text)
    expect("失败不结算任何奖励", "宠物经验" not in loss_text)
    expect("失败后局面也关闭", handler.mc_guess.active("G-MC") is None)

    # ---- 认输 / 超时 ----
    await mc_start(user="MC6", name="阿曼")
    await mc("弗一把 结束", user="MC6", name="阿曼")
    expect("认输会揭晓答案",
           "答案是" in mc_text() and "蜂蜜块" in mc_text())

    fixed = [10_000.0]
    handler.mc_guess.now = lambda: fixed[0]
    await mc_start(user="MC7", name="阿曼")
    fixed[0] += SESSION_TTL + 1
    await mc_start(user="MC7", name="阿曼")
    expect("十分钟没动就散场、可以直接开新局",
           handler.mc_guess.active("G-MC").rounds == 0
           and "Minecraft 物品 & 生物篇" in mc_text())

    handler.mc_guess.now = time.time
    handler.mc_guess.clear()

    # ---- 带颜色的题：只猜后缀也算中 ----
    handler.mc_guess._pick = lambda *args, **kwargs: find_item("羊毛")
    await mc_start(user="MC11", name="阿曼")
    expect("开局不再白送类型提示", "类型是「" not in mc_text())
    await mc("猜 红色羊毛", user="MC11", name="阿曼")
    expect("带颜色的题猜「颜色+后缀」直接算中",
           "猜中" in mc_text() and "羊毛" in mc_text())
    handler.mc_guess._pick = lambda *args, **kwargs: find_item("陶瓦")
    await mc_start(user="MC12", name="阿曼")
    await mc("淡蓝色陶瓦", user="MC12", name="阿曼")
    expect("带颜色的题猜光秃秃的后缀也算中",
           "猜中" in mc_text() and "陶瓦" in mc_text())

    # ---- 榜单 / 趣味互动 ----
    handler.mc_guess.clear()
    handler.mc_guess._pick = lambda *args, **kwargs: find_item("钻石剑")
    await mc_start(user="MC20", name="榜一大哥")
    expect("开局界面直接带本群榜单", "本群榜" in mc_text())
    await mc("钻石剑", user="MC20", name="榜一大哥")
    expect("一轮秒杀会吐槽外挂", "这不是外挂？" in mc_text())
    expect("猜中次数记进榜单", "第 1 次猜中" in mc_text())
    board = handler.mc_guess.leaderboard("G-MC")
    expect("榜首就是刚猜中的人", board and board[0]["name"] == "榜一大哥")
    await mc("弗一把 榜单")
    expect("「弗一把 榜单」能看完整榜",
           "本群弗一把榜" in mc_text() and "榜一大哥" in mc_text())

    handler.mc_guess._pick = lambda *args, **kwargs: find_item("苹果")
    await mc_start(user="MC20", name="榜一大哥")
    await mc("苹果", user="MC20", name="榜一大哥")
    expect("同一个人再中一次会累加", "第 2 次猜中" in mc_text())

    fresh = MCGuess(handler.pets, paths.data)
    expect("榜单落盘、重启还在",
           fresh.leaderboard("G-MC")[0]["wins"] >= 2)

    # 冷场提醒：把时钟往后拨，只改提醒计数
    # （后台催更任务是真定时器，自检里先停掉，免得半夜突然说话）
    early_ticker = getattr(handler, "_mc_ticker", None)
    if early_ticker is not None:
        early_ticker.cancel()
    fixed = [20_000.0]
    handler.mc_guess.now = lambda: fixed[0]
    handler.mc_guess._pick = lambda *args, **kwargs: find_item("钻石剑")
    await mc_start(user="MC21", name="阿曼")
    rounds_before = handler.mc_guess.active("G-MC").rounds
    fixed[0] += NUDGE_IDLE + 1
    first_nudge = handler.mc_guess.nudge("G-MC")
    expect("冷场三分钟会催「花都谢了」",
           bool(first_nudge) and "我等的花都谢了💔" in first_nudge)
    expect("催更不占轮数、不改参与者",
           handler.mc_guess.active("G-MC").rounds == rounds_before
           and not handler.mc_guess.active("G-MC").players)
    expect("同一时间不重复催", handler.mc_guess.nudge("G-MC") is None)
    fixed[0] += NUDGE_IDLE + 1
    second_nudge = handler.mc_guess.nudge("G-MC")
    expect("第二次换个说法", bool(second_nudge) and "打哈欠" in second_nudge)
    expect("一局最多催两次", handler.mc_guess.nudge("G-MC") is None)
    await mc("钻石剑", user="MC21", name="阿曼")
    expect("催更之后照样能正常玩", "猜中" in mc_text())
    handler.mc_guess.now = time.time
    handler.mc_guess.clear()
    ticker = getattr(handler, "_mc_ticker", None)
    if ticker is not None:
        ticker.cancel()

    # ---- 困难模式：从扩展题库里抽题 ----
    handler.mc_guess.clear()
    handler.mc_guess._pick = lambda *args, **kwargs: find_hard_item("重锤")
    await mc_start(user="MCH1", name="阿曼", group="G-HARD", mode="困难")
    expect("困难模式开局写明范围和难度",
           "困难模式" in mc_text() and "26.3" in mc_text())
    expect("这一局记着是困难模式",
           handler.mc_guess.active("G-HARD").mode == "困难")
    await mc("猜 下界合金剑", user="MCH2", name="庞月", group="G-HARD")
    expect("困难模式里老物品照样能猜（反馈走扩展档位）",
           "题库里没有" not in mc_text()
           and "还剩 19 次" in mc_text())
    expect("新版本打 ⬆️ 而不是不认识",
           "答案比「1.16 下界更新」新" in mc_text())
    await mc("重锤", user="MCH2", name="庞月", group="G-HARD")
    expect("困难模式猜中新物品算中",
           "猜中" in mc_text() and "重锤" in mc_text())
    expect("困难局结束后不残留", handler.mc_guess.active("G-HARD") is None)

    handler.mc_guess._pick = lambda *args, **kwargs: find_item("下界合金剑")
    await mc_start(user="MCE1", name="阿曼", group="G-EASY")
    await mc("猜 重锤", user="MCE1", name="阿曼", group="G-EASY")
    expect("简单模式还是只认 1.20.2 的题库",
           "题库里没有" in mc_text()
           and handler.mc_guess.active("G-EASY").rounds == 0)
    handler.mc_guess.clear()

    # ---- 第 16 / 18 轮各给一个字 ----
    handler.mc_guess.clear()
    handler.mc_guess._pick = lambda *args, **kwargs: find_item("钻石剑")
    await mc_start(user="MC30", name="阿曼", group="G-HINT")
    early = ("苹果", "面包", "桶", "时钟", "地图", "火把", "梯子", "箱子",
             "熔炉", "皮革", "箭", "铁剑", "木剑", "石剑", "金剑", "剪刀")
    for index, wrong in enumerate(early, 1):
        await mc(f"猜 {wrong}", user="MC30", name="阿曼", group="G-HINT")
        if index == 15:
            expect("前 15 轮不给提示", "小提示" not in mc_text())
        if index == 16:
            expect("第 16 轮给出名字第一个字",
                   "第一个字是「钻」" in mc_text())
    await mc("猜 鞍", user="MC30", name="阿曼", group="G-HINT")   # 第 17 轮
    expect("第 17 轮不重复提示", "小提示" not in mc_text())
    await mc("猜 弓", user="MC30", name="阿曼", group="G-HINT")   # 第 18 轮
    expect("第 18 轮给出名字最后一个字",
           "最后一个字是「剑」" in mc_text())
    expect("提示不额外烧轮数",
           handler.mc_guess.active("G-HINT").rounds == 18)

    class _HintStub:
        def __init__(self, rounds, target):
            self.rounds, self.target = rounds, target

    one_char = find_hard_item("矛")
    expect("一个字的名字不把答案直接说穿",
           "第一个字是「矛」" not in handler.mc_guess._hint(_HintStub(16, one_char))
           and "最后一个字是「矛」" not in handler.mc_guess._hint(_HintStub(18, one_char))
           and "答案就一个字" in handler.mc_guess._hint(_HintStub(16, one_char)))
    expect("第 16 / 18 轮之外都不提示",
           all(handler.mc_guess._hint(_HintStub(rounds, one_char)) == ""
               for rounds in (0, 1, 15, 17, 19, 20)))
    handler.mc_guess.clear()

    await mc("猜 钻石剑", user="MC8", name="阿曼")
    expect("没开局直接猜会给提示", "先发一句" in mc_text())
    await mc("猜猜我是谁", user="MC8", name="阿曼")
    expect("「猜猜我是谁」这种闲聊不接", sender.events == [])

    print("== 恶魔轮盘赌 ==")

    def dr_labels(panel) -> dict:
        return {label: data for row in panel["rows"] for label, data in row}

    def dr_panel_ok(panel) -> bool:
        """平台硬限制：最多 5 行、每行最多 5 个、label 最多 10 字。"""
        rows = (panel or {}).get("rows") or []
        return (
            len(rows) <= 5
            and all(len(row) <= 5 for row in rows)
            and all(len(label) <= 10 for row in rows for label, _ in row)
        )

    def dr_panel(game) -> dict:
        """出一张最新面板（会作废旧面板，和真实点击一致）。"""
        return handler.devil._game_panel(game)

    def dr_click(game, label, user="DR1", name="庞月", group="G-DR") -> dict:
        return handler.devil.handle(dr_labels(dr_panel(game))[label],
                                    group, user, name)

    def dr_reply(result: dict) -> str:
        return ((result or {}).get("panel") or {}).get("text") \
            or (result or {}).get("reply") or ""

    def dr_run(text, user="DR1", name="庞月", group="G-DR", opponents=()) -> dict:
        return handler.devil.handle(text, group, user, name, opponents=opponents)

    def dr_start(group="G-DR", user="DR1", name="庞月", label="单人·道具"):
        menu = dr_run("恶魔轮盘赌", user, name, group)["panel"]
        return dr_run(dr_labels(menu)[label], user, name, group)

    devil = handler.devil
    devil.clear()
    devil.now = time.time
    devil.rng = random.Random(20261123)
    # 入场费走抽卡 / 锻造同一个银币钱包：先给自检用的几号人发点钱
    for user_id in ("DR1", "DA", "DB", "DC", "DD", "DH", "DO"):
        handler.cards.grant_shards(user_id, 5000)

    # ---- 主菜单：榜单就在最上面 ----
    menu = dr_run("恶魔轮盘赌")["panel"]
    expect("主菜单第二行（榜单位）就是本群榜",
           "本群榜" in menu["text"].splitlines()[1])
    expect("主菜单同时给出单人 / 双人 / 规则 / 榜单入口",
           {"单人·道具", "单人·纯赌", "公开挑战", "定向挑战",
            "完整榜单", "玩法规则"} <= set(dr_labels(menu)))
    expect("主菜单面板过平台限制", dr_panel_ok(menu))
    expect("菜单按钮的 data 带上面板 id 和序号",
           sum(1 for data in dr_labels(menu).values()
               if data.startswith("轮盘 ")) == len(dr_labels(menu)))

    # ---- 单人开局 ----
    start = dr_start()
    game = devil.active("G-DR")
    expect("单人开局后这桌是活的", game is not None)
    expect("单人对手是大肥鱼（AI）",
           game.players[1].ai and game.players[1].name == FISH_NAME)
    expect("开局面板写明弹匣和双方电量",
           "弹匣" in start["panel"]["text"] and "❤" in start["panel"]["text"])
    expect("道具模式开局双方都拿到手牌",
           all(player.items for player in game.players))
    expect("对局面板过平台限制", dr_panel_ok(start["panel"]))
    game.players[0].items = ["放大镜", "香烟", "啤酒", "手锯", "手铐",
                             "逆变器", "电话", "药丸"]
    expect("八件手牌也能排进面板（不超过 5 行）",
           dr_panel_ok(dr_panel(game)))

    # ---- 开枪：空包保枪 / 实弹掉电交枪 ----
    game.players[0].items = []
    game.shells = [False, True]
    game.idx = 0
    game.revealed = {}
    turn_before = game.turn
    result = dr_click(game, "朝自己开枪")
    expect("朝自己开空包：不扣电、枪还归你",
           game.players[0].hp == DEVIL_MAX_HP and game.turn == turn_before
           and game.idx == 1)
    expect("空包的结果写在面板上", "空包" in dr_reply(result))

    game.players[1].ai = False          # 先关掉 AI，单独看「交枪」这件事
    game.turn = 0
    game.shells = [True, False]
    game.idx = 0
    game.players[0].hp = DEVIL_MAX_HP
    dr_click(game, "朝自己开枪")
    expect("朝自己开实弹：自己掉 1 点电", game.players[0].hp == DEVIL_MAX_HP - 1)
    expect("朝自己开实弹后交枪", game.turn == 1)

    # ---- 道具 ----
    game.turn = 0
    game.players[1].ai = True
    game.players[0].hp = DEVIL_MAX_HP
    game.players[1].hp = DEVIL_MAX_HP
    game.players[1].cuffed = False
    game.players[0].saw = False

    game.shells = [True, False]
    game.idx = 0
    game.players[0].items = ["手锯"]
    dr_click(game, "手锯")
    expect("手锯用掉后进入锯短状态", game.players[0].saw
           and not game.players[0].items)
    game.players[1].ai = False
    dr_click(game, "朝对方开枪")
    expect("手锯让伤害翻倍（5 → 3）", game.players[1].hp == DEVIL_MAX_HP - 2)
    game.players[1].ai = True

    game.turn = 0
    game.players[1].hp = DEVIL_MAX_HP
    game.players[0].items = ["手铐"]
    game.shells = [True, False]
    game.idx = 0
    dr_click(game, "手铐")
    expect("手铐锁住对方", game.players[1].cuffed)
    game.players[1].ai = False
    dr_click(game, "朝对方开枪")
    expect("被锁住的对方跳过回合，枪回到自己手里",
           game.turn == 0 and not game.players[1].cuffed)
    game.players[1].ai = True

    game.players[0].items = ["啤酒"]
    game.shells = [True, True, False]
    game.idx = 0
    dr_click(game, "啤酒")
    expect("啤酒把当前这发退出来、弹匣前进",
           game.idx == 1 and game.revealed.get(0) is True)

    game.players[0].items = ["逆变器"]
    game.shells = [False, True]
    game.idx = 0
    dr_click(game, "逆变器")
    expect("逆变器把空包翻成实弹", game.shells[0] is True)

    game.players[0].items = ["放大镜"]
    game.shells = [False, True]
    game.idx = 0
    game.revealed = {}
    result = dr_click(game, "放大镜")
    expect("放大镜告诉当前这发是什么",
           game.revealed.get(0) is False and "空包" in dr_reply(result))

    game.players[0].items = ["电话"]
    game.shells = [False, True, True]
    game.idx = 0
    game.revealed = {}
    result = dr_click(game, "电话")
    expect("电话点出弹匣里某一发",
           len(game.revealed) >= 1 and "第" in dr_reply(result))

    game.players[0].items = ["香烟"]
    game.players[0].hp = 1
    dr_click(game, "香烟")
    expect("香烟回 1 点电", game.players[0].hp == 2)
    game.players[0].items = ["香烟"]
    game.players[0].hp = DEVIL_MAX_HP
    dr_click(game, "香烟")
    expect("满电时抽烟不会超过上限", game.players[0].hp == DEVIL_MAX_HP)

    class FixedRandom(random.Random):
        """药丸是 50/50，自检里把 random() 钉死才好断言。"""

        def __init__(self, value: float) -> None:
            super().__init__(1)
            self.value = value

        def random(self) -> float:
            return self.value

    game.players[0].items = ["药丸"]
    game.players[0].hp = 1
    devil.rng = FixedRandom(0.1)
    dr_click(game, "药丸")
    expect("药丸好运时回 2 点电", game.players[0].hp == 3)
    game.players[0].items = ["药丸"]
    game.players[0].hp = DEVIL_MAX_HP
    devil.rng = FixedRandom(0.9)
    dr_click(game, "药丸")
    expect("药丸是坏的时候掉 1 点电", game.players[0].hp == DEVIL_MAX_HP - 1)
    devil.rng = random.Random(20261123)

    game.players[0].items = ["肾上腺素"]
    game.players[1].items = ["香烟"]
    dr_click(game, "肾上腺素")
    expect("肾上腺素把对方的道具抢到自己手里",
           "香烟" in game.players[0].items and not game.players[1].items)

    expect("九件道具的名字都在按钮 10 字限制内",
           all(len(name) <= 10 for name in DEVIL_ITEMS))

    # ---- 换弹：不回血、每轮补 2 件道具、打到见底才结算 ----
    devil.clear()
    dr_start(group="G-DR-RELOAD")
    reload_game = devil.active("G-DR-RELOAD")
    reload_game.players[0].hp = 2
    reload_game.players[1].hp = 3
    reload_game.shells = [False]
    reload_game.idx = 0
    items_before = [len(player.items) for player in reload_game.players]
    dr_click(reload_game, "朝自己开枪", group="G-DR-RELOAD")
    expect("弹匣打空只换新弹，双方血量不回满",
           [player.hp for player in reload_game.players] == [2, 3])
    expect("每轮固定补发 2 件道具",
           [len(player.items) for player in reload_game.players]
           == [count + 2 for count in items_before])
    expect("换弹之后这局还在继续（没人见底就不结算）",
           not reload_game.over and reload_game.round == 2
           and reload_game.idx == 0)
    expect("每人 5 格电量", DEVIL_MAX_HP == 5)

    # ---- 文案：对局面板不贴榜单、大肥鱼的话单独缩成引用 ----
    reload_game.taunt = "哼，你的手在抖吧？"
    text = handler.devil._game_panel(reload_game)["text"]
    expect("对局中不再重复贴对局榜单", "本群榜" not in text)
    expect("标题用一号标题、正文分层", text.startswith("# "))
    expect("大肥鱼的话单独隔开成引用块",
           "\n> 🐟 哼，你的手在抖吧？" in text)
    expect("对局面板正文不超过 10 行", len(text.splitlines()) <= 10)

    # ---- 入场费：扣费 / 赢了按倍率返 / 输了按模式退 ----
    devil.clear()
    poor_menu = dr_run("恶魔轮盘赌", "DQ", "穷鬼", "G-DR-POOR")["panel"]
    poor = devil.handle(dr_labels(poor_menu)["单人·道具"],
                        "G-DR-POOR", "DQ", "穷鬼")
    expect("银币不够开不了局", "银币不够" in dr_reply(poor))
    expect("没钱时不会白开一桌", devil.active("G-DR-POOR") is None)

    devil.clear()
    before = handler.cards.shards_of("DA")
    dr_start(group="G-DR-FEE-WIN", user="DA", name="庞月")
    fee_game = devil.active("G-DR-FEE-WIN")
    expect("开局先扣入场费",
           handler.cards.shards_of("DA") == before - ENTRY_FEE)
    fee_game.players[1].hp = 1
    fee_game.shells = [True]
    fee_game.idx = 0
    fee_won = dr_click(fee_game, "朝对方开枪", user="DA", name="庞月",
                       group="G-DR-FEE-WIN")
    expect("道具模式赢了按 1.4 倍返还入场费",
           handler.cards.shards_of("DA")
           == before - ENTRY_FEE + int(round(ENTRY_FEE * 1.4)))
    expect("结算面板写明入场和返还",
           "入场" in dr_reply(fee_won) and "返" in dr_reply(fee_won))

    devil.clear()
    before = handler.cards.shards_of("DB")
    dr_start(group="G-DR-FEE-LOSE", user="DB", name="阿伟")
    dr_run("恶魔轮盘赌 认输", "DB", "阿伟", "G-DR-FEE-LOSE")
    expect("道具模式输了入场费全赔",
           handler.cards.shards_of("DB") == before - ENTRY_FEE)

    devil.clear()
    before = handler.cards.shards_of("DC")
    dr_start(group="G-DR-FEE-PURE", user="DC", name="路人",
             label="单人·纯赌")
    dr_run("恶魔轮盘赌 认输", "DC", "路人", "G-DR-FEE-PURE")
    expect("纯赌模式输了返还一半入场费",
           handler.cards.shards_of("DC")
           == before - ENTRY_FEE + int(round(ENTRY_FEE * 0.5)))

    # ---- 纯赌模式：没有道具 ----
    devil.clear()
    pure_start = dr_start(group="G-DR-PURE", label="单人·纯赌")
    pure_game = devil.active("G-DR-PURE")
    expect("纯赌模式双方都没有手牌",
           not any(player.items for player in pure_game.players))
    expect("纯赌面板不给道具按钮",
           not any(label in dr_labels(pure_start["panel"])
                   for label in ("放大镜", "香烟", "手锯")))
    blocked = devil.handle(
        devil_panel_data(pure_game.gid, pure_game.seq, ACT_USE, "放大镜"),
        "G-DR-PURE", "DR1", "庞月",
    )
    expect("纯赌模式点道具会被拦下", "纯赌" in dr_reply(blocked))

    # ---- 认输 / 打赢大肥鱼 / 榜单 ----
    devil.clear()
    devil.rng = random.Random(5)
    dr_start(group="G-DR-LOSE")
    lose_game = devil.active("G-DR-LOSE")
    lost = dr_run("恶魔轮盘赌 认输", group="G-DR-LOSE")
    expect("认输会结束这局", lose_game.over
           and devil.active("G-DR-LOSE") is None)
    expect("认输算输给大肥鱼", lose_game.winner == FISH_NAME)
    expect("输了会看到大肥鱼得意的台词",
           any(line in dr_reply(lost)
               for line in ("就这？", "下一局记得", "小鱼干到手", "赢了赢了",
                            "还敢嘴硬", "谢谢款待")))

    devil.clear()
    dr_start(group="G-DR-WIN")
    win_game = devil.active("G-DR-WIN")
    win_game.players[1].hp = 1
    win_game.shells = [True, False]
    win_game.idx = 0
    won = dr_click(win_game, "朝对方开枪", group="G-DR-WIN")
    expect("电趴大肥鱼后它很不甘心",
           any(line in dr_reply(won) for line in DEFEAT_LINES))
    expect("结算面板记下胜场", "1胜0负" in dr_reply(won))
    expect("结算面板过平台限制", dr_panel_ok(won["panel"]))

    fresh_devil = DevilRoulette(paths.data)
    board = fresh_devil.leaderboard("G-DR-WIN")
    expect("榜单落盘、重启还在", bool(board) and board[0]["wins"] >= 1)
    menu = dr_run("恶魔轮盘赌", group="G-DR-WIN")["panel"]
    expect("主菜单里面能直接看到刚打的胜场",
           "1胜" in menu["text"] and "本群榜" in menu["text"])

    rematch = devil.handle(dr_labels(won["panel"])["再来一局"],
                           "G-DR-WIN", "DR1", "庞月")
    expect("再来一局能直接开新的一桌",
           bool(rematch.get("panel")) and devil.active("G-DR-WIN") is not None)

    # ---- 谁血量归零谁输（包括朝自己开枪把自己电死）----
    devil.clear()
    dr_start(group="G-DR-SELFKILL")
    self_game = devil.active("G-DR-SELFKILL")
    self_game.players[0].hp = 1
    self_game.shells = [True]
    self_game.idx = 0
    suicide = dr_click(self_game, "朝自己开枪", group="G-DR-SELFKILL")
    expect("朝自己开枪把自己电死：是自己输，不是自己赢",
           self_game.over and self_game.winner == FISH_NAME)
    expect("自尽按输结算（道具模式入场费全赔）",
           "入场 100 → 返 0" in dr_reply(suicide))

    # ---- 双人对赌：定向挑战 ----
    devil.clear()
    invite = dr_run("恶魔轮盘赌", "DA", "庞月", "G-DR-PVP",
                    opponents=[("DB", "阿伟")])["panel"]
    expect("定向挑战的按钮只签给被 @ 的人", invite["user_ids"] == ["DB"])
    expect("挑战帖写明有效期", str(int(INVITE_TTL)) in invite["text"])
    expect("挑战帖过平台限制", dr_panel_ok(invite))
    third = devil.handle(dr_labels(invite)["接受·道具"],
                         "G-DR-PVP", "DC", "路人")
    expect("别人接不了定向挑战", "阿伟" in dr_reply(third))
    before_duel = (handler.cards.shards_of("DA"), handler.cards.shards_of("DB"))
    started = devil.handle(dr_labels(invite)["接受·纯赌"],
                           "G-DR-PVP", "DB", "阿伟")
    pvp = devil.active("G-DR-PVP")
    expect("被点名的人接受后开局", pvp is not None and not pvp.solo)
    expect("接受的时候自己选模式", pvp.mode == "纯赌")
    expect("发起人先手", pvp.players[0].user == "DA")
    expect("双人局两边各交一份入场费",
           (handler.cards.shards_of("DA"), handler.cards.shards_of("DB"))
           == (before_duel[0] - ENTRY_FEE, before_duel[1] - ENTRY_FEE))
    expect("双人开局面板过平台限制", dr_panel_ok(started["panel"]))

    pvp.players[1].hp = DEVIL_MAX_HP
    pvp.shells = [True, False]
    pvp.idx = 0
    pvp.revealed = {}
    not_yet = devil.handle(dr_labels(started["panel"])["朝自己开枪"],
                           "G-DR-PVP", "DB", "阿伟")
    expect("没轮到自己点按钮会被拦下", "回合" in dr_reply(not_yet))
    devil.handle(dr_labels(started["panel"])["朝对方开枪"],
                 "G-DR-PVP", "DA", "庞月")
    expect("双人局的伤害记在对方身上",
           pvp.players[1].hp == DEVIL_MAX_HP - 1 and pvp.turn == 1)

    # 双人局里自尽：血量归零的人输，对手赢
    devil.clear()
    kill_menu = dr_run("恶魔轮盘赌", "DA", "庞月", "G-DR-PVP2")["panel"]
    kill_open = devil.handle(dr_labels(kill_menu)["公开挑战"],
                             "G-DR-PVP2", "DA", "庞月")
    devil.handle(dr_labels(kill_open["panel"])["接受·纯赌"],
                 "G-DR-PVP2", "DB", "阿伟")
    kill_game = devil.active("G-DR-PVP2")
    kill_game.players[0].hp = 1
    kill_game.shells = [True]
    kill_game.idx = 0
    kill_game.revealed = {}
    kill_result = devil.handle(dr_labels(devil._game_panel(kill_game))["朝自己开枪"],
                               "G-DR-PVP2", "DA", "庞月")
    expect("双人局里把自己电死的人算输",
           kill_game.over and kill_game.winner == "阿伟")
    expect("双人结算排名：赢家第 1、自尽的人第 2",
           "阿伟 1胜0负 · 本群第 1" in dr_reply(kill_result)
           and "庞月 0胜1负 · 本群第 2" in dr_reply(kill_result))

    # ---- 双人对赌：拒绝 / 公开挑战 / 一桌一座 ----
    devil.clear()
    refused = dr_run("恶魔轮盘赌", "DA", "庞月", "G-DR-REFUSE",
                     opponents=[("DB", "阿伟")])["panel"]
    answer = devil.handle(dr_labels(refused)["拒绝"], "G-DR-REFUSE", "DB", "阿伟")
    expect("另一边可以拒绝挑战", "拒绝" in dr_reply(answer))

    devil.clear()
    open_menu = dr_run("恶魔轮盘赌", "DA", "庞月", "G-DR-OPEN")["panel"]
    opened = devil.handle(dr_labels(open_menu)["公开挑战"],
                          "G-DR-OPEN", "DA", "庞月")
    expect("公开挑战谁都能接", opened["panel"]["user_ids"] == [])
    expect("发起人自己不能接",
           "自己接自己" in dr_reply(devil.handle(
               dr_labels(opened["panel"])["接受·道具"],
               "G-DR-OPEN", "DA", "庞月")))
    devil.handle(dr_labels(opened["panel"])["接受·道具"],
                 "G-DR-OPEN", "DC", "路人")
    expect("旁人接了直接开局", devil.active("G-DR-OPEN") is not None)
    busy_menu = dr_run("恶魔轮盘赌", "DD", "阿曼", "G-DR-OPEN")["panel"]
    blocked = devil.handle(dr_labels(busy_menu)["单人·道具"],
                           "G-DR-OPEN", "DD", "阿曼")
    expect("同一个群不能同时开两桌", "已经有一桌" in dr_reply(blocked))

    # ---- 过期：挑战帖 / 对局 / 旧面板 ----
    fixed = [1000.0]
    devil.now = lambda: fixed[0]
    devil.clear()
    stale_invite = dr_run("恶魔轮盘赌", "DA", "庞月", "G-DR-EXP",
                          opponents=[("DB", "阿伟")])["panel"]
    fixed[0] += INVITE_TTL + 1
    expired = devil.handle(dr_labels(stale_invite)["接受·道具"],
                           "G-DR-EXP", "DB", "阿伟")
    expect("挑战帖三分钟不接就过期", "过期" in dr_reply(expired))

    devil.clear()
    before_ttl = handler.cards.shards_of("DA")
    ttl_menu = dr_run("恶魔轮盘赌", "DA", "庞月", "G-DR-TTL")["panel"]
    devil.handle(dr_labels(ttl_menu)["单人·纯赌"], "G-DR-TTL", "DA", "庞月")
    expect("开局先扣入场费",
           handler.cards.shards_of("DA") == before_ttl - ENTRY_FEE)
    fixed[0] = 2000.0
    fixed[0] += DEVIL_SESSION_TTL + 1
    expect("半小时没人动就散桌", devil.active("G-DR-TTL") is None)
    expect("超时散桌把入场费原路退回",
           handler.cards.shards_of("DA") == before_ttl)
    devil.now = time.time

    devil.clear()
    stale_menu = dr_run("恶魔轮盘赌", "DA", "庞月", "G-DR-STALE")["panel"]
    devil.handle(dr_labels(stale_menu)["单人·纯赌"],
                 "G-DR-STALE", "DA", "庞月")
    stale_game = devil.active("G-DR-STALE")
    old_data = devil_panel_data(stale_game.gid, stale_game.seq, ACT_SHOOT)
    dr_panel(stale_game)          # 出一张新面板，旧的就该作废
    stale = devil.handle(old_data, "G-DR-STALE", "DA", "庞月")
    expect("旧面板点了只提示看最新那条", "最新" in dr_reply(stale))

    # ---- 大肥鱼的 AI 与台词 ----
    devil.clear()
    ai_start = dr_start(group="G-DR-AI")
    ai_game = devil.active("G-DR-AI")
    ai_game.players[1].items = []
    ai_game.players[0].hp = DEVIL_MAX_HP
    ai_game.shells = [True, False]
    ai_game.idx = 0
    ai_game.turn = 1
    ai_game.revealed = {0: True}
    devil._ai_act(ai_game)
    expect("大肥鱼知道是实弹就打人",
           ai_game.players[0].hp == DEVIL_MAX_HP - 1)

    ai_game.turn = 1
    ai_game.shells = [False, True]
    ai_game.idx = 0
    ai_game.revealed = {0: False}
    devil._ai_act(ai_game)
    expect("大肥鱼知道是空包就打自己、继续开枪", ai_game.turn == 1)

    expect("大肥鱼有一整套奶凶台词", len(DEVIL_TAUNTS) >= 8)
    expect("大肥鱼被打败的不甘心台词够多", len(DEFEAT_LINES) >= 5)
    expect("大肥鱼挨打和打中人都有一句话",
           len(HURT_LINES) >= 3 and any(HURT_LINES))
    expect("大肥鱼的电量和玩家同一个上限", DEVIL_MAX_HP == 5)

    # ---- handler 路由：文字命令 / @ 定向挑战 / 闲聊不误伤 ----
    devil.clear()
    sender.events.clear()
    sender.panels.clear()
    await handler.handle(Incoming(
        group_openid="G-DR-H", user_openid="DH", username="庞月",
        content="恶魔轮盘赌", msg_id="mdr1",
    ))
    expect("handler 把「恶魔轮盘赌」路由成按钮面板", bool(sender.panels))
    expect("面板正文带本群榜",
           bool(sender.events) and "本群榜" in sender.events[0][1])

    sender.events.clear()
    sender.panels.clear()
    await handler.handle(Incoming(
        group_openid="G-DR-H2", user_openid="DH", username="庞月",
        content="恶魔轮盘赌", msg_id="mdr2", mention_ids=["DO"],
    ))
    permission = sender.panels[-1][0]["buttons"][0]["action"]["permission"]
    expect("handler 把 @ 到的人当成挑战对象",
           permission.get("type") == 0
           and "DO" in (permission.get("specify_user_ids") or []))

    sender.events.clear()
    sender.panels.clear()
    await handler.handle(Incoming(
        group_openid="G-DR-H", user_openid="DH", username="庞月",
        content="今天吃什么好呢", msg_id="mdr3",
    ))
    expect("普通闲聊不会被恶魔轮盘赌抢走", not sender.events)
    devil.clear()
    devil.now = time.time

    print("== 宠物冒险 ==")

    class Forged:
        """冒充 forge_new.Session：剑库只读这几个字段。"""

        user = "A1"
        name = "冒险测试"
        knife = "M9刺刀"
        pattern = "渐变之色"
        attrs = [88, 74, 66]
        wear = 0.02

        class material:  # noqa: N801 - 冒充 Material 实例
            name = "强化合金"

    async def af(content, user="A1", name="冒险测试", msg_id="af"):
        sender.events.clear()
        sender.panels.clear()
        await handler.handle(Incoming(
            group_openid="G1", user_openid=user, username=name,
            content=content, msg_id=msg_id,
        ))

    def af_button(label):
        rows = sender.panels[-1] if sender.panels else []
        for row in rows:
            for button in row["buttons"]:
                if button["render_data"]["label"] == label:
                    return button["action"]["data"]
        return ""

    def af_labels():
        rows = sender.panels[-1] if sender.panels else []
        return [button["render_data"]["label"]
                for row in rows for button in row["buttons"]]

    def af_panel_ok() -> bool:
        """面板必须过 panel.py 的平台限制：≤5 行、每行 ≤5 个、label ≤10 字。"""
        rows = sender.panels[-1] if sender.panels else []
        return (bool(rows) and len(rows) <= MAX_ROWS
                and all(1 <= len(row["buttons"]) <= MAX_BUTTONS_PER_ROW
                        for row in rows)
                and all(len(button["render_data"]["label"]) <= MAX_LABEL_CHARS
                        for row in rows for button in row["buttons"]))

    def af_text() -> str:
        return sender.events[0][1] if sender.events else ""

    async def af_home():
        """回到没在打的那张首页（顺手清掉结算画面）。"""
        await af("宠物 冒险")
        if af_button("回主面板"):
            await af(af_button("回主面板"))
        if af_button("收工"):
            await af(af_button("收工"))
            await af("宠物 冒险")
            if af_button("回主面板"):
                await af(af_button("回主面板"))

    async def af_start():
        await af_home()
        await af(af_button("出发"))

    async def af_battle(kind=KIND_NORMAL):
        run = handler.swords._run("A1")
        run["options"] = [handler.swords._battle_node(run, kind)]
        handler.swords._save()
        await af("宠物 冒险")
        await af(af_button("①" + handler.swords._run("A1")["options"][0]["label"]))

    # ---- 内容表 ----
    monster_names = [monster.name for plane in PLANES
                     for monster in plane.pool + (plane.elite, plane.boss)]
    expect("8 个位面 × 每位面 5 层",
           len(PLANES) == 8 and FLOORS_PER_PLANE == 5)
    expect("40 只怪，名字不重复",
           len(monster_names) == 40 and len(set(monster_names)) == 40)
    expect("每只怪都有自己的招式",
           all(monster.moves for plane in PLANES
               for monster in plane.pool + (plane.elite, plane.boss)))
    expect("道具 19 / 遗物 20 / 招式 10 / 事件 24",
           (len(ITEMS), len(RELICS), len(MOVES), len(EVENTS)) == (19, 20, 10, 24))
    expect("每个道具都写了效果，并标明是一次性的",
           all(item.desc and item.once for item in ITEMS.values()))
    expect("遗物说明里正面和负面都写着",
           all(len(relic.desc) >= 6 for relic in RELICS.values())
           and any("但" in relic.desc or "-" in relic.desc
                   for relic in RELICS.values()))
    expect("招式描述里写了冷却与倍数",
           all("冷却" in move.desc for move in MOVES.values()
               if move.cooldown))

    # ---- 难度：越往后越硬 ----
    p1 = stats_for(PLANES[0].pool[0], 1, 1, KIND_NORMAL)
    p1_boss = stats_for(PLANES[0].boss, 1, 5, KIND_BOSS)
    p8 = stats_for(PLANES[7].pool[0], 8, 5, KIND_NORMAL)
    p8_boss = stats_for(PLANES[7].boss, 8, 5, KIND_BOSS)
    expect("同一只怪在第 40 关比第 1 关硬一倍以上",
           stats_for(PLANES[0].pool[0], 8, 5, KIND_NORMAL)["hp"] > p1["hp"] * 2)
    expect("最后的首领比第一只小怪硬 10 倍以上",
           p8_boss["hp"] > p1["hp"] * 10)
    expect("首领血量 / 攻击都比同层小怪高",
           p1_boss["hp"] > p1["hp"] and p8_boss["attack"] > p8["attack"])
    expect("第 40 关的银币也更高", loot_coins(8, 5, KIND_BOSS) > loot_coins(1, 1, KIND_NORMAL) * 5)

    # ---- 分支随机性 ----
    layouts = set()
    for seed in range(40):
        handler.swords.rng = random.Random(seed)
        fake = {"plane": 1, "floor": 2, "owner": "A1"}
        nodes = handler.swords._build_options(fake)
        expect_ok = 2 <= len(nodes) <= 3 and all(node["detail"] for node in nodes)
        if not expect_ok:
            layouts.add(("BAD",))
        layouts.add(tuple(node["kind"] for node in nodes))
    expect("每层都是 2~3 条分支，而且每条都写了内容",
           ("BAD",) not in layouts)
    expect("存在“只有打怪和精英”的分支组合",
           any(all(kind in ("战斗", "精英") for kind in combo)
               for combo in layouts if combo != ("BAD",)))
    expect("不是每层都一定有休整或事件",
           any("休整" not in combo and "事件" not in combo
               for combo in layouts if combo != ("BAD",)))
    handler.swords.rng = random.Random(1)
    boss_nodes = handler.swords._build_options({"plane": 2, "floor": 5, "owner": "A1"})
    expect("第 5 层只有一个首领",
           [node["kind"] for node in boss_nodes] == [KIND_BOSS])

    # ---- 开局 ----
    handler.cards.grant_shards("A1", 2000)
    handler.swords.clear()
    handler.swords.rng = random.Random(3)
    blade = handler.swords.record_forge(Forged(), 420, 9000)
    expect("锻造收工的剑自动进剑库",
           blade is not None and len(handler.swords.swords_of("A1")) == 1)
    expect("剑库落盘", (temporary / SWORD_FILE).is_file())

    await af("宠物 冒险")
    expect("首页有「出发 / 剑库 / 养成」三个按钮",
           {"出发", "剑库", "养成"} <= set(af_labels()))
    expect("首页写清位面塔规模", "8 个位面 × 5 层" in af_text())
    expect("首页过平台限制", af_panel_ok())

    await af(af_button("出发"))
    run = handler.swords._run("A1")
    expect("开局在位面1第1层", (run["plane"], run["floor"]) == (1, 1))
    expect("血量 = 26 + 坚韧//2 + 等级×2",
           run["hp_max"] == 26 + toughness_of(blade) // 2 + 2)
    expect("开局锋利度就是剑的锋利度", run["sharp"] == blade["sharp"])
    expect("开局就有 2~3 条分支", 2 <= len(run["options"]) <= 3)
    expect("分支的说明都写在面板上",
           all(node["detail"] in af_text() for node in run["options"]))
    expect("地图面板过平台限制", af_panel_ok())

    battle_node = handler.swords._battle_node(run, KIND_NORMAL)
    expect("战斗分支写明怪物血量 / 攻击 / 预计银币",
           "HP" in battle_node["detail"] and "攻击" in battle_node["detail"]
           and "银币" in battle_node["detail"])
    event_node = handler.swords._event_node()
    expect("事件分支写明第一个选项能拿到什么",
           "事件：" in event_node["detail"] and "——" in event_node["detail"])

    # ---- 战斗 ----
    run = handler.swords._run("A1")
    run["options"] = [handler.swords._battle_node(run, KIND_NORMAL)]
    handler.swords._save()
    await af("宠物 冒险")
    await af(af_button("①战斗"))
    run = handler.swords._run("A1")
    battle = run["battle"]
    expect("战斗面板写了敌人、意图、我的血",
           "意图" in af_text() and "HP" in af_text())
    expect("战斗按钮有挥剑 / 防守 / 道具 / 撤退",
           {"挥剑", "防守", "道具", "撤退"} <= set(af_labels()))
    expect("战斗面板过平台限制", af_panel_ok())

    before_sharp = run["sharp"]
    battle["hp"] = 1
    handler.swords._save()
    await af(af_button("挥剑"))
    run = handler.swords._run("A1")
    expect("打赢进战利品面板，三选一",
           run["mode"] == "reward" and len(run["rewards"]) == 3)
    expect("打赢一场扣 4 点锋利度", run["sharp"] == before_sharp - 4)
    expect("银币先进本局钱包", run["coins"] > 0)
    expect("战利品面板过平台限制", af_panel_ok())

    await af(af_button(af_labels()[0]))
    run = handler.swords._run("A1")
    expect("拿完战利品进第 2 层", (run["plane"], run["floor"]) == (1, 2))
    expect("通过一层给 1 鲸鳞", run["scales"] == 1)

    # ---- 事件：每个选项的结果都写在面板上 ----
    run = handler.swords._run("A1")
    run["options"] = [handler.swords._event_node()]
    handler.swords._save()
    await af("宠物 冒险")
    await af(af_button("①事件"))
    event_obj = EVENTS[(handler.swords._run("A1")["node"] or {})["event"]]
    expect("事件面板逐条写清每个选项的结果",
           all(option.detail in af_text() for option in event_obj.options))
    expect("事件面板过平台限制", af_panel_ok())
    await af(af_button(af_labels()[0]))
    expect("事件做完就推进一层",
           (handler.swords._run("A1")["plane"], handler.swords._run("A1")["floor"]) == (1, 3))

    # 防守：格挡顶掉伤害
    await af_battle()
    run = handler.swords._run("A1")
    run["hp"] = 50
    run["hp_max"] = 50
    battle = run["battle"]
    battle["attack"] = 10
    battle["turn"] = 1
    battle["intent"] = {"name": "测试啃咬", "multiplier": 1.0, "effect": ""}
    handler.swords._save()
    await af(af_button("防守"))
    run = handler.swords._run("A1")
    expect("防守给出 8 + 坚韧//2 的格挡",
           guard_block(run["tough"]) == 8 + run["tough"] // 2)
    expect("这一下被格挡吃掉，血量没掉", run["hp"] == 50)
    expect("拖到第 7 回合后敌人会越来越凶",
           handler.swords._enemy_attack_now(run, dict(run["battle"], turn=10))
           > run["battle"]["attack"] * 1.3)

    # ---- 招式 ----
    run = handler.swords._run("A1")
    handler.swords._gain_move(run, "次元鲸斩")
    battle = run["battle"]
    battle["hp"] = 500
    battle["hp_max"] = 500
    battle["attack"] = 0
    battle["turn"] = 1
    battle["intent"] = {"name": "发呆", "multiplier": 0.0, "effect": ""}
    handler.swords._save()
    await af("宠物 冒险")
    expect("战斗面板出现刚学会的招式", "次元鲸斩" in af_labels())
    await af(af_button("次元鲸斩"))
    run = handler.swords._run("A1")
    expect("招式打出伤害", run["battle"]["hp"] < 500)
    expect("招式进入冷却", run["cooldowns"]["次元鲸斩"] == 2)
    await af("宠物 冒险")
    await af(af_button("次元鲸斩"))
    expect("冷却中放不出来",
           any("冷却" in text for kind, text in sender.events if kind == "text"))

    # ---- 道具 ----
    run = handler.swords._run("A1")
    run["hp"] = 20
    run["items"] = []
    handler.swords._gain_item(run, "疗伤牛奶")
    handler.swords._save()
    await af("宠物 冒险")
    await af(af_button("道具"))
    expect("行囊写明效果、一次性、限战斗",
           "回复 30 HP" in af_text() and "（一次性）" in af_text())
    expect("行囊面板过平台限制", af_panel_ok())
    await af(af_button("用①"))
    run = handler.swords._run("A1")
    expect("用道具回了血", run["hp"] == 50)
    expect("用掉之后道具栏空了", run["items"] == [])

    run = handler.swords._run("A1")
    run["hp"] = 50
    run["items"] = []
    handler.swords._save()
    await af("宠物 冒险")
    await af(af_button("道具"))
    expect("没道具时行囊不给使用按钮",
           not any(label.startswith("用") for label in af_labels()))

    # ---- 两个格子：多的必须丢或换 ----
    run = handler.swords._run("A1")
    handler.swords._gain_item(run, "磨刀石")
    handler.swords._gain_item(run, "深海护符")
    expect("道具栏最多两个", handler.swords._gain_item(run, "回响贝壳") is False)
    state = handler.swords.active("G1", "A1")
    handler.swords._apply_effect(state, run, EFFECT_ITEM, "回响贝壳")
    expect("第三个道具会弹「装不下」面板", run["mode"] == "replace")
    await af("宠物 冒险")
    expect("替换面板把两个旧道具都列出来",
           "①" in af_text() and "②" in af_text())
    await af(af_button("替换①"))
    run = handler.swords._run("A1")
    expect("替换后第一个格子换成新的，总数还是 2",
           run["items"] == ["回响贝壳", "深海护符"])

    run = handler.swords._run("A1")
    state = handler.swords.active("G1", "A1")
    handler.swords._apply_effect(state, run, EFFECT_ITEM, "星屑瓶")
    await af("宠物 冒险")
    await af(af_button("丢弃新的"))
    expect("丢掉新道具时旧的两个不动",
           handler.swords._run("A1")["items"] == ["回响贝壳", "深海护符"])

    # ---- 遗物：正负效果都要生效 ----
    run = handler.swords._run("A1")
    run["hp_base"] = 100
    handler.swords._refresh_max_hp(run)
    run["hp"] = run["hp_max"] = 100
    before_attack = handler.swords._attack_power(run)
    handler.swords._gain_relic(run, "鲸骨护腕")
    expect("鲸骨护腕：攻击 +15%",
           handler.swords._attack_power(run) == int(round(before_attack * 1.15)))
    expect("鲸骨护腕：最大生命 -10%", run["hp_max"] == 90)
    expect("磨刀匠指环让磨刀便宜 30%",
           sharpen_cost(100, ("磨刀匠指环",))
           == int(round(100 * 3 * 0.7)))
    handler.swords._gain_relic(run, "回响鳞片")
    handler.swords._save()

    # ---- v2.14：数值事件 / 新道具 / 新遗物 ----
    expect("每个事件都配了大肥鱼的冒险描述",
           all(len(event.text) >= 12 for event in EVENTS.values()))
    expect("新事件里有纯正面提升（热泉疗养：最大生命 + 回血）",
           [eff for eff, _ in EVENTS["hot_spring"].options[0].good]
           == ["max_hp", "heal"])
    expect("新事件里有正负交换（深渊回声：攻击换生命）",
           ("atk", 20) in EVENTS["echo"].options[0].good
           and ("max_hp", -20) in EVENTS["echo"].options[0].good)
    expect("事件支持按百分比改最大生命",
           ("max_hp", "-25%") in EVENTS["last_stand"].options[0].good)
    expect("新道具既有纯正面也有正负",
           ITEMS["鲸脂膏"].extra == (("max_hp", 12),)
           and ITEMS["双刃鳞"].extra == (("max_hp", -8),)
           and ITEMS["苦胆酒"].extra == (("self_damage", 6),))
    expect("新道具说明把两种效果都写了",
           "最大生命 +12" in ITEMS["鲸脂膏"].desc
           and "最大生命 -8" in ITEMS["双刃鳞"].desc)
    expect("新遗物既有纯正面也有正负",
           RELICS["鲸脂护符"].desc.endswith("（纯正面）")
           and "攻击 +18%" in RELICS["双生珊瑚"].desc
           and "锋利度消耗 +25%" in RELICS["潮汐肺"].desc)

    state = handler.swords.active("G1", "A1")
    run = handler.swords._run("A1")
    hp_before = int(run["hp_max"])
    handler.swords._apply_effect(state, run, EFFECT_MAX_HP, 12)
    expect("事件「最大生命 +12」真的生效",
           abs(int(run["hp_max"]) - (hp_before + 12)) <= 2)
    atk_before = handler.swords._attack_power(run)
    handler.swords._apply_effect(state, run, EFFECT_ATK_FLAT, 6)
    delta = handler.swords._attack_power(run) - atk_before
    expect("事件「攻击 +6」真的生效（受百分比加成放大）",
           5 <= delta <= 9)
    block_before = guard_block(handler.swords._tough_power(run))
    handler.swords._apply_effect(state, run, EFFECT_TOUGH, 10)
    expect("事件「坚韧 +10」让防守格挡 +5",
           guard_block(handler.swords._tough_power(run)) == block_before + 5)
    sharp_max_before = int(run["sharp_max"])
    handler.swords._apply_effect(state, run, EFFECT_SHARP_MAX, 10)
    expect("事件「锋利度上限 +10」真的生效",
           int(run["sharp_max"]) == sharp_max_before + 10)
    hp_before = int(run["hp_max"])
    handler.swords._apply_effect(state, run, EFFECT_MAX_HP, "-25%")
    expect("事件能按百分比砍最大生命（-25%）",
           abs(int(run["hp_max"]) - int(round(hp_before * 0.75))) <= 2)

    run["items"] = []
    hp_before = int(run["hp_max"])
    notes = handler.swords._apply_item(run, run.get("battle"), ITEMS["鲸脂膏"])
    expect("鲸脂膏：回血 + 最大生命 +12",
           int(run["hp_max"]) > hp_before
           and any("最大生命 +12" in note for note in notes))
    atk_before = handler.swords._attack_power(run)
    handler.swords._apply_item(run, None, ITEMS["鲨牙粉"])
    delta = handler.swords._attack_power(run) - atk_before
    expect("鲨牙粉：本局攻击 +6（受百分比加成放大）",
           5 <= delta <= 9)
    atk_before = handler.swords._attack_power(run)
    hp_before = int(run["hp_max"])
    handler.swords._apply_item(run, None, ITEMS["双刃鳞"])
    expect("双刃鳞：攻击 +12%、最大生命下降",
           handler.swords._attack_power(run) > atk_before
           and 4 <= hp_before - int(run["hp_max"]) <= 10)
    block_before = guard_block(handler.swords._tough_power(run))
    handler.swords._apply_item(run, None, ITEMS["蜕壳素"])
    expect("蜕壳素：坚韧 +4（格挡 +2）",
           guard_block(handler.swords._tough_power(run)) == block_before + 2)
    battle = run.get("battle")
    if battle is not None:
        hp_before = int(run["hp"])
        handler.swords._apply_item(run, battle, ITEMS["苦胆酒"])
        expect("苦胆酒：本场攻击 +30%，自己 -6 HP",
               int(battle.get("atk_buff") or 0) >= 30
               and int(run["hp"]) == hp_before - 6)

    atk_before = handler.swords._attack_power(run)
    handler.swords._gain_relic(run, "鲨齿项链")
    expect("鲨齿项链：攻击 +10%",
           handler.swords._attack_power(run) - atk_before
           >= max(1, int(atk_before * 0.05)))
    block_before = guard_block(handler.swords._tough_power(run))
    handler.swords._gain_relic(run, "蜕鳞臂甲")
    expect("蜕鳞臂甲：坚韧 +8（格挡 +4）",
           guard_block(handler.swords._tough_power(run)) == block_before + 4)
    hp_before = int(run["hp_max"])
    handler.swords._gain_relic(run, "鲸脂护符")
    expect("鲸脂护符：最大生命 +12%",
           int(run["hp_max"]) > hp_before
           and abs(int(run["hp_max"]) - int(round(hp_before * 1.12))) <= 5)
    atk_before = handler.swords._attack_power(run)
    hp_before = int(run["hp_max"])
    handler.swords._gain_relic(run, "双生珊瑚")
    expect("双生珊瑚：攻击 +18%、最大生命 -8%",
           handler.swords._attack_power(run) > atk_before
           and int(run["hp_max"]) < hp_before)
    base_cost = handler.swords._battle_sharp_cost(run, KIND_NORMAL)
    hp_before = int(run["hp_max"])
    handler.swords._gain_relic(run, "潮汐肺")
    expect("潮汐肺：最大生命 +10%、锋利度消耗 +25%",
           int(run["hp_max"]) > hp_before
           and handler.swords._battle_sharp_cost(run, KIND_NORMAL)
           == max(1, int(round(base_cost * 1.25))))
    handler.swords._save()

    # ---- 局外养成 ----
    record = handler.swords.user("A1")
    record["meta"]["points"] = 10
    handler.swords._save()
    await af("宠物 养成")
    expect("养成面板列出全部 6 项",
           sum(1 for upgrade in META_UPGRADES.values()
               if upgrade.name in af_text()) == 6)
    expect("养成面板过平台限制", af_panel_ok())
    await af(af_button("硬鳞"))
    meta = handler.swords.user("A1")["meta"]
    expect("买一级硬鳞：等级 +1、鲸鳞 -2",
           meta["upgrades"]["hp"] == 1 and meta["points"] == 8)
    meta["points"] = 0
    handler.swords._save()
    await af(af_button("利齿"))
    expect("鲸鳞不够时明确拒绝",
           any("鲸鳞" in text for kind, text in sender.events if kind == "text"))

    await af_home()
    await af(af_button("出发"))
    expect("养成「硬鳞」让下一趟血量 +8",
           handler.swords._run("A1")["hp_max"] == 26 + toughness_of(blade) // 2 + 2 + 8)

    # ---- 位面推进 / 首领 / 通关 ----
    run = handler.swords._run("A1")
    run["plane"] = 1
    run["floor"] = 5
    run["options"] = [handler.swords._battle_node(run, KIND_BOSS)]
    handler.swords._save()
    await af("宠物 冒险")
    await af(af_button("①首领"))
    run = handler.swords._run("A1")
    run["battle"]["hp"] = 1
    scales_before = run["scales"]
    handler.swords._save()
    await af(af_button("挥剑"))
    run = handler.swords._run("A1")
    expect("首领额外给 3 鲸鳞", run["scales"] == scales_before + 3)
    await af(af_button(af_labels()[0]))
    run = handler.swords._run("A1")
    expect("打完位面首领进下一位面第 1 层",
           (run["plane"], run["floor"]) == (2, 1))

    run["plane"] = 8
    run["floor"] = 5
    run["options"] = [handler.swords._battle_node(run, KIND_BOSS)]
    handler.swords._save()
    await af("宠物 冒险")
    await af(af_button("①首领"))
    run = handler.swords._run("A1")
    run["battle"]["hp"] = 1
    handler.swords._save()
    await af(af_button("挥剑"))
    await af(af_button(af_labels()[0]))
    last = handler.swords.user("A1").get("last_run") or {}
    expect("打完第 8 个位面的首领 = 通关",
           last.get("outcome") == "clear" and last.get("scales", 0) >= 10)
    expect("通关奖励只有鲸鳞（不再发宠物经验）",
           last.get("scales", 0) >= 10 and "exp" not in last
           and "coins" not in last)
    expect("通关后先问要不要存档",
           "通关 · 存档" in af_text() and "①存入" in af_labels())
    expect("存档面板过平台限制", af_panel_ok())
    expect("通关后没有进行中的一趟", handler.swords._run("A1") is None)

    # ---- 通关存档：3 个栏位 / 覆盖确认 ----
    snapshot = handler.swords.active("G1", "A1").save_snapshot
    expect("存档里是打首领之前的状态",
           isinstance(snapshot, dict) and snapshot.get("plane") == 8
           and snapshot.get("floor") == 5)
    await af(af_button("①存入"))
    expect("存进 1 号栏位",
           isinstance(handler.swords.user("A1")["saves"][0], dict))
    expect("存完写明已存入并给回主面板",
           "已存入" in af_text() and af_button("回主面板") != "")

    async def af_pending_save():
        """手动挂一份待存快照，用来测覆盖 / 不保存。"""
        panel = handler.swords.active("G1", "A1")
        panel.save_snapshot = dict(snapshot or {})
        panel.end = {"outcome": "clear", "coins": 0, "scales": 0,
                     "plane": 8, "floor": 5, "floors": 40, "sword": "测试",
                     "sharp": 50, "left": 0, "points": 0}
        await af("宠物 冒险")

    await af_pending_save()
    await af(af_button("①存入"))
    expect("已占用的栏位先问要不要覆盖",
           "覆盖" in af_text() and af_button("覆盖") != "")
    await af(af_button("取消"))
    expect("取消覆盖回到存档面板", "通关 · 存档" in af_text())
    await af(af_button("②存入"))
    expect("2 号栏位也能存",
           isinstance(handler.swords.user("A1")["saves"][1], dict))
    await af_pending_save()
    await af(af_button("不保存"))
    expect("不保存就回结算面板并注明没存",
           "没有存档" in af_text() and af_button("回主面板") != "")

    # ---- 哦鲸鲸大挑战 ----
    class PickRng:
        """random() 恒为 0（赌概率必中），choice 优先挑指定首领。"""

        def __init__(self, item, base):
            self.item = item
            self.base = base

        def choice(self, seq):
            if isinstance(seq, (list, tuple)) and self.item in seq:
                return self.item
            return self.base.choice(seq)

        def random(self):
            return 0.0

        def randint(self, low, high):
            return self.base.randint(low, high)

        def uniform(self, low, high):
            return self.base.uniform(low, high)

    await af("哦鲸鲸大挑战")
    expect("大挑战面板列出三档存档和三个首领",
           af_labels()[:3] == ["①挑战", "②挑战", "③挑战"]
           and "海德软脚虾" in af_text()
           and "显卡吞噬者老黄" in af_text() and "川建国" in af_text())
    expect("大挑战面板过平台限制", af_panel_ok())
    await af(af_button("③挑战"))
    expect("空栏位不能开挑战",
           any("还没有存档" in text for kind, text in sender.events
               if kind == "text"))

    # 首领 1：锁血 + 二阶段反弹
    handler.swords.rng = PickRng(CHALLENGE_BOSSES[0], random.Random(1))
    await af("哦鲸鲸大挑战")
    await af(af_button("①挑战"))
    run = handler.swords._run("A1")
    expect("挑战开局随机到海德软脚虾",
           bool(run and run.get("challenge"))
           and run["battle"]["name"] == "海德软脚虾")
    expect("挑战战斗面板过平台限制", af_panel_ok())
    run["battle"]["hp"] = 1
    run["hp"] = 500
    run["hp_max"] = 500
    handler.swords._save()
    await af("宠物 冒险")
    await af(af_button("挥剑"))
    run = handler.swords._run("A1")
    expect("一击秒杀会锁血并进二阶段",
           run["battle"]["name"] == "北国沙鹰虾"
           and run["battle"]["hp"] == 1800
           and run["battle"]["challenge_phase"] == 2)
    expect("转阶段那一回合它不出手", run["hp"] == 500)
    expect("二阶段下一手是防御（反弹）",
           (run["battle"]["intent"] or {}).get("effect") == "reflect")
    boss_hp = run["battle"]["hp"]
    await af("宠物 冒险")
    await af(af_button("挥剑"))
    run = handler.swords._run("A1")
    expect("它防御时攻击会被反弹（自己掉血）", run["hp"] < 500)
    expect("反弹阶段它只掉一点血", run["battle"]["hp"] > boss_hp - 300)
    run["battle"]["hp"] = 1
    run["battle"]["intent"] = {"name": "攻击", "multiplier": 1.0, "effect": ""}
    handler.swords._save()
    await af("宠物 冒险")
    await af(af_button("挥剑"))
    challenge = handler.swords.user("A1").get("last_challenge") or {}
    expect("挑战成功只给鲸鳞（不再发经验）",
           challenge.get("outcome") == "challenge_win"
           and challenge.get("scales") == CHALLENGE_SCALES
           and "exp" not in challenge)
    expect("挑战结算不发银币", "coins" not in challenge)
    expect("挑战胜场记进存档",
           int(handler.swords.user("A1")["saves"][0]["wins"]) == 1)

    # 首领 2：麻痹让防守失效
    handler.swords.rng = PickRng(CHALLENGE_BOSSES[1], random.Random(2))
    await af("哦鲸鲸大挑战")
    await af(af_button("①挑战"))
    run = handler.swords._run("A1")
    expect("挑战开局随机到老黄",
           run["battle"]["name"] == "显卡吞噬者老黄")
    expect("面板写明麻痹机制", "麻痹" in af_text())
    run["hp"] = 400
    run["hp_max"] = 400
    handler.swords._save()
    await af("宠物 冒险")
    await af(af_button("挥剑"))
    run = handler.swords._run("A1")
    expect("老黄的攻击会让人麻痹", int(run["battle"].get("paralyzed") or 0) == 1)
    hp_before = run["hp"]
    await af("宠物 冒险")
    await af(af_button("防守"))
    run = handler.swords._run("A1")
    expect("麻痹时防守失效（挡不住，直接掉血）", run["hp"] < hp_before)
    expect("挑战失败会记负场", True)  # 占位，下面真的打输再断言
    run["hp"] = 1
    run["battle"]["attack"] = 999
    run["battle"]["intent"] = {"name": "必杀", "multiplier": 1.0, "effect": ""}
    handler.swords._save()
    await af("宠物 冒险")
    await af(af_button("挥剑"))
    challenge = handler.swords.user("A1").get("last_challenge") or {}
    expect("挑战失败：不发鲸鳞也不发经验、记负场",
           challenge.get("outcome") == "challenge_lose"
           and challenge.get("scales") == 0
           and "exp" not in challenge
           and int(handler.swords.user("A1")["saves"][0]["losses"]) == 1)

    # 首领 3：攻击被弹开 + 自己回血
    handler.swords.rng = PickRng(CHALLENGE_BOSSES[2], random.Random(3))
    await af("哦鲸鲸大挑战")
    await af(af_button("①挑战"))
    run = handler.swords._run("A1")
    expect("挑战开局随机到川建国", run["battle"]["name"] == "川建国")
    expect("面板写明弹开与回血机制",
           "弹开" in af_text() and "回复" in af_text())
    run["battle"]["hp"] = 2000
    boss_hp = run["battle"]["hp"]
    run["battle"]["attack"] = 0
    run["battle"]["intent"] = {"name": "发呆", "multiplier": 0.0, "effect": ""}
    handler.swords._save()
    await af("宠物 冒险")
    await af(af_button("挥剑"))
    run = handler.swords._run("A1")
    expect("川建国会把攻击弹开（这一刀不掉血）",
           int(run["battle"]["hp"]) >= boss_hp)
    expect("他每回合还会自己回血", int(run["battle"]["hp"]) > boss_hp)

    other = SwordAdventure(paths.data, lambda: handler.cards, handler.pets)
    expect("存档落盘，新实例也读得到",
           isinstance(other.user("A1")["saves"][0], dict))
    # 这一场挑战先撤掉，免得影响后面的位面塔测试
    await af("宠物 冒险")
    await af(af_button("撤退"))
    handler.swords.rng = random.Random(3)

    # ---- 阵亡 ----
    await af_home()
    await af(af_button("出发"))
    run = handler.swords._run("A1")
    run["coins"] = 300
    run["scales"] = 4
    run["battles"] = [{"kind": KIND_BOSS, "turns": 2,
                       "plane": 1, "floor": 1}]
    run["hp"] = 1
    run["options"] = [handler.swords._battle_node(run, KIND_NORMAL)]
    expected_scales = handler.swords._run_reward(run, "dead")
    handler.swords._save()
    await af("宠物 冒险")
    await af(af_button("①战斗"))
    run = handler.swords._run("A1")
    run["battle"]["attack"] = 999
    run["battle"]["intent"] = {"name": "必杀", "multiplier": 1.0, "effect": ""}
    handler.swords._save()
    await af(af_button("挥剑"))
    last = handler.swords.user("A1").get("last_run") or {}
    expect("阵亡只带回一半鲸鳞",
           last.get("outcome") == "dead"
           and last.get("scales") == expected_scales
           and "exp" not in last)
    expect("阵亡结算里没有银币字段", "coins" not in last)
    expect("阵亡没有把进行中的一趟留在存档里",
           handler.swords._run("A1") is None)

    # ---- 鲸鳞兑换：启程资金 / 道具仓库 ----
    await af_home()
    meta = handler.swords.user("A1")["meta"]
    meta["points"] = 60
    handler.swords._save()
    await af("鲸鳞兑换")
    expect("兑换面板列出启程资金和全部兑换道具",
           "启程资金" in af_text()
           and all(name in af_text() for name, _ in EXCHANGE_ITEMS))
    expect("兑换面板过平台限制", af_panel_ok())
    first_name, first_price = EXCHANGE_ITEMS[0]
    await af(af_button("①买"))
    user = handler.swords.user("A1")
    expect("买道具扣鲸鳞、放进仓库",
           user["meta"]["points"] == 60 - first_price
           and user["vault"]["items"].get(first_name) == 1)
    await af(af_button("启程资金"))
    user = handler.swords.user("A1")
    expect("启程资金升级扣鲸鳞并记等级",
           user["vault"]["silver"] == 1
           and user["meta"]["points"]
           == 60 - first_price - EXCHANGE_SILVER_COSTS[0])
    await af(af_button("返回"))
    await af(af_button("出发"))
    run = handler.swords._run("A1")
    expect("启程资金让开局多一笔局内银币",
           run["coins"] == exchange_silver_bonus(1))
    expect("仓库道具开局自动带入", first_name in run["items"])
    expect("仓库里的道具用掉一件少一件",
           not handler.swords.user("A1")["vault"]["items"].get(first_name))
    wallet_before = handler.cards.shards_of("A1")
    await af("宠物 冒险")
    await af(af_button("收工"))
    expect("收工后不再往钱包塞银币",
           handler.cards.shards_of("A1") == wallet_before)

    # ---- 存档：新实例也能读回进行中的一趟 ----
    await af_home()
    await af(af_button("出发"))
    other = SwordAdventure(paths.data, lambda: handler.cards, handler.pets)
    expect("重开一个实例也能读回进行中的一趟", other._run("A1") is not None)
    await af("宠物 冒险")
    await af(af_button("收工"))
    expect("收工也能结算", (handler.swords.user("A1").get("last_run") or {}).get("outcome") == "quit")

    # ---- 命令 & 面板边界 ----
    await af_home()
    await af("宠物 剑库")
    expect("「宠物 剑库」直接开剑库", "剑库" in af_text())
    await af(af_button(af_labels()[0]))
    expect("点剑库里的剑就换上了",
           handler.swords.equipped_sword("A1")["id"] == blade["id"])
    await af("宠物 面板")
    expect("「宠物 面板」仍然走原来的宠物面板",
           bool(sender.panels) and "大肥鱼" in af_text())
    await af("宠物医院")
    expect("「宠物医院」这种闲聊不会被抢走", sender.events == [])
    expect("锻造那一局收工的剑也自动进了剑库（接线通了）",
           len(handler.swords.swords_of("N1")) >= 1)

    handler.swords.clear()

    print("== 规则覆盖 ==")
    rules_path = paths.data / "official_rules.json"
    rules_path.write_text(json.dumps({"text": {"测试规则": "规则生效"}}, ensure_ascii=False),
                          encoding="utf-8")
    sender2 = FakeSender()
    handler2 = Handler(sender2, paths)
    await handler2.handle(Incoming(group_openid="G1", content="测试规则", msg_id="m2"))
    expect("official_rules.json 覆盖生效", sender2.events == [("text", "规则生效")])

    print()
    if failures:
        print(f"自检失败 {len(failures)} 项：{failures}")
        return 1
    print("自检全部通过")
    print(f"临时数据目录：{temporary}")
    return 0
