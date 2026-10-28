"""群消息业务处理：命令、关键词、歌词、AI 对话、复读。

只依赖下面几层；网关和入口不在这里。
"""
from __future__ import annotations

from .base import *  # noqa: F401,F403
from .cards import *  # noqa: F401,F403
from .config import *  # noqa: F401,F403
from .cs import (
    CS,
    CS_COMMANDS,
    CS_RESULT_COMMANDS,
    CS_TIMEOUT,
    brief_text,
    results_text,
)
from .features import *  # noqa: F401,F403
from .forge import (
    COMMAND_ENCHANT,
    MAX_STRIKE_BATCH,
    Forge,
    book_text,
    books_text,
    end_text,
    is_enchant_command,
    is_finish_command,
    is_forging_command,
    is_reforge_command,
    parse_book,
    parse_strike,
    parse_sword,
    rank_text,
    reforge_text,
    start_text,
    strike_batch_text,
    strike_text,
    sword_list_text,
)
from .forge_rank import ForgeRank, is_rank_command
from .videosum import (
    BiliClient,
    BiliBlocked,
    find_video_link,
    load_cookie,
    review_prompt,
)

try:  # Pillow 是可选依赖：没装就只发文字版
    from . import cs_card
except Exception:  # noqa: BLE001 - 缺字体/图片库都不该挡住主流程
    cs_card = None


# --------------------------------------------------------------------------
# 业务处理
# --------------------------------------------------------------------------

# 单独一个 @ 加这些话，算「让我看那个视频」。只认这些词是为了不抢普通提问：
# 群里刚有人发过链接，紧接着问「这个怎么下载」就不该被当成要看视频。
VIDEO_INTENT_WORDS = (
    "总结", "评价", "评一下", "讲讲", "说说", "看看", "看下", "看一",
    "瞅", "讲了什么", "讲了啥", "什么内容", "啥内容",
)


def wants_video_comment(text: str) -> bool:
    text = (text or "").strip()
    return bool(text) and any(word in text for word in VIDEO_INTENT_WORDS)


