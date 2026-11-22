"""离线自检：不联网，覆盖规则、命令、AI、搜索、复读、上传。

单独成文件，平时运行 bot 不用导入它（入口只在 --selftest 时延迟导入）。
"""
from __future__ import annotations

import math

from .ai import *  # noqa: F401,F403
from .api import *  # noqa: F401,F403
from .base import *  # noqa: F401,F403
from .cards import *  # noqa: F401,F403
from .config import *  # noqa: F401,F403
from .cs import *  # noqa: F401,F403
from .features import *  # noqa: F401,F403
from .forge import *  # noqa: F401,F403
from .forge_new import *  # noqa: F401,F403
from .forge_rank import *  # noqa: F401,F403
from .handler import *  # noqa: F401,F403
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

    # AI 短回复默认会自带一条语音条。自检不联网，也不该真去开 edge/PowerShell，
    # 所以全局把合成换成假的（「== 语音 ==」那节自己会临时换成另一个假的）。
    from . import handler as handler_module

    ai_voices: list[str] = []

    async def fake_synthesize(text, **kwargs):
        ai_voices.append(text)
        out = temporary / "stub-voice.wav"
        out.write_bytes(b"RIFF" + b"\x00" * 1024)
        return out

    handler_module.synthesize = fake_synthesize

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

    async def fake_chat(system: str, text: str, images=None) -> str:
        ai_calls.append((system, text))
        image_calls.append(list(images or []))
        return "收到：" + text

    handler.chat = fake_chat
    sender.events.clear()
    ai_calls.clear()
    ai_voices.clear()
    await feed("你好呀", mentioned=True)
    expect("@ 触发 AI", sender.events == [("text", "收到：你好呀"),
                                        ("voice", "stub-voice.wav")])
    expect("短回复才念、念的是回复原文", ai_voices == ["收到：你好呀"])
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

    # 记忆按人分开：第二次对话能带上第一次的内容
    sender.events.clear()
    ai_calls.clear()
    await feed("我刚说了什么", mentioned=True)
    expect("记忆带进提示词", bool(ai_calls) and "你好呀" in ai_calls[0][0])

    # 换个用户就看不到别人的记忆
    sender.events.clear()
    ai_calls.clear()
    await handler.handle(Incoming(group_openid="G1", user_openid="U2", username="另一个人",
                                  content="你好呀", msg_id="m4", mentioned=True))
    expect("别人的记忆不串进来", bool(ai_calls) and "我刚说了什么" not in ai_calls[0][0])

    # 忘掉我：清空自己的记忆
    sender.events.clear()
    await feed("忘掉我", mentioned=False, msg_id="m5")
    expect("忘掉我 有回复", bool(sender.events) and sender.events[0][0] == "text")
    expect("忘掉我 真的清了", handler.memory.transcript("G1", "U1") == "")

    # 长回复自动分条
    sender.events.clear()

    async def long_chat(system: str, text: str, images=None) -> str:
        return "第一段。" * 400

    handler.chat = long_chat
    ai_voices.clear()
    await feed("讲个长故事", mentioned=True, msg_id="m6")
    expect("长回复切成多条", len(sender.events) > 1)
    expect("每条都没超限", all(len(text) <= REPLY_CHUNK_CHARS for _, text in sender.events))
    expect("长回复不念语音",
           all(kind == "text" for kind, _ in sender.events) and not ai_voices)

    # AI 失败要兜底，不能把异常抛出去
    sender.events.clear()

    async def broken_chat(system: str, text: str, images=None) -> str:
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

    handler.search = fake_search
    search_seen: dict = {}

    async def search_chat(system: str, text: str, images=None, search=None) -> str:
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

    async def vision_chat(system: str, text: str, images=None) -> str:
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
    expect("忘掉我清画像", profiles.forget("G1", "U9"))
    expect("清完就没了", profiles.summary_of("G1", "U9") == "")

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
