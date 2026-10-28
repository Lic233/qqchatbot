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
from .forge_rank import *  # noqa: F401,F403
from .handler import *  # noqa: F401,F403


# --------------------------------------------------------------------------
# 自检
# --------------------------------------------------------------------------

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class FakeSender:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    async def text(self, group: str, content: str, msg_id: str | None = None) -> None:
        # 和真正的 GroupSender 一样过千分位，否则自检看不出区别
        self.events.append(("text", format_numbers(content)))

    async def image(self, group: str, path: Path, msg_id: str | None = None) -> None:
        self.events.append(("image", Path(path).name))

    async def markdown(self, group: str, content: str,
                       msg_id: str | None = None) -> None:
        self.events.append(("markdown", content))

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
    await feed("你好呀", mentioned=True)
    expect("@ 触发 AI", sender.events == [("text", "收到：你好呀")])
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
    await feed("讲个长故事", mentioned=True, msg_id="m6")
    expect("长回复切成多条", len(sender.events) > 1)
    expect("每条都没超限", all(len(text) <= REPLY_CHUNK_CHARS for _, text in sender.events))

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

    print("== 千分位 ==")
    expect("六位以上切三位", format_numbers("现在价值 1234567") == "现在价值 1,234,567")
    expect("刚好六位才切", format_numbers("123456") == "123,456")
    expect("五位不动", format_numbers("价格 12345") == "价格 12345")
    expect("URL 里不动", format_numbers("https://x.com/123456789") == "https://x.com/123456789")
    expect("小数位不动", format_numbers("3.1415926") == "3.1415926")

    class FakeAPI:
        def __init__(self) -> None:
            self.texts: list[str] = []

        async def send_text(self, group: str, content: str,
                            msg_id: str | None = None, msg_seq: int = 1) -> dict:
            self.texts.append(content)
            return {"id": "x"}

        async def send_image(self, *args, **kwargs) -> dict:
            return {"id": "y"}

    fake_api = FakeAPI()
    await GroupSender(fake_api).text("G1", "碎片 1234567")
    expect("出群文本自动千分位", fake_api.texts == ["碎片 1,234,567"])

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

    # 单一卡池里再抽一定重复 → 折碎片
    while int(cards.user("U-CARD")["draws"]) > 0:
        cards.draw("U-CARD")
    expect("重复卡折成碎片", int(cards.user("U-CARD")["shards"]) > 0)
    expect("次数用完有提示", "明天" in cards.draw("U-CARD").text)

    # 开箱：碎片不足
    poor = cards.user("U-POOR")
    poor["shards"] = 10
    expect("碎片不够开箱", "要 500" in cards.open_box("U-POOR").text)

    # 开箱：扣 500 并给结果
    rich = cards.user("U-RICH")
    rich["shards"] = CARD_BOX_COST
    box = cards.open_box("U-RICH")
    expect("开箱有结果", any(word in box.text for word in ("始源卡", "附魔书", "碎片")))
    expect("开箱扣了 500", int(cards.user("U-RICH")["shards"]) < CARD_BOX_COST)

    # 始源卡改为完全随机：抽到已有的就折碎片，不再优先没出过的。
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

    # 十连：要 5000
    ten = cards.user("U-TEN")
    ten["shards"] = CARD_BOX_COST * CARD_BOX_TEN_COUNT
    reply_ten = cards.open_ten("U-TEN")
    expect("十连有汇总", "十个箱子" in reply_ten.text)
    expect("十连扣 5000", int(cards.user("U-TEN")["shards"]) < CARD_BOX_COST * CARD_BOX_TEN_COUNT)

    # 库存文案
    inventory = cards.inventory_text("U-CARD")
    expect("库存列了卡", "稀有" in inventory or "史诗" in inventory or "神话" in inventory)
    expect("库存报碎片", "奶龙碎片" in inventory)

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
    expect("签到给碎片", int(record["shards"]) > before)
    expect("签到用完次数", int(record["draws"]) == 0)
    expect(
        "记住今天签过",
        record.get("last_check_in") == datetime.date.today().isoformat(),
    )
    expect("当天第二次不给碎片", handler.cards.grant_check_in_shards("U1") is None)

    print("== 今日猫娘 / 随机老婆 ==")
    sender.events.clear()
    await feed("随便说句话", msg_id="m40")     # 让名册记住这个人
    expect("名册记住发言人", bool(handler.roster.members("G1")))
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
    expect("幸运暴击 2.0~2.5", CRIT_FACTOR == (2.0, 2.5))
    expect(
        "s1 附魔书就是这六本",
        BOOK_NAMES == ("经验修补", "重构", "时运", "升格", "保护", "掠夺"),
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
        "铁剑扣 250 碎片",
        forged["paid"] == 250 and handler.cards.shards_of("F1") == 750,
    )
    forge.clear()

    handler.cards.grant_shards("F1", 1000)
    forged = forge.start("G1", "F1", SWORDS["diamond"])
    expect(
        "钻石剑扣 500 碎片、初始价值 500",
        forged["paid"] == 500 and forged["value"] == 500,
    )
    forge.clear()

    # 无头骑士剑（限时）：恒定概率、自带修补、开局抽诅咒、收益封顶。
    # 这一段会真发碎片、真进榜，先把排行榜换成临时的一份，别污染后面的排行榜用例。
    headless_rank = ForgeRank(paths.data / "forge_rank_headless.json")
    real_rank = forge.rank
    forge.rank = headless_rank
    expect(
        "无头骑士剑概率恒定 25/45/30",
        outcome_table("headless", 9) == (0.25, 0.45, 0.30),
    )
    expect(
        "无头骑士剑 1.3~1.5、暴击 15%",
        SWORDS["headless"].factor == (1.3, 1.5)
        and SWORDS["headless"].crit_chance == 0.15,
    )
    expect(
        "无头骑士剑可以直接锻造",
        parse_sword("锻造 无头骑士剑") is SWORDS["headless"],
    )
    expect("无头骑士剑默认开放", headless_available())
    forge.clear()
    handler.cards.grant_shards("F1", 5000)
    forged = forge.start("G1", "F1", SWORDS["headless"])
    session = forge.active("G1", "F1")
    expect(
        "无头骑士剑扣 1000、初始价值 1000、完成度 50",
        forged["paid"] == 1000
        and forged["value"] == 1000
        and abs(session.completion - 50) < 1e-9,
    )
    expect("开局随机抽到一个诅咒", session.curse in CURSES)
    expect(
        "开局播报本场诅咒",
        f"诅咒【{session.curse}】" in start_text(forged, SWORDS["headless"]),
    )
    owned_before = handler.cards.books_of("F1")
    denied = forge.use_book("G1", "F1", "保护")
    expect(
        "无头骑士剑不吃附魔书（书也不扣）",
        denied["reason"] == "no_enchant"
        and handler.cards.books_of("F1") == owned_before,
    )
    session.curse = CURSE_BACKLASH
    expect(
        "诅咒·反噬把暴击率翻四倍",
        abs(forge.crit_chance(session) - 0.60) < 1e-9,
    )
    forge.rng = StubRng([0.30, 0.05, 2.2])
    crit = forge.strike("G1", "F1")
    expect(
        "诅咒·反噬：暴击时完成度 -5",
        crit.crit and crit.backlash and abs(crit.completion - 45) < 1e-9,
    )
    # 永生：倍率照常（1.3~1.5），完成度 +15，顶满就自动收工。
    forge.clear()
    handler.cards.grant_shards("F1", 5000)
    forge.start("G1", "F1", SWORDS["headless"])
    session = forge.active("G1", "F1")
    session.curse = CURSE_IMMORTAL
    session.completion_cap = INITIAL_COMPLETION
    session.completion = 50.0
    session.turns = 3
    forge.rng = StubRng([0.30, 0.99, 1.45])
    immortal = forge.strike("G1", "F1")
    expect(
        "诅咒·永生：倍率照常 1.3~1.5、增加时完成度 +15",
        1.3 <= immortal.factor <= 1.5
        and abs(immortal.completion - 65) < 1e-9
        and forge.active("G1", "F1") is not None,
    )
    forge.rng = StubRng([0.95, 0.99])
    unchanged = forge.strike("G1", "F1")
    expect(
        "诅咒·永生：不变时完成度也 +15",
        unchanged.outcome == "unchanged"
        and abs(unchanged.completion - 80) < 1e-9,
    )
    session.completion = 95.0
    forge.rng = StubRng([0.30, 0.99, 1.45])
    immortal_end = forge.strike("G1", "F1")
    expect(
        "诅咒·永生：满完成度强制收工",
        immortal_end.forced_end
        and forge.active("G1", "F1") is None
        and "强制收工" in strike_text(immortal_end),
    )
    # 失衡：失败不掉完成度，第三次直接报废。
    forge.clear()
    handler.cards.grant_shards("F1", 5000)
    forge.start("G1", "F1", SWORDS["headless"])
    session = forge.active("G1", "F1")
    session.curse = CURSE_UNBALANCED
    forge.rng = StubRng([0.0])
    first_fail = forge.strike("G1", "F1")
    expect(
        "诅咒·失衡：失败不掉完成度",
        first_fail.failed
        and first_fail.unbalanced
        and abs(forge.active("G1", "F1").completion - 50) < 1e-9,
    )
    forge.rng = StubRng([0.0])
    forge.strike("G1", "F1")
    forge.rng = StubRng([0.0])
    third_fail = forge.strike("G1", "F1")
    expect(
        "诅咒·失衡：失败三次强制失败、局消失",
        third_fail.forced_fail and forge.active("G1", "F1") is None,
    )
    # 收益封顶 50000。
    forge.clear()
    handler.cards.grant_shards("F1", 5000)
    forge.start("G1", "F1", SWORDS["headless"])
    session = forge.active("G1", "F1")
    session.value = 1e9
    session.completion = 100.0
    session.turns = 3
    capped = forge.end_forge("G1", "F1")
    expect(
        "无头骑士剑收益封顶 50000",
        capped["capped"] and capped["reward"] == 50000,
    )
    # 易碎：完成度上限 70、最终价值 ×1.8。
    forge.clear()
    handler.cards.grant_shards("F1", 5000)
    forge.start("G1", "F1", SWORDS["headless"])
    session = forge.active("G1", "F1")
    session.curse = CURSE_BRITTLE
    session.completion_cap = BRITTLE_COMPLETION_CAP
    session.value = 1000.0
    session.completion = BRITTLE_COMPLETION_CAP
    session.turns = 3
    brittle = forge.end_forge("G1", "F1")
    expect(
        "诅咒·易碎：×1.8 乘在收益上（价值不变）",
        brittle["brittle"]
        and brittle["value"] == 1000.0
        and brittle["reward"]
        == round(reward_for(1000, 70) * BRITTLE_REWARD_FACTOR),
    )
    expect(
        "易碎进榜记的是 ×1.8 之后的收益",
        any(
            item["user_id"] == "F1"
            and item["value"] == round(reward_for(1000, 70) * BRITTLE_REWARD_FACTOR)
            for item in headless_rank.leaderboard()
        ),
    )
    reloaded_headless = ForgeRank(paths.data / "forge_rank_headless.json")
    expect(
        "易碎倍率落盘后还在（读盘重算也带着 ×1.8）",
        any(
            item["value"] == round(reward_for(1000, 70) * BRITTLE_REWARD_FACTOR)
            for item in reloaded_headless.leaderboard()
        ),
    )
    # 三个新诅咒：鸩毒 / 贪饕 / 畸变。
    class CurseRng(StubRng):
        """开局抽诅咒时固定返回指定的那个（StubRng.choice 只会返回第一个）。"""

        def __init__(self, curse, values):
            super().__init__(values)
            self._curse = curse

        def choice(self, seq):
            return self._curse

    forge.clear()
    handler.cards.grant_shards("F1", 5000)
    forge.rng = CurseRng(CURSE_POISON, [0.30, 0.99, 1.4])
    started = forge.start("G1", "F1", SWORDS["headless"])
    expect(
        "诅咒·鸩毒：开局完成度拉满 100",
        started["curse"] == CURSE_POISON and started["completion"] == 100,
    )
    forge.rng = StubRng([0.30, 0.99, 1.4])
    poisoned = forge.strike("G1", "F1")
    expect(
        "诅咒·鸩毒：增加不回完成度、每回合固定 -4",
        abs(poisoned.completion - 96) < 1e-9 and poisoned.poisoned,
    )
    forge.rng = StubRng([0.0])
    poisoned_fail = forge.strike("G1", "F1")
    expect(
        "诅咒·鸩毒：失败也不掉完成度、只掉那 4 点",
        poisoned_fail.failed and abs(poisoned_fail.completion - 92) < 1e-9,
    )
    forge.clear()
    handler.cards.grant_shards("F1", 5000)
    forge.rng = CurseRng(CURSE_GLUTTONY, [0.30, 0.99])
    started = forge.start("G1", "F1", SWORDS["headless"])
    expect("诅咒·贪饕能被抽到", started["curse"] == CURSE_GLUTTONY)
    forge.rng = StubRng([0.30, 0.99])
    plain = forge.strike("G1", "F1")
    expect("诅咒·贪饕：普通增加固定 1.1", plain.factor == GLUTTONY_FACTOR)
    forge.rng = StubRng([0.30, 0.05])
    gluttony_crit = forge.strike("G1", "F1")
    expect(
        "诅咒·贪饕：暴击固定 10 倍",
        gluttony_crit.crit and gluttony_crit.factor == GLUTTONY_CRIT_FACTOR,
    )
    forge.clear()
    handler.cards.grant_shards("F1", 5000)
    forge.rng = CurseRng(CURSE_MUTATION, [0.0, 40])
    forge.start("G1", "F1", SWORDS["headless"])
    session = forge.active("G1", "F1")
    session.value = 1000.0
    forge.rng = StubRng([0.0, 40])
    mutated = forge.strike("G1", "F1")
    expect(
        "诅咒·畸变：失败价值 ×2、完成度掉 30~50",
        mutated.mutated
        and abs(mutated.value - 2000) < 1e-9
        and abs(mutated.completion - 10) < 1e-9,
    )
    forge.rank = real_rank
    headless_rank.clear()
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

    handler.cards.grant_shards("F1", 1000)
    forge.clear()
    forge.start("G1", "F1", SWORDS["stone"])
    handler.cards.user("F1")["books"] = {"保护": 2}
    handler.cards._save()
    armed = forge.use_book("G1", "F1", "保护")
    expect(
        "贴保护成功、3 回合后才到账",
        armed["ok"] and armed["books_left"] == 6 and not armed["guard_ready"],
    )
    forge.rng = StubRng([0.5, 0.99, 1.2] * 3)
    for _ in range(3):
        forge.strike("G1", "F1")
    expect("保护三回合后到账", forge.active("G1", "F1").guard)
    forge.rng = StubRng([0.0])
    result = forge.strike("G1", "F1")
    expect(
        "保护挡下完成度损失",
        result is not None
        and result.guarded
        and abs(result.completion - 100) < 1e-9
        and abs(result.value - 86.4) < 1e-9,
    )
    again = forge.use_book("G1", "F1", "保护")
    expect(
        "保护一局只能一次",
        again["reason"] == "already" and handler.cards.books_of("F1").get("保护") == 1,
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

    # 掠夺：不变也涨价值（1.2~1.4），不暴击。
    handler.cards.grant_shards("F1", 1000)
    forge.start("G1", "F1", SWORDS["stone"])
    handler.cards.user("F1")["books"] = {"掠夺": 1}
    handler.cards._save()
    expect("贴掠夺成功", forge.use_book("G1", "F1", "掠夺")["ok"])
    forge.rng = StubRng([0.95, 1.2])
    plundered = forge.strike("G1", "F1")
    expect(
        "掠夺把「不变」变成涨 20%",
        plundered is not None and plundered.plunder
        and abs(plundered.value - 60) < 1e-9
        and abs(plundered.value_before - 50) < 1e-9,
    )
    forge.clear()

    # 升格：吃 2 个次数，剑变下界合金剑（1.6~1.8 / 暴击 20% / 失败 20%）。
    handler.cards.grant_shards("F1", 1000)
    forge.start("G1", "F1", SWORDS["stone"])
    handler.cards.user("F1")["books"] = {"升格": 2}
    handler.cards._save()
    upgraded = forge.use_book("G1", "F1", "升格")
    expect(
        "升格吃 2 个次数、换成下界合金剑",
        upgraded["ok"] and upgraded["books_left"] == 5
        and forge.active("G1", "F1").sword == "netherite",
    )
    forge.rng = StubRng([0.3, 0.5, 1.7])
    hit = forge.strike("G1", "F1")
    expect(
        "下界合金剑用 1.6~1.8",
        hit is not None and abs(hit.value - 85) < 1e-9 and not hit.crit,
    )
    expect(
        "升格不能贴第二次",
        forge.use_book("G1", "F1", "升格")["reason"] == "already",
    )
    forge.clear()

    handler.cards.grant_shards("F1", 1000)
    forge.start("G1", "F1", SWORDS["stone"])
    forge.active("G1", "F1").books_used = 6
    denied = forge.use_book("G1", "F1", "升格")
    expect(
        "升格只剩 1 个次数时拒绝",
        denied["reason"] == "limit" and denied.get("need") == 2,
    )
    forge.clear()

    handler.cards.grant_shards("F1", 1000)
    forge.start("G1", "F1", SWORDS["stone"])
    forge.rng = StubRng([0.5, 0.99, 1.2] * 3)
    for _ in range(3):
        forge.strike("G1", "F1")
    ended = forge.end_forge("G1", "F1", "测试锻造人")
    expect(
        "收工按收益曲线发碎片",
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

    print("== 锻造命令 ==")
    handler.forge.rng = random
    handler.checkin_renderer = None
    handler.cards.grant_shards("U1", 10000)
    sender.events.clear()
    await feed("锻造 石剑", msg_id="fg1")
    expect(
        "锻造开局有回复",
        any("石剑" in text for kind, text in sender.events if kind == "text"),
    )
    sender.events.clear()
    await feed("收工", msg_id="fg2")
    expect(
        "没砸够不能收工",
        any("再砸" in text for kind, text in sender.events if kind == "text"),
    )
    sender.events.clear()
    await feed("用力砸", msg_id="fg3")
    expect(
        "用力砸有结果",
        any("回合" in text for kind, text in sender.events if kind == "text"),
    )

    handler.forge.clear()
    sender.events.clear()
    await feed("锻造 石剑", msg_id="fg6")
    handler.forge.rng = StubRng([0.5, 0.99, 1.2] * 3)
    await feed("用力砸3", msg_id="fg7")
    expect(
        "用力砸3 一条消息回三行",
        any(
            kind == "text" and text.count("已进行") == 3
            for kind, text in sender.events
        ),
    )

    handler.forge.clear()
    sender.events.clear()
    await feed("锻造 石剑", msg_id="fg8")
    handler.forge.rng = StubRng([0.5, 0.99, 1.2] * 10)
    await feed("用力砸99", msg_id="fg9")
    expect(
        "用力砸99 截到 10 下并提示",
        any(
            kind == "text"
            and text.count("已进行") == 10
            and "最多连砸" in text
            for kind, text in sender.events
        ),
    )

    handler.forge.clear()
    sender.events.clear()
    await feed("锻造 石剑", msg_id="fg10")
    handler.forge.rng = StubRng([0.5, 0.99, 1.2, 0.0, 40])
    await feed("用力砸5", msg_id="fg11")
    expect(
        "用力砸5 碰到失败就停、并说明剩下几下",
        any(
            kind == "text"
            and text.count("已进行") == 2
            and "先停手" in text
            and "剩下的 3 下" in text
            for kind, text in sender.events
        ),
    )
    handler.forge.rng = random

    handler.forge.clear()
    sender.events.clear()
    await feed("附魔 保护", msg_id="fg4")
    expect(
        "没局时附魔只提示",
        any("先发" in text for kind, text in sender.events if kind == "text"),
    )
    sender.events.clear()
    await feed("锻造排行榜", msg_id="fg5")
    expect(
        "排行榜文字兜底",
        any("锻造排行榜" in text for kind, text in sender.events if kind == "text"),
    )

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