class Handler:
    def __init__(self, sender: GroupSender, paths: Paths, *,
                 chat=None, lyric_chat=None, memory: Memory | None = None,
                 search=None, persona_path: Path | None = None) -> None:
        self.sender = sender
        self.paths = paths
        self.text_rules, self.face_rules, self.image_rules = load_rules(self.paths.data)
        self.records = self._load_records()
        self.last_images: dict[str, ImageRef] = {}
        self.last_image_at: dict[str, float] = {}
        # 每个群上一条消息，用来判断「同一句话连发两次」要不要复读（+1）。
        self.last_messages: dict[str, str] = {}
        # 机器人自己的名字（启动后从 /users/@me 取），用来剥掉正文开头的「名字 + 空格」。
        self.bot_names: set[str] = set()
        # 机器人自己的 ID（openid / union_openid），启动后从 /users/@me 填；
        # 用来判断「这条到底是不是在 @ 我」——@ 别人时正文里带的是对方的 ID。
        self.bot_ids: set[str] = set()
        # 给 None 就是不开 AI（自检里不联网时也走这条路）。
        self.chat = chat
        # 联网搜索；None 表示这次不给模型搜索工具（提示词也会同步改口）。
        self.search = search
        # 视频总结：B站的 AI 文稿接口要登录态，没配 SESSDATA 也能跑，只是多半
        # 只剩标题和简介 —— 启动时把这件事说清楚，别等群里发链接才发现。
        self.video = None
        if VIDEO_SUMMARY_ENABLED:
            self.video = BiliClient(load_cookie())
            log(
                "[视频] 已启用"
                + ("（有登录态，能取 AI 文稿）" if self.video.sessdata
                   else "（没配 cookie，多半只能看标题和简介）")
            )
        # 群里最近一条 B站链接：很多人是先转发链接，再单独 @ 一句「看看这个」。
        self.last_video_links: dict[str, tuple[str, float]] = {}
        # 群里最近一次「收到卡片」的记录：(卡片里带的 B站标题, 时间)。
        # 手机端转发的视频卡片里没有链接、只有标题，下一句「总结」就靠它。
        self.last_card: dict[str, tuple[str, float]] = {}
        # 单独一个低温度的调用，给歌词接龙这种「只准回一行」的场合
        self.lyric_chat = lyric_chat or chat
        self.lyric_library = lyrics_line.LYRIC_LIBRARY_ENABLED
        self.memory = memory or Memory()
        self.persona_path = persona_path or PERSONA_FILE
        # 识图开关与上限，放在实例上方便自检里改小。
        self.vision_enabled = VISION_ENABLED
        self.vision_max_images = VISION_MAX_IMAGES
        self.vision_max_bytes = VISION_MAX_BYTES
        self.cards = Cards(self.paths.data)
        self.cs = CS()
        self.forge_rank = ForgeRank(self.paths.data / "forge_rank.json")
        self.forge = Forge(self.cards, self.forge_rank)
        self.attendance = Attendance(self.paths.data)
        self.roster = Roster(self.paths.data)
        self.profiles = Profiles(self.paths.data)
        # 原版渲染器的输出目录要跟着数据目录走（自检时是临时目录）
        self.checkin_renderer = load_checkin_renderer()
        # 渲染图只是发消息的中间产物：放系统临时目录，发完就删，data/ 里不留东西
        self.render_dir = Path(tempfile.gettempdir()) / "qqchatbot-render"
        if self.checkin_renderer is not None:
            self.checkin_renderer.CHECKIN_CARD_DIR = self.render_dir
        self.luck = DailyLuck(self.paths.data)

    # ---- 记录 ----

    def _load_records(self) -> dict[str, str]:
        if not self.paths.named_diaotu_file.is_file():
            return {}
        try:
            payload = json.loads(self.paths.named_diaotu_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            log(f"[吊图] 记录读取失败：{error}")
            return {}
        if not isinstance(payload, dict):
            return {}
        return {str(k): str(v) for k, v in payload.items() if isinstance(v, str)}

    def _save_records(self) -> bool:
        temporary = self.paths.named_diaotu / f"records_{os.getpid()}.tmp"
        try:
            temporary.write_text(
                json.dumps(self.records, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.paths.named_diaotu_file)
            return True
        except OSError as error:
            log(f"[吊图] 记录保存失败：{error}")
            temporary.unlink(missing_ok=True)
            return False

    # ---- 入口 ----

    async def handle(self, event: Incoming) -> bool:
        """入口：先跑业务；什么都没命中时，再决定要不要复读（+1）。

        复读判定必须放在**所有规则之后**：命令、关键词、歌词、AI 命中过就不跟，
        只有两条一模一样的闲聊才会触发。上一条消息按 (群) 记，重启清空。
        """
        if event.is_bot or not event.group_openid:
            return False
        handled = await self._handle(event)
        if not REPEAT_ENABLED:
            return handled
        key = " ".join(normalize_content(event.content).split())
        if not key:
            return handled
        group = event.group_openid
        if not handled and self.last_messages.get(group) == key:
            await self.sender.text(group, key, event.msg_id)
            log(f"[复读] 跟上一条：{key[:40]!r}")
            handled = True
        self.last_messages[group] = key
        return handled

    async def _handle(self, event: Incoming) -> bool:
        if event.is_bot:
            return False
        if not event.group_openid:
            return False
        if event.images:
            self.last_images[event.group_openid] = event.images[0]
            self.last_image_at[event.group_openid] = time.time()
        # 再归一化一次：正常事件在 parse_group_event 里已经清过，
        # 但 Handler 也可能被自检/其它来源直接调用，这里兜底保证命令干净。
        command = normalize_content(event.content)

        # 顺手记下这个群的 B站链接（不管有没有 @ 我）：实测的真实用法是先转发
        # 链接、再单独 @ 一句「看看这个」，那时候正文里已经没有链接了。
        video_link = find_video_link(command) or event.attached_url
        if video_link:
            self.last_video_links[event.group_openid] = (video_link, time.time())
        elif event.has_card or event.card_title:
            # 收到了卡片但一个链接都捞不出来（手机端转发 B站 视频就是这样，
            # 正文只剩「[卡片消息] 小程序 / title: … / source: 哔哩哔哩」）。
            # 记下标题和时间，等下一句「总结」来了按标题去搜。
            self.last_card[event.group_openid] = (
                event.card_title, time.time()
            )

        # 歌词接龙：**放在最前面**。以 ~ 结尾是比 @ 更明确的信号，
        # 原插件也是这个顺序（连 @ 过的消息也走接歌词）。
        if lyrics_line.LYRIC_ENABLED:
            lyric = lyrics_line.lyric_line(command)
            if lyric is not None:
                await self._reply_lyric(lyric, event)
                return True

        # 「忘掉我」：清掉这个人自己的记忆（和原插件 memory.forget 一致）
        if command == "忘掉我":
            forgotten = self.memory.forget(event.group_openid, event.user_openid)
            forgotten = self.profiles.forget(
                event.group_openid, event.user_openid
            ) or forgotten
            await self.sender.text(
                event.group_openid,
                "好啦好啦，你的那点事我已经忘干净了～" if forgotten
                else "我本来就不记得你什么呀",
                event.msg_id,
            )
            return True

        # 记住这个人（@ 人要用），顺手节流落盘
        self.roster.remember(event.group_openid, event.user_openid, event.username)
        self.roster.save()

        # 功能列表 / 更新日志（读 data 下的文本，原样发）
        if command in DOC_COMMANDS:
            await self._handle_docs(command, event)
            return True

        # 保存老婆（可带名字）
        if command == "保存老婆" or command.startswith("保存老婆"):
            await self._handle_save_wife(command, event)
            return True

        # 今日猫娘 / 随机老婆
        if command in WIFE_COMMANDS:
            await self._handle_wife(command, event)
            return True

        # 打卡 / 签到（固定命令）
        if command in ("打卡", "签到"):
            await self._handle_checkin(command, event)
            return True

        # 抽卡 / 开箱 / 库存（固定命令，任何时候都认）
        if command in CARD_COMMANDS:
            await self._handle_cards(command, event)
            return True

        # CS2 赛事 / 赛果（联网查 5EPlay，纯文字）。大小写不敏感，也认 @ 后残留的名字。
        for candidate in (
            command,
            self._strip_leading_name(command) if command else None,
        ):
            key = (candidate or "").strip().lstrip("/／").strip().lower()
            # 允许带参数：「cs赛事 今天」也走同一套（参数暂时不用，原插件也不看）
            key = key.split(None, 1)[0] if key else ""
            if key in CS_COMMANDS:
                await self._handle_cs(results=False, event=event)
                return True
            if key in CS_RESULT_COMMANDS:
                await self._handle_cs(results=True, event=event)
                return True

        # 锻造 / 附魔 / 重构 / 排行榜。日常词（用力砸、收工、重构）只在真有局时
        # 才算命令，所以 _handle_forge 内部会再看一次 active session。
        for candidate in (
            command,
            self._strip_leading_name(command) if command else None,
        ):
            if candidate and await self._handle_forge(candidate, event):
                return True

        # 实测：@ 的位置有时会留下机器人自己的名字（日志里出现过
        # ``'机器人 这也太这么强了吧'``）。所以对「前面的名字」再试一次。
        variant = self._strip_leading_name(command) if command else None
        candidates = [candidate for candidate in (command, variant) if candidate]

        # 命令优先于 AI：`@机器人 保存吊图` 仍然存图，不会变成闲聊。
        # 这和原插件（@ 一律走 AI）有意不同，见 README。
        for candidate in candidates:
            if await self._handle_save(candidate, event):
                return True
            if await self._handle_send(candidate, event):
                return True
            if await self._apply_rules(candidate, event):
                return True

        addressed = (event.mentioned and self._mentions_me(event)) or bool(variant)
        if addressed and self.chat is not None:
            if await self._handle_video(command, event, video_link):
                return True
            await self._reply_ai(variant or command, event)
            return True
        return False

    async def _handle_forge(self, command: str, event: Incoming) -> bool:
        """锻造系统的命令分发；不是锻造命令（或没局时的日常词）返回 False。"""
        text = command.strip()
        group, user = event.group_openid, event.user_openid
        if is_rank_command(text):
            await self._send_forge_rank(event)
            return True
        if is_forging_command(text):
            sword = parse_sword(text)
            if sword is None:
                await self.sender.text(group, sword_list_text(), event.msg_id)
                return True
            result = self.forge.start(group, user, sword)
            await self.sender.text(group, start_text(result, sword), event.msg_id)
            return True
        session = self.forge.active(group, user)
        if is_enchant_command(text) or text == COMMAND_ENCHANT:
            if session is None:
                # 光说「附魔」两个字在没局时当闲聊放过；「附魔 <书名>」给一句提示。
                if not is_enchant_command(text):
                    return False
                await self.sender.text(
                    group,
                    book_text(
                        {"ok": False, "reason": "no_forge"}, "",
                        self.cards.books_of(user),
                    ),
                    event.msg_id,
                )
                return True
            book = parse_book(text)
            owned = self.cards.books_of(user)
            if book is None:
                await self.sender.text(group, books_text(owned), event.msg_id)
                return True
            result = self.forge.use_book(group, user, book)
            await self.sender.text(
                group, book_text(result, book, owned), event.msg_id
            )
            return True
        if is_reforge_command(text):
            if session is None:
                return False
            reply = reforge_text(
                self.forge.reforge(group, user, event.username)
            )
            if reply:
                await self.sender.text(group, reply, event.msg_id)
            return True
        strike_count = parse_strike(text)
        if strike_count is not None:
            if session is None:
                return False
            if strike_count <= 0:
                await self.sender.text(
                    group,
                    "要砸几下呀？「用力砸 5」就是连砸 5 下；不写数字就砸一下。",
                    event.msg_id,
                )
                return True
            clamped = strike_count > MAX_STRIKE_BATCH
            count = min(strike_count, MAX_STRIKE_BATCH)
            results = self.forge.strike_many(group, user, count, event.username)
            if not results:
                return True
            if strike_count == 1:
                reply = strike_text(results[0])
            else:
                reply = strike_batch_text(results)
                if len(results) < count and not results[-1].ruined:
                    left = count - len(results)
                    reply += (
                        f"\n（第 {results[-1].turns} 回合锻造失败，先停手了，"
                        f"剩下的 {left} 下没砸 —— 想接着砸再发「用力砸」。）"
                    )
            if clamped:
                reply += (
                    f"\n（一次最多连砸 {MAX_STRIKE_BATCH} 下，"
                    "想继续再发「用力砸」。）"
                )
            await self.sender.text(group, reply, event.msg_id)
            return True
        if is_finish_command(text):
            if session is None:
                return False
            result = self.forge.end_forge(group, user, event.username)
            if result is None:
                return True
            reply = end_text(result, event.username)
            if reply:
                await self.sender.text(group, reply, event.msg_id)
            return True
        return False

    async def _send_forge_rank(self, event: Incoming) -> None:
        """「锻造排行榜」：有渲染器就发图，失败退回文字版。"""
        records = self.forge_rank.leaderboard()
        path = None
        if self.checkin_renderer is not None:
            try:
                path = await asyncio.to_thread(
                    self.checkin_renderer.render_forge_rank_card,
                    records=records,
                    user_id=event.user_openid,
                )
            except Exception as error:  # noqa: BLE001 - 画图失败不能让排行榜查不了
                log(f"[锻造排行榜] 渲染失败，退回文字：{error!r}")
        if path is None:
            await self.sender.text(
                event.group_openid, rank_text(records), event.msg_id
            )
            return
        try:
            await self.sender.image(event.group_openid, path, event.msg_id)
        finally:
            self._drop_rendered(path)

    async def _handle_docs(self, command: str, event: Incoming) -> None:
        """功能列表 / 更新日志：把 data 下的文本原样发出去（过长自动分条）。"""
        group = event.group_openid
        text = load_text_file(self.paths.doc(DOC_FILES[command]))
        if not text:
            await self.sender.text(group, DOC_EMPTY_REPLY[command], event.msg_id)
            return
        chunks, dropped = split_changelog(
            text, CHANGELOG_CHARS, CHANGELOG_MAX_MESSAGES
        )
        log(
            f"[{command}] 发 {len(chunks)} 条（正文 {len(text)} 字"
            f"{'，超出上限已截断' if dropped else ''}）"
        )
        for chunk in chunks:
            await self.sender.text(group, chunk, event.msg_id)
        if dropped:
            await self.sender.text(group, DOC_TRUNCATED_REPLY, event.msg_id)

    @staticmethod
    def _drop_rendered(path) -> None:
        """渲染出来的图发完就删：它只是发消息用的中间产物，留着白占地方。"""
        if path is None:
            return
        try:
            Path(path).unlink(missing_ok=True)
        except OSError as error:
            log(f"[图片] 删除临时图失败：{error}")

    async def _reply_lyric(self, line: str, event: Incoming) -> None:
        """歌词接龙：只回下一句（带 ~），接不上回兜底文案。

        顺序是「歌词库 → 模型」：库能命中就给确定答案（不编），
        库里没有这首歌才让模型接，而且只跑一轮、只准回一行。
        """
        group = event.group_openid
        following = ""
        source = ""
        if self.lyric_library:
            try:
                following, source = await asyncio.to_thread(
                    lyrics_line.lookup_next_line, line
                )
            except Exception as error:  # noqa: BLE001 - 库失败不该影响接龙
                log(f"[歌词] 歌词库异常：{error!r}")
        if not following and self.lyric_chat is not None:
            try:
                raw = await self.lyric_chat(
                    lyrics_line.LYRIC_SYSTEM_PROMPT, line, images=None
                )
                following = lyrics_line.clean_lyric_reply(raw)
                source = source or "模型"
            except Exception as error:  # noqa: BLE001 - 模型失败也不能报错到群里
                log(f"[歌词] 模型接不上：{error!r}")
        if following:
            log(f"[歌词] {line!r} → {following!r}（{source}）")
            await self.sender.text(
                group, following + lyrics_line.LYRIC_SUFFIX, event.msg_id
            )
            return
        log(f"[歌词] 接不上，回兜底：{line!r}")
        await self.sender.text(group, lyrics_line.LYRIC_FALLBACK, event.msg_id)

    def _mentions_me(self, event: Incoming) -> bool:
        """这条消息是不是在 @ 机器人本人（而不是 @ 别人）。"""
        if not event.mention_ids:
            # 没有 ID 信息（自检直接构造的事件）就退回旧判定
            return event.mentioned
        if not self.bot_ids:
            log("[事件] 还没拿到自己的 openid，暂时按「有 @ 就算叫我」处理")
            return event.mentioned
        mine = {value.casefold() for value in self.bot_ids}
        return any(value.casefold() in mine for value in event.mention_ids)

    async def _handle_save_wife(self, command: str, event: Incoming) -> None:
        """保存老婆 / 保存老婆 <名字>：把群里上一张图存进 data/wife。"""
        group = event.group_openid
        name = command[len("保存老婆"):].strip() or None
        if name is not None and not self._valid_name(name):
            await self.sender.text(
                group, "老婆名字不能为空，且不能包含文件路径中的特殊字符", event.msg_id
            )
            return
        image = self.last_images.get(group)
        if image is None:
            await self.sender.text(group, "没有找到上一张图片", event.msg_id)
            return
        saved = await asyncio.to_thread(save_wife_image, self.paths.data, image, name)
        if name is None:
            reply = (
                "哼，连名字都不取吗……行吧行吧，勉强帮你收下了。" if saved
                else "老婆保存失败"
            )
        else:
            reply = (
                f"“{name}”是吧～那以后就是老婆啦，我会好好保管的❤️" if saved
                else "老婆保存失败"
            )
        await self.sender.text(group, reply, event.msg_id)

    async def _handle_wife(self, command: str, event: Incoming) -> None:
        """今日猫娘（随机 @ 一位群友 + 一张老婆图）/ 随机老婆（只发图）。"""
        group = event.group_openid
        if command == "随机老婆":
            path, name = random_wife(self.paths.data)
            if path is None:
                await self.sender.text(group, "老婆文件夹里还没有图片", event.msg_id)
                return
            line = (
                f"这是{event.username}今日的老婆哦❤️" if not name
                else f"{event.username}今日的老婆是{name}哦❤️"
            )
            await self.sender.text(group, line, event.msg_id)
            await self.sender.image(group, path, event.msg_id)
            return

        members = self.roster.members(group)
        if not members:
            await self.sender.text(
                group,
                "群里还没见过几个人呢……等大家说几句话我再抽吧。",
                event.msg_id,
            )
            return
        member_openid, member_name = random.choice(members)
        # 先定人、再取图：抽人失败不该白白吃掉池子里的一张图
        path, name = random_wife(self.paths.data)
        # 普通文本里的 @ 标记在群里会显示成尖括号原文，所以走 markdown 卡片
        card = (
            "# 今日猫娘\n这是今日的猫娘"
            '<qqbot-at-user id="' + member_openid + '" />哦！❤️'
        )
        try:
            await self.sender.markdown(group, card, event.msg_id)
        except Exception as error:  # noqa: BLE001 - 卡片发不出去就退回普通文本
            log(f"[今日猫娘] markdown 发送失败，退回文本：{error!r}")
            await self.sender.text(
                group, f"这是今日的猫娘{member_name or ''}哦！❤️", event.msg_id
            )
        if path is not None:
            await self.sender.image(group, path, event.msg_id)
        log(
            f"[今日猫娘] 人={member_name or member_openid[:8]} "
            f"图={path.name if path is not None else '没有图片'}"
        )

    async def _handle_checkin(self, command: str, event: Incoming) -> None:
        """打卡（记次数）和签到（用光今日抽卡 + 发碎片 + 出签到图）。"""
        group, user = event.group_openid, event.user_openid
        if command == "打卡":
            count = self.attendance.record(group, user)
            await self.sender.text(
                group, f"就这点？才打卡{count}次啊，明天继续。", event.msg_id
            )
            return

        before = int(self.cards.user(user)["shards"])
        drawn = self.cards.draw_all(user)
        names = [item["name"] for item in drawn]
        amount = self.cards.grant_check_in_shards(user)
        total = int(self.cards.user(user)["shards"])
        gained = total - before
        luck = self.luck.today(group, user)
        luck_image = self.luck.image(luck) if luck else None
        wife_path, wife_name = random_wife(self.paths.data)

        lines = [
            f"签到成功，自动抽卡 {len(names)} 次：" + "、".join(names)
            if names else "签到成功，今天的抽卡次数已经用完了。"
        ]
        if amount is not None:
            lines.append(f"奶龙碎片 +{amount}（今日首次签到），现在一共 {total}。")
        else:
            lines.append("今天已经签到过了，碎片每天只有第一次签到才给哦。")
        summary = chr(10).join(lines)

        # 首选原插件那套渲染器（视觉完全一致），失败再退回简版
        if self.checkin_renderer is not None:
            try:
                path = await asyncio.to_thread(
                    self.checkin_renderer.render_check_in_card,
                    username=event.username or "群友",
                    user_id=user,
                    wife_path=wife_path,
                    wife_name=wife_name,
                    drawn=drawn,
                    drawn_count=len(drawn),
                    shard_gain=gained,
                    shard_total=total,
                    first_check_in=amount is not None,
                    luck_name=luck,
                    luck_path=luck_image,
                )
            except Exception as error:  # noqa: BLE001 - 画图失败不能挡着签到
                log(f"[签到] 原版渲染器失败，退回简版：{error!r}")
                path = None
            if path is not None:
                await self.sender.image(group, path, event.msg_id)
                self._drop_rendered(path)
                return

        if card_image is not None:
            try:
                path = await asyncio.to_thread(
                    card_image.render_checkin_card,
                    username=event.username or "群友",
                    drawn=names,
                    shard_gain=gained,
                    shard_total=total,
                    first_check_in=amount is not None,
                    luck_name=luck,
                    luck_path=luck_image,
                    luck_flavor=self.luck.flavor(luck) if luck else "",
                    luck_advice=self.luck.advice(luck) if luck else ("", ""),
                    wife_path=wife_path,
                    wife_name=wife_name,
                    out_dir=self.render_dir,
                )
            except Exception as error:  # noqa: BLE001 - 画图失败不能挡着签到
                log(f"[签到] 画图失败，退回文字：{error!r}")
                path = None
            if path is not None:
                await self.sender.image(group, path, event.msg_id)
                self._drop_rendered(path)
                return
        await self.sender.text(group, summary, event.msg_id)
        if wife_path is not None:
            await self.sender.image(group, wife_path, event.msg_id)

    async def _handle_cards(self, command: str, event: Incoming) -> None:
        """抽卡 / 开箱 / 十连 / 库存。"""
        user = event.user_openid or event.username
        if command == "抽卡":
            reply = self.cards.draw(user)
        elif command == "开箱":
            reply = self.cards.open_box(user)
        elif command == "十连开箱":
            reply = self.cards.open_ten(user)
        else:
            show_all = command == "查看全部库存"
            groups, shards, total, hidden = self.cards.inventory_groups(
                user, show_all=show_all
            )
            image = None
            # 首选原插件那套库存图（和 NapCat 版视觉一致）
            if self.checkin_renderer is not None and groups:
                grouped = [(label, label, color, names) for label, color, names in groups]
                try:
                    image = await asyncio.to_thread(
                        self.checkin_renderer.render_inventory_card,
                        username=event.username or "群友",
                        user_id=user,
                        groups=grouped,
                        shards=shards,
                        total_cards=total,
                        show_all=show_all,
                    )
                except Exception as error:  # noqa: BLE001 - 画图失败还有简版兜底
                    log(f"[库存] 原版渲染失败，退回简版：{error!r}")
                    image = None
            if image is None and card_image is not None and groups:
                try:
                    image = await asyncio.to_thread(
                        card_image.render_inventory_card,
                        groups=groups,
                        shards=shards,
                        total_cards=total,
                        username=event.username or "群友",
                        show_all=show_all,
                        out_dir=self.render_dir,
                    )
                except Exception as error:  # noqa: BLE001 - 画图失败不能挡着库存
                    log(f"[库存] 画图失败，退回文字：{error!r}")
                    image = None
            if image is not None:
                # 原版发完图就结束，不再补「还有 N 种没列」那句
                await self.sender.image(event.group_openid, image, event.msg_id)
                self._drop_rendered(image)
                return
            reply = CardReply(self.cards.inventory_text(user, show_all=show_all))
        await self.sender.text_long(event.group_openid, reply.text, event.msg_id)
        if reply.image is not None:
            await self.sender.image(event.group_openid, reply.image, event.msg_id)

    async def _handle_cs(self, *, results: bool, event: Incoming) -> None:
        """CS2 赛事 / 赛果：查 5EPlay 的 JSON 接口，出 NapCat 同款卡片。

        赛程 / 赛事 / 赛果三张图都用 Pillow 重画（`cs_card.py`）；没装 Pillow
        或画图失败时自动退回文字。接口挂了就回一句人话，不拖死消息链。
        """
        group = event.group_openid
        await self.sender.text(
            group, "正在获取赛果……" if results else "正在获取实时赛程……", event.msg_id
        )
        failed: list[str] = []
        matches: list = []
        events: list = []
        try:
            if results:
                matches = await asyncio.wait_for(
                    self.cs.results_data(), timeout=CS_TIMEOUT * 2 + 5
                )
            else:
                matches, events, failed = await asyncio.wait_for(
                    self.cs.matches_data(), timeout=CS_TIMEOUT * 2 + 5
                )
        except Exception as error:  # noqa: BLE001 - 外部接口，失败也要说人话
            log(f"[CS] {'赛果' if results else '赛程'}查询失败：{error!r}")
            await self.sender.text(
                group,
                "5EPlay 那边没响应（接口偶尔抽风），过一会儿再发一次试试？",
                event.msg_id,
            )
            return

        images: list[Path] = []
        try:
            images = await asyncio.wait_for(
                self._render_cs_cards(results=results, matches=matches, events=events),
                timeout=30,
            )
        except Exception as error:  # noqa: BLE001 - 画图失败还有文字兜底
            log(f"[CS图] 渲染失败，退回文字：{error!r}")
            images = []
        if images:
            for path in images:
                await self.sender.image(group, path, event.msg_id)
                self._drop_rendered(path)
            if failed:
                await self.sender.text(
                    group, f"（{'、'.join(failed)}没拉到，过一会儿再试）", event.msg_id
                )
            return

        text = results_text(matches) if results else brief_text(matches, events)
        if failed:
            text += f"\n（{'、'.join(failed)}没拉到，过一会儿再试）"
        await self.sender.text_long(group, text, event.msg_id)

    async def _render_cs_cards(self, *, results: bool, matches, events) -> list[Path]:
        """渲染赛程 / 赛事 / 赛果卡片；哪张画不出来就跳过，全失败返回空。"""
        if cs_card is None:
            return []
        paths: list[Path] = []
        try:
            if results:
                path = await asyncio.to_thread(
                    cs_card.render_results_card, matches, self.render_dir
                )
                if path is not None:
                    paths.append(path)
            else:
                if matches:
                    path = await asyncio.to_thread(
                        cs_card.render_matches_card, matches, self.render_dir
                    )
                    if path is not None:
                        paths.append(path)
                if events:
                    path = await asyncio.to_thread(
                        cs_card.render_events_card, events, self.render_dir
                    )
                    if path is not None:
                        paths.append(path)
        except Exception:  # noqa: BLE001 - 画到一半失败，清掉半成品让调用方退文字
            for path in paths:
                self._drop_rendered(path)
            raise
        return paths

    async def _reply_ai(self, prompt: str, event: Incoming) -> None:
        """@ 机器人：带上这个人的记忆（和图片）去问 DeepSeek。"""
        group, user = event.group_openid, event.user_openid
        if not prompt and not event.images:
            # 平台会把「图 + @」拆成两条消息，所以没文字也没图时再看一眼刚发的图。
            age = time.time() - self.last_image_at.get(group, 0)
            if not (self.vision_enabled and self.last_images.get(group) is not None
                    and age <= VISION_RECENT_IMAGE_TTL):
                await self.sender.text(
                    group, "哼，@我却不说话，是在逗我玩吗？", event.msg_id
                )
                return
        images = await self._collect_images(event)
        note = ""
        # 实测的真实用法：先发一张图，再单独发「这是什么」或单独 @。这条消息本身没图，
        # 但话里在说图（或干脆没说话），就把群里上一张图附上（原插件 VISION_LAST_IMAGE 的行为）。
        if not images and not event.images and self.vision_enabled:
            last = self.last_images.get(group)
            age = time.time() - self.last_image_at.get(group, 0)
            explicit = bool(prompt) and mentions_image(prompt)
            # 没提"图"时更严格：只认「这是什么」这种指代（或干脆没说话）+ 图刚发不久
            implicit = age <= VISION_RECENT_IMAGE_TTL and (
                not prompt or asks_about_something(prompt)
            )
            if last is not None and (explicit or implicit) and age <= VISION_LAST_IMAGE_TTL:
                images = await self._images_to_blocks([last])
                if images:
                    note = "\n（这条消息没带图，附上的是群里上一张图）"
                    log(f"[识图] 这条没带图，附上一张（{age:.0f}s 前）")
        if not prompt:
            # 只有图：取到了画面就让模型描述，没取到就明说看不到，免得它编
            prompt = (
                "（对方只发了图片，没有配文字）" if images
                else "（对方只发了图片，没有配文字；这张图没取到，你看不到画面）"
            )
        # 只有被 @ 的消息才进画像样本（和原插件的记忆范围一致）
        self.profiles.remember(group, user, event.username, prompt)
        context = self.memory.transcript(group, user)
        self.memory.record(group, user, event.username, prompt)
        system = build_system_prompt(
            load_persona(self.persona_path),
            speaker_name=event.username,
            speaker_profile=self.profiles.summary_of(group, user),
            context=context,
            vision_enabled=self.vision_enabled,
            search_enabled=self.search is not None,
        )
        started = time.monotonic()
        kwargs: dict = {"images": images}
        if self.search is not None:
            kwargs["search"] = self.search
        try:
            reply = await self.chat(system, prompt + note, **kwargs)
        except Exception as error:  # noqa: BLE001 - 单条失败不能拖垮连接
            log(f"[AI] 调用失败：{error!r}")
            reply = "呜……AI暂时走丢了，等我一会儿再试嘛！"
        await self.sender.text_long(group, reply, event.msg_id)
        self.memory.record(group, user, BOT_LABEL, reply, from_bot=True)
        log(f"[AI] 用了 {time.monotonic() - started:.1f}s，回复 {len(reply)} 字")
        # 攒够了就在后台更新画像，不拖慢这次回答
        if self.chat is not None and self.profiles.should_summarize(group, user):
            asyncio.create_task(self.profiles.summarize(group, user, self.chat))

    async def _handle_video(self, command: str, event: Incoming,
                            link: str = "") -> bool:
        """这条消息是在让我看视频吗？是就取文稿、让模型评一评，返回 True。

        触发条件（任一）：正文里带 B站链接；或者正文在说「总结/看看」这类话，
        且这个群最近几分钟刚出现过 B站链接（或一张只有标题的卡片）。
        只认 @ 过的消息 —— 群里别人随手甩个链接也去插嘴，那就成刷屏了。
        """
        if self.video is None or self.chat is None:
            return False
        if not link and not wants_video_comment(command):
            return False
        if not link:
            recent = self.last_video_links.get(event.group_openid)
            if recent and time.time() - recent[1] <= VIDEO_LINK_TTL:
                link = recent[0]
        group, user = event.group_openid, event.user_openid
        # 手机端卡片：没有链接，只有标题 —— 按标题去 B站 搜一个最像的。
        card_title, card_at = self.last_card.get(group, ("", 0.0))
        by_title = (
            not link
            and bool(card_title)
            and time.time() - card_at <= VIDEO_LINK_TTL
            and callable(getattr(self.video, "analyze_by_title", None))
        )
        if not link and not by_title:
            # 卡片里连标题都没捞到：与其让模型说「我看不到视频」，不如说清怎么给。
            if (wants_video_comment(command)
                    and time.time() - card_at <= VIDEO_LINK_TTL):
                await self.sender.text(
                    group,
                    "你刚发的那张卡片我这边只收到标题，链接没跟过来……\n"
                    "在 B站 里点「分享 → 复制链接」，把 https://b23.tv/… 发给我；"
                    "或者直接发 BV 号也行～",
                    event.msg_id,
                )
                return True
            return False

        if by_title:
            await self.sender.text(
                group,
                f"卡片里没带链接，我按标题去 B站 搜一下「{card_title[:16]}」～",
                event.msg_id,
            )
        else:
            await self.sender.text(group, "我看看这个视频，稍等我一下～", event.msg_id)
        started = time.monotonic()
        try:
            if by_title:
                video = await asyncio.wait_for(
                    asyncio.to_thread(self.video.analyze_by_title, card_title),
                    timeout=VIDEO_SUMMARY_TIMEOUT,
                )
            else:
                video = await asyncio.wait_for(
                    asyncio.to_thread(self.video.analyze, link),
                    timeout=VIDEO_SUMMARY_TIMEOUT,
                )
        except asyncio.TimeoutError:
            log(f"[视频] 取文稿超时（{VIDEO_SUMMARY_TIMEOUT:.0f}s）：{link or card_title}")
            await self.sender.text(
                group, "这个视频我半天没打开……等下再发我一次？", event.msg_id
            )
            return True
        except BiliBlocked as error:
            log(f"[视频] {error}：{link or card_title}")
            await self.sender.text(
                group, "B站把我拦下来了（说我看得太快），过几分钟再试试嘛",
                event.msg_id,
            )
            return True
        except Exception as error:  # noqa: BLE001 - 单条失败不能拖垮连接
            log(f"[视频] 取文稿失败：{error!r}")
            await self.sender.text(
                group, "这个视频我没打开，链接是对的吗？", event.msg_id
            )
            return True

        if video is None:
            if by_title:
                await self.sender.text(
                    group,
                    f"按标题在 B站 没搜到像「{card_title[:16]}」的视频……\n"
                    "在 B站 里点「分享 → 复制链接」把链接发我，这样最稳。",
                    event.msg_id,
                )
            else:
                await self.sender.text(
                    group,
                    "这个链接我没认出来……发 bilibili.com/video/BV… 或者 b23.tv 的短链给我？",
                    event.msg_id,
                )
            return True
        # 文稿只覆盖「听得见的声音」，纯音乐/无声演示这类得靠画面补。
        # 放在时长检查之后：明显看不完的长视频就别白抓一遍截图了。
        if video.duration > VIDEO_MAX_MINUTES * 60:
            await self.sender.text(
                group,
                f"这个有{video.duration_text()}，太长了，我看不完……换个短点的？",
                event.msg_id,
            )
            return True
        if self.vision_enabled and VIDEO_FRAMES > 0:
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(self.video.snapshot, video, VIDEO_FRAMES),
                    timeout=max(VIDEO_SUMMARY_TIMEOUT / 2, 8),
                )
            except Exception as error:  # noqa: BLE001 - 抓不到画面不影响文字
                log(f"[视频] 抓画面失败，只发文字：{error!r}")
        if not (video.has_content() or video.desc) and not video.frames:
            await self.sender.text(
                group,
                f"《{video.title}》我只看得到标题，别的什么都抓不到，"
                "这个我就不瞎猜了…",
                event.msg_id,
            )
            return True

        system = build_system_prompt(
            load_persona(self.persona_path),
            speaker_name=event.username,
            speaker_profile=self.profiles.summary_of(group, user),
            context=self.memory.transcript(group, user),
            vision_enabled=self.vision_enabled,
            search_enabled=self.search is not None,
        )
        try:
            reply = await self.chat(
                system,
                review_prompt(video, VIDEO_TRANSCRIPT_LIMIT),
                self._frames_to_blocks(video.frames),
            )
        except Exception as error:  # noqa: BLE001 - 单条失败不能拖垮连接
            log(f"[视频] 模型调用失败：{error!r}")
            reply = "呜……看是看完了，话卡在嘴边说不出来，等会儿再试嘛"
        if by_title:
            # 标题搜出来的完全可能是搬运或同名的另一条，先说清总结的是哪条。
            reply = (
                f"（卡片里没有链接，我按标题搜到的是《{video.title}》，"
                f"UP主 {video.up_name}；要是不是这条你说一声）\n" + reply
            )
            self.last_card.pop(group, None)
        await self.sender.text_long(group, reply, event.msg_id)
        self.memory.record(group, user, event.username, command or link or card_title)
        self.memory.record(group, user, BOT_LABEL, reply, from_bot=True)
        log(
            f"[视频] {video.bvid}《{video.title[:20]}》来源={video.source}，"
            f"文稿 {len(video.text)} 字、截图 {len(video.frames)} 张，"
            f"用了 {time.monotonic() - started:.1f}s"
        )
        return True

    def _frames_to_blocks(self, frames: list[tuple[int, bytes]]) -> list[dict]:
        """把抽出来的画面帧做成内容块。

        和群友发图那条路不同：帧是本地裁好的 JPEG，不用再下载，也不该受
        ``VISION_MAX_IMAGES``（默认 2，是给聊天图片用的）限制，否则视频只剩两张。
        上限另由 ``VIDEO_FRAMES`` 控制，这里再兜一层 8 张，防止把请求撑爆。
        """
        if not self.vision_enabled or not frames:
            return []
        blocks: list[dict] = []
        for _, data in frames[:8]:
            if not data or len(data) > self.vision_max_bytes:
                continue
            blocks.append(make_image_block(data, "image/jpeg"))
        if blocks:
            log(f"[视频] 附加 {len(blocks)} 张画面截图")
        return blocks

    async def _collect_images(self, event: Incoming) -> list[dict]:
        """把这条消息里的图片下载成内容块；失败/超限就跳过，不影响文字回复。"""
        if not self.vision_enabled or not event.images:
            return []
        return await self._images_to_blocks(event.images)

    async def _images_to_blocks(self, images: list[ImageRef]) -> list[dict]:
        blocks: list[dict] = []
        for image in images[: self.vision_max_images]:
            try:
                data = await asyncio.to_thread(fetch_bytes, image.url)
            except Exception as error:  # noqa: BLE001 - 单张失败只丢这张
                log(f"[识图] 下载失败：{error!r}")
                continue
            if not data:
                log("[识图] 下载到空内容")
                continue
            if len(data) > self.vision_max_bytes:
                log(
                    f"[识图] {image.filename} 超过上限"
                    f"（{len(data) / 1024 / 1024:.1f}MB），跳过"
                )
                continue
            mime = guess_mime(data, image.filename, image.content_type)
            blocks.append(make_image_block(data, mime))
            log(f"[识图] 已附加 {image.filename}（{len(data) / 1024:.0f}KB，{mime}）")
        return blocks

    def _strip_leading_name(self, command: str) -> str | None:
        """把正文开头的「@名字 / 机器人名字 + 空格」去掉，返回剩下的命令。"""
        head, separator, rest = command.partition(" ")
        if not separator or not rest.strip():
            return None
        bare = head.lstrip("@＠")
        if head.startswith(("@", "＠")) or bare in self.bot_names:
            return normalize_content(rest)
        return None

    async def _apply_rules(self, command: str, event: Incoming) -> bool:
        handled = False
        if command in self.text_rules:
            await self.sender.text(event.group_openid, self.text_rules[command], event.msg_id)
            handled = True
        if command in self.face_rules:
            # 表情和关键词图共用一个图库（faces/ 已并入 images/）
            path = self.paths.images / self.face_rules[command]
            if path.is_file():
                await self.sender.image(event.group_openid, path, event.msg_id)
                handled = True
            else:
                log(f"[表情] 文件不存在：{path}")
        for keyword, filename in self.image_rules.items():
            if keyword in command:
                path = self.paths.images / filename
                if path.is_file():
                    await self.sender.image(event.group_openid, path, event.msg_id)
                    handled = True
                else:
                    log(f"[图片] 文件不存在：{path}")
                break
        return handled

    # ---- 吊图 ----

    @staticmethod
    def _parse_name(command: str, prefix: str) -> tuple[bool, str | None]:
        """``保存吊图`` → (True, None)；``保存吊图 猫`` → (True, '猫')。"""
        if command == prefix:
            return True, None
        if command.startswith(prefix):
            return True, command[len(prefix):].strip() or None
        return False, None

    @staticmethod
    def _valid_name(name: str | None) -> bool:
        if name is None:
            return True
        invalid = set('\\/:*?"<>|')
        return bool(name) and name not in {".", ".."} and not any(
            ch in invalid or ord(ch) < 32 for ch in name
        )

    async def _handle_save(self, command: str, event: Incoming) -> bool:
        matched, name = self._parse_name(command, "保存吊图")
        if not matched:
            return False
        if not self._valid_name(name):
            await self.sender.text(
                event.group_openid, "吊图名称不能为空，且不能包含文件路径中的特殊字符",
                event.msg_id,
            )
            return True
        image = event.images[0] if event.images else self.last_images.get(event.group_openid)
        if image is None:
            await self.sender.text(event.group_openid, "没有找到上一张图片", event.msg_id)
            return True
        success = await self._download_and_save(image, name)
        if name:
            reply = (
                f"“{name}”是吧～就这个名字？我会好好保管的啦，才不会偷偷扔掉呢～❤️"
                if success else "吊图保存失败"
            )
        else:
            reply = (
                "哼，真是事多……行吧行吧，勉强帮你存好，别再烦我了。"
                if success else "吊图保存失败"
            )
        await self.sender.text(event.group_openid, reply, event.msg_id)
        return True

    async def _download_and_save(self, image: ImageRef, name: str | None) -> bool:
        extension = Path(image.filename).suffix or ".jpg"
        stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1e6) % 1000000:06d}"
        filename = f"{stamp}{extension}" if name else f"diaotu_{stamp}{extension}"
        directory = self.paths.named_diaotu if name else self.paths.diaotu
        path = directory / filename
        try:
            data = await asyncio.to_thread(fetch_bytes, image.url)
            if not data:
                log("[吊图] 下载到空内容")
                return False
            path.write_bytes(data)
        except (OSError, urllib.error.URLError, ValueError) as error:
            log(f"[吊图] 保存失败：{error}")
            return False
        if name:
            self.records[name] = filename
            if not self._save_records():
                self.records.pop(name, None)
                path.unlink(missing_ok=True)
                return False
        log(f"[吊图] 已保存：{path}")
        return True

    async def _handle_send(self, command: str, event: Incoming) -> bool:
        matched, name = self._parse_name(command, "发送吊图")
        if not matched:
            return False
        if not self._valid_name(name):
            await self.sender.text(
                event.group_openid, "吊图名称不能为空，且不能包含文件路径中的特殊字符",
                event.msg_id,
            )
            return True
        if name is None:
            await self.sender.text(
                event.group_openid, "啧……真麻烦啊。喏，就给你这一张，别得寸进尺了。",
                event.msg_id,
            )
            await self._send_random(event)
            return True
        path = self._find_named(name)
        if path is not None:
            await self.sender.image(event.group_openid, path, event.msg_id)
            return True
        # 命名吊图里没有 → 翻卡池（抽卡用的卡面 + 有图的限定卡）
        card_image_path = self.cards.find_card_image(name)
        if card_image_path is not None:
            log(f"[吊图] 「{name}」不在 named_diaotu，改用卡池图：{card_image_path.name}")
            await self.sender.image(event.group_openid, card_image_path, event.msg_id)
            return True
        if name in self.records:
            reply = f"名为“{name}”的吊图文件不存在"
        else:
            reply = f"根本没有什么叫做“{name}”的东西嘛！真是的，可恶！嗯？才、才没有生气呢！"
        await self.sender.text(event.group_openid, reply, event.msg_id)
        return True

    def _find_named(self, name: str) -> Path | None:
        filename = self.records.get(name)
        if filename is None:
            return None
        path = self.paths.named_diaotu / filename
        return path if path.is_file() else None

    async def _send_random(self, event: Incoming) -> None:
        candidates: list[Path] = []
        for directory in (self.paths.diaotu, self.paths.named_diaotu):
            if not directory.is_dir():
                continue
            candidates.extend(
                path for path in directory.iterdir()
                if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
            )
        if not candidates:
            await self.sender.text(
                event.group_openid, "吊图文件夹里还没有图片", event.msg_id
            )
            return
        path = random.choice(candidates)
        await self.sender.image(event.group_openid, path, event.msg_id)
        log(f"[吊图] 随机发送：{path.name}")
