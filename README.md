# QQ 官方机器人（qqchatbot-official）

跑在 QQ 开放平台上的群机器人：入口是 `official_bot.py`，业务代码按层拆在 `qqbot/`。
核心链路（收消息、鉴权、HTTP API、WebSocket）**零第三方依赖**，用系统自带的 Python 就能跑；
只有画图（Pillow）和在线 TTS（edge-tts）是可选依赖。

机器人支持三类能力：

1. **@机器人聊天**：DeepSeek 对话、识图、联网搜索、B站视频总结，带短期记忆和长期记忆库；
2. **群内玩法**：抽卡 / 开箱、CS2 赛事、猜物品、轮盘赌、宠物冒险、锻造、签到、歌词接龙等；
3. **工具**：语音条、吊图存取、功能列表 / 更新日志、每日运势等。

## 目录

- [快速开始](#快速开始)
- [功能地图](#功能地图)
- [功能详解](#功能详解)
  - [AI 与对话](#ai-与对话)
  - [群内玩法](#群内玩法)
  - [工具与杂项](#工具与杂项)
  - [消息发送机制](#消息发送机制)
- [配置与数据](#配置与数据)
- [运行与维护](#运行与维护)
- [排错](#排错)
- [附录](#附录)

---

## 快速开始

### 1. 准备凭据

在 [QQ 开放平台](https://q.qq.com/#/app/bot) 创建或打开机器人，拿到 AppID 和 AppSecret，写入：

```text
config/appid.txt     一行 AppID
config/secret.txt    一行 AppSecret
```

也可以用环境变量 `QQ_BOT_APPID` / `QQ_BOT_SECRET`（优先于文件）。
这两个文件不要提交、不要外发。

需要 AI 对话时再配一把 DeepSeek key：

```text
config/deepseek_api.txt   一行 DeepSeek API key
```

或用环境变量 `DEEPSEEK_API_KEY`。没配的话启动日志会提示「@机器人 不会走 AI」，关键词规则仍然可用。

### 2. 跑自检（不联网）

```bat
cd /d F:\qqchatbot-official
python official_bot.py --selftest
```

输出约 930 项 `ok`（实测 932 项，随分支略有差异），最后一行是「自检全部通过」。
自检使用临时目录，不碰 `data/`。

### 3. 验证凭据

```bat
python official_bot.py --check
```

成功后会打印：

```text
[检查] AppID 1234****abcd 鉴权成功，token ****
[检查] 网关地址：wss://...
```

失败时直接给出原因：`100016` = AppID/Secret 不对，`100007` = 机器人状态异常。

### 4. 正式运行

```bat
python official_bot.py
```

正常启动的日志大致是：

```text
[鉴权] access_token 已刷新，7200s 后过期
[网关] 连接 wss://api.bot.qq.com/websocket/
[网关] Hello，心跳间隔 45s
[网关] 已发送鉴权
[网关] 已就绪，session=xxxxxxxx…
```

也可以双击 `start-official-bot.bat`，详见[运行与维护](#运行与维护)。

### 5. 在群里试

**默认情况下，官方机器人只收得到 @ 它的消息**，所以第一轮测试都用 `@机器人`：

| 发什么 | 应该收到 |
| --- | --- |
| `@机器人 我是奶龙` | 文字「我才是奶龙」+ 奶龙表情图 |
| `@机器人 什么` | 文字「不不不」 |
| `@机器人 气笑了` | 表情图 `qixiaole.jpg` |
| `@机器人 这也太这么强了吧` | 图片 `zhemeqiang.jpg` |
| `@机器人 保存吊图 测试` | 「“测试”是吧～…」 |
| `@机器人 发送吊图 测试` | 刚存的那张 + 「诶～就这张？…」 |
| `@机器人 发送吊图` | 「啧……真麻烦啊…」+ 随机一张 |
| `@机器人 发送吊图 不存在的名字` | 「根本没有什么叫做…」 |

想不 @ 也触发关键词，需要在手机 QQ 群里给机器人打开「接收群内全部消息」（群成员列表 → 点机器人 → 权限设置）。
打开后事件会从 `GROUP_AT_MESSAGE_CREATE` 变成/增加 `GROUP_MESSAGE_CREATE`，代码两种都监听。
全量消息模式下每条群消息都会推过来，日志会变多，但这一版只做规则匹配，不会每条都调 AI。

**@ 的判定**有两个容易踩的点：

- 平台真实 @ 的格式是 `<@union_openid>`，代码会把它剥掉；手打「@机器人 什么」或「机器人 什么」会留下字面量，不算 @。测试请用 QQ 的 @ 选择器点机器人头像。
- 机器人启动时从 `/users/@me` 取自己的 `id` / `union_openid`，只认这两个，不会把「@别人」当成叫自己。

调试原始正文：

```bat
set QQCHATBOT_DEBUG=1
python official_bot.py
```

日志会多出一行 `[调试] 原始正文：...`。

---

## 功能地图

**总原则：命令优先，AI 兜底。** 先匹配命令、关键词、歌词等规则，都没命中且这条是 @ 机器人的，才交给 DeepSeek。
所以 `@机器人 保存吊图 测试` 仍然是存图，不会变成闲聊（这一点和原插件有意不同）。

| 类别 | 触发 | 一句话说明 |
| --- | --- | --- |
| 对话 | `@机器人` + 任意文字 | AI 对话，带人设、群名片、短期记忆和长期记忆库 |
| 对话 | 带图 @机器人 / 先发图再问 | AI 识图，可自动附带群内上一张图 |
| 对话 | 提出需要查证的问题 | AI 自己决定是否联网搜索，最多 3 轮 |
| 对话 | @机器人 + B站链接 | 取平台 AI 文稿 + 画面截图，让人设角色评一评 |
| 素材 | `我是奶龙` / `什么` / `气笑了` / `这么强` … | 关键词回固定文字、表情图、图片 |
| 素材 | `保存吊图 [名字]` / `发送吊图 [名字]` / `保存老婆 [名字]` | 吊图、老婆图的存取 |
| 抽卡 | `抽卡` / `开箱` / `十连开箱` / `查看库存` | 卡牌、保底、银币、库存图 |
| 赛事 | `cs赛事` / `赛果` | 5EPlay 赛程、赛事、赛果卡片 |
| 猜物品 | `弗一把` | Minecraft 物品全群猜谜，简单 / 困难两档 |
| 对枪 | `恶魔轮盘赌` | Buckshot Roulette 按钮面板，单人 / 双人 |
| 养成 | `宠物 冒险` / `剑库` / `养成` / `大挑战` / `兑换` | 8 位面 × 5 层的肉鸽塔 |
| 锻造 | `锻造` / `锻造排行榜` | 选材 → 锻造 → 淬火 → 测试，价值进银币 |
| 日常 | `打卡` / `签到` | 月度打卡、抽完当天次数、银币和运势 |
| 文字 | 以 `~` 结尾的消息 / 同一句连发两次 | 歌词接龙 / 自动复读 +1 |
| 工具 | `语音：内容` | 合成语音条，支持自训音色 |
| 工具 | `功能列表` / `更新日志` | 读 `config/` 下的文本文件 |
| 工具 | `今日猫娘` / `随机老婆` | markdown 卡片 @ 群友并发图 |

---

## 功能详解

### AI 与对话

#### @机器人：AI 对话

需要 `config/deepseek_api.txt` 或 `DEEPSEEK_API_KEY`。

| 能力 | 说明 |
| --- | --- |
| 人设 | `config/persona.txt`，每次请求都重读，改完立刻生效 |
| 群名片 | 把说话人的名字写进提示词，问「我是谁」答的是群名片 |
| 短期记忆 | 本群最近 20 条 @对话，群内共享；每行带群名片，行首 `→` 是当前对话的人；只在内存里，重启清空 |
| 记忆库 | 模型自己判断该记什么，落盘不丢（见下） |
| 群友画像 | 后台按节奏总结「他说话什么风格」，落盘不丢（见下） |
| 长回复 | 超过 800 字按段落切条发 |
| 联网搜索 | 模型自己决定搜不搜，开搜前先发一句提示，答案另发一条 |

实测：

```text
@机器人 你好          → 哼，你好。我在这儿呢…(1.4s)
@机器人 我是谁        → 你是一氧化二氢啊，群名片写得明明白白…(1.8s)
@机器人 我刚才说了啥   → 你刚才先说了句“你好”，然后又问“我是谁”…(2.7s)
@机器人 保存吊图 测试  → 走命令保存，没进 AI
```

#### 记忆库与群友画像

**记忆库**是模型自己写的长期笔记。每次 @ 对话都会给它一个 `remember` 工具，它觉得「以后用得上」就记一条
（身份、喜好、约定、长期项目、查证过的结论），写到 `data/memory_bank_official.json`，重启不丢。

刻意不让它把聊天原话抄进去（工具描述里明确排除一次性闲聊、情绪、临时安排），也不记密码、手机号、住址。
下次对话时，本群记忆按时间顺序塞进提示词的【记忆库】段；和对方现在说的冲突时，以现在说的为准。

`about` 参数决定记在谁名下：默认是当前说话的人，也可以指定别人（名册里查得到才算数，查不到退回记在群里）。文件格式：

```json
{
  "75B8F990…": [
    {"text": "怕辣，不吃香菜", "about": "初春", "about_id": "F28AEA…", "at": 1794490000}
  ]
}
```

**群友画像**是程序在后台按固定节奏总结的风格描述，写进 `data/profiles_official.json`：

1. 每条**被 @ 到的消息**进这个人的样本（普通闲聊不进）；
2. 攒够 `QQCHATBOT_MEMORY_SUMMARIZE_EVERY`（默认 25）条，后台让 DeepSeek 总结成 2~3 句；
3. 之后每次 @ 都把画像塞进提示词。

两次总结之间至少隔 `QQCHATBOT_MEMORY_SUMMARIZE_COOLDOWN`（默认 600 秒），样本池默认 40 条。
画像只增不删，要清就手动删 `data/profiles_official.json` 里那一条。

相关开关见[环境变量速查](#环境变量速查)。两者分工：画像是程序按固定节奏总结的风格，模型看不到过程；
记忆库是模型在对话里主动挑出的事实，写什么由它决定。都按群分开；画像每人一份，记忆库每群一份。

#### AI 识图

图片先下载成 base64 再内联进多模态消息（官方 CDN 链接带时效 token，直接丢给模型容易超时 / 403）。

| 怎么发 | 行为 |
| --- | --- |
| 图 + 文字一起（`@机器人 这是什么` 带图） | 用这条消息里的图 |
| 只发图并 @机器人 | 描述画面 |
| 先发图，再单独问「这是什么」/「这张图呢」 | 自动附上群里上一张图（120s 内） |

显式提到「图 / 截图 / 照片」时，上一张图 600s 内都算；没提图只问「这是什么」时只认 120s 内的。
最多带 2 张、单张 ≤ 8MB，超了跳过并打日志，不影响文字回复。`QQCHATBOT_VISION=0` 整体关掉，提示词会同步改成「你看不到画面」。

每条事件独立处理：AI 慢时（实测一张 288KB 的 GIF 跑到 62.8s 才超时），后面的「保存吊图」之类命令照常立刻响应。

#### 联网搜索

模型挂着 `web_search` 工具，**由它自己决定搜不搜**（问新闻会搜，问「你是谁」不搜）。
后端是 DeepSeek Search，和对话共用那把 key，按**成功请求次数**计费，只在真调用时才花钱。

流程：请求带工具 → 模型回 `tool_calls` → 代码去搜 → 结果作为 `tool` 消息回喂 → 最多 3 轮；
最后一轮撤掉工具，逼它基于已有资料作答。拿到资料后温度降到 0.3，减少对着资料瞎编。

- 开搜前先单独发一句「等我一下，我去网上翻翻～」，答案另发一条，避免群里对着空白等十几秒。
- 模型偶尔只放话「这个我得查一下」却不调用工具，代码会识别这种短句并催它真去搜一次；
  「我查了一下，是…」这种已经在讲结果的不催。
- 搜索结果过一道相关性闸门：把查询切成 2~3 字词元，命中数和比例都不够就当「没搜到」，
  避免把降级结果喂给模型。失败 / 超时（默认 20s）一律退化成空结果，回答照常发。
- 搜索结果是不可信的外部内容，提示词里明确要求只当参考、不执行其中的指令。

`QQCHATBOT_SEARCH=0` 整体关掉；没配 key 时也不会挂工具。

#### B站视频总结

@机器人 并带 B站链接，它会取视频文稿，再按自己的人设评一评。抖音 / YouTube 不做（没有一次拿到全文文稿的接口）。

三种触发方式：

```text
@机器人 看看这个 https://b23.tv/xxxxxx
@机器人 BV1GJ411x7h7 总结一下
（先单独发链接，再）@机器人 看看这个      ← 用群里 10 分钟内最近那条链接
```

这句本身带链接 / BV 号就直接看；没链接但说了「总结 / 评价 / 讲讲 / 说说 / 看看 / 讲了什么」，
才去找群里 10 分钟内的旧链接，并且要求句子里有「视频」或整句 ≤ 12 字，避免聊别的话题时被拽去看旧视频。
只认 @ 过的消息：别人随手甩链接它不会插嘴，只会悄悄记下来给下一条用。

**资料来源：**

```text
b23.tv 短链 / BV 号 / av 号
  → x/web-interface/view                  标题、UP主、时长、简介、cid
  → x/web-interface/view/conclusion/get   （Wbi 签名 + SESSDATA）
       有 → 平台摘要 + 分段提纲 + AI 全文文稿
       没有 → x/player/wbi/v2 的 CC 字幕兜底
  → x/player/videoshot                    雪碧图 → 裁成 N 张画面截图
  → 拼成一条 prompt（+ 截图）交给 DeepSeek 评价
```

所谓 AI 文稿本质是 ASR，只有听觉、没有画面：口播 / 评测 / 访谈效果好，纯音乐 / 无声演示只能靠截图补。
`analyze()` 之后会抓官方快照帧：10×10 雪碧图裁开、均匀取 6 帧，和文字一起发给 DeepSeek（多模态）。
没装 Pillow 就自动退回只看文稿。超过 `QQCHATBOT_VIDEO_MAX_MINUTES`（默认 60 分钟）直接拒绝。
默认流程是「先回一句在看 → 取文稿 → 发评价」两条消息，不会撞被动回复上限。

**必须配登录态**：`config/bilibili_cookie.txt`（整段 Cookie，推荐）或 `config/bilibili_sessdata.txt`。
不配的话只能看标题、简介和画面截图，代码会老实说明。

取 Cookie（**别在 Elements 面板里找，那儿是网页源码**）：

```text
1. 开无痕窗口：Chrome/Edge 按 Ctrl+Shift+N（Firefox 是 Ctrl+Shift+P）
2. 在里面登录 B站（推荐扫码），随便打开一个视频页
3. F12 → 网络 / Network → 刷新页面
4. 点最上面那条 document 请求 → 标头 / Headers → 请求标头里的 cookie: 那一行
5. 右键「复制值」→ 粘进 config/bilibili_cookie.txt（UTF-8）→ 关掉无痕窗口
```

走 Network 而不是「应用 → Cookie」表格，是因为表格 Ctrl+A 只复制已渲染的行，
而 `SESSDATA` 等 HttpOnly Cookie 很容易漏掉；请求头里的 `cookie` 是浏览器实际发出的全量内容。

机器人会自己续期：响应头里换发了新的 SESSDATA 就写回文件；登录态失效时按 B站 web 端流程自动续一次
（需要整段 Cookie，只有 SESSDATA 时缺 `bili_jct` / `ac_time_value`，续不了）。手动验证：

```bat
python -m qqbot.videosum --refresh
python -m qqbot.videosum BV1c5HK6CEPu --frames 0
```

自动续期只能救「服务端还认这份会话」的情况。如果浏览器那边把会话刷掉了，只能重新取。
想一次配置管很久，就用无痕窗口登录取 Cookie，取完直接关掉窗口。
补充 `ac_time_value` 的办法：F12 → 控制台 → `localStorage.getItem('ac_time_value')`，
把返回值（不带引号）另起一行写成 `ac_time_value=那个值` 追加到 cookie 文件。

更多链接解析细节、手机端小程序卡片按标题搜索、以及请求头 / Wbi 签名的坑，见[附录 B](#b-实现细节与历史遗留)。

### 群内玩法

#### 抽卡 / 开箱 / 库存

| 命令 | 规则 |
| --- | --- |
| `抽卡` | 每天 5 次；稀有 45% / 史诗 35% / 神话 15% / 传奇 5%；连续 14 抽没神话第 15 抽必出，连续 29 抽没传奇第 30 抽必出 |
| `开箱` | 花 500 银币：10% 始源卡 / 90% 银币 100-300 |
| `十连开箱` | 5000 银币开 10 个，只回一条汇总 |
| `查看库存` | 画成图：始源 / 限定 / 传奇 / 神话 + 附魔书（如有）+ 银币；`查看全部库存` 连稀有 / 史诗一起列 |

重复卡不叠加，按品质折成银币（稀有 +10 / 史诗 +20 / 神话 +150 / 传奇 +500）；开箱抽到的始源卡重复折 100-300 银币。

数据存在 `data/card_users_official.json`（键是成员的 `member_openid`），和 NapCat 版分开，避免两个进程互相覆盖。
第一次启动会把旧共用文件 `card_users.json` 里键不是纯数字的记录搬过来。

卡池统一在 `data/card/` 下：`rare_card`、`epic_card`、`myth_card`、`legend_card`、`box_card`（始源）、
`limited_card`（限定），每个目录的 `cards.json` 记「卡名 → 文件名」。限定卡不在抽卡池里，但两种库存命令都会列。
代码会跳过没有图文件的卡；当前工作区只拷了 1MB 以下的图，所以部分卡池条目缺图是预期行为。

库存图和签到图都直接用原插件那套渲染器（`napcat_render/checkin_card.py`），5 列网格、品质徽章、顶部头像卡、底部银币卡。
兜底顺序：原版渲染器 → `card_image.py` 简版 → 纯文字。图渲染到系统临时目录，发完即删，`data/` 里不留图。

#### CS2 赛事 / 赛果

| 命令 | 规则 |
| --- | --- |
| `cs赛事`（`赛事` / `cs2赛事` / `csgo赛事`） | 赛程预告（进行中 + 最近 12 场，S/A 级）+ S/A 级赛事列表，两张图 |
| `赛果`（`cs赛果` / `赛事赛果`） | 最近完赛比分，按日期分组，最多 12 场，标胜负 |

数据来自 5EPlay 背后的 JSON 接口（不需要登录、不需要浏览器）：

```text
GET  https://app.5eplay.com/api/tournament/session_list
     game_status=1：进行中 + 未开始；game_status=2：已结束
     grades=1,7,2,3,8,9：和网站赛事页默认勾选一致
POST https://app.5eplay.com/api/csgo/tournament/csgo_event_list_v1
     请求体 {"tournaments_options": {…}}
```

`qqbot/cs_card.py` 按 NapCat 版的三张 HTML 卡片用 Pillow 重画了深色卡、渐变细条、日期 / 赛事标签、队徽、
比分块、状态胶囊、胜方框；队徽从 CDN 现拉并内存缓存，拉不到就画队名首字母。
时间戳按本机时区显示，`TBD vs TBD` 不画；赛事图最多 6 条。
没装 Pillow、字体坏了或画图超时自动退回文字版；接口超时（默认 12s）回一句人话，不会卡死消息链。

#### 弗一把 · Minecraft 物品版

`qqbot/mc_guess.py` + 两套题库：全群一起猜一件 Minecraft 物品，**20 轮全群共享**，猜中记一次胜场进本群榜（不发宠物经验）。

| 命令 | 规则 |
| --- | --- |
| `弗一把`（`mc弗一把` / `再弗一把`） | 回难度面板（简单 / 困难两个按钮），选了才抽题，开局带本群榜 |
| `弗一把 简单模式` / `弗一把 困难模式` | 按钮点击和打字走同一条路，谁唤出面板谁点 |
| 直接发物品名 / `猜 <物品名>` | 算一轮，给六维反馈：名称 / 加入版本 / 类型 / 标签 / 字数 / 生成世界 |
| `弗一把 状态` / `榜单` / `结束` | 看进度 / 看完整榜 / 认输揭晓答案 |

- 题目在 JSON 里，改题不用碰代码：简单 = `config/mc_guess_easy.json`（739 条，1.20.2 截止），
  困难 = 简单 + `config/mc_guess_hard.json`（225 条，扩到 26.3），合计 964 条。
  字段写错、版本 / 类型 / 标签不在词表、权值不是正数，启动或自检时会指出第几条。
- 六维里的「加入版本」带更新主题名（`1.13 水域更新`、`26.1 小鬼当家`），名字写在两份 JSON 的 `version_names`。
- 每道题有 `weight`，概率 = 本题权重 ÷ 全库权重和；楼梯 / 台阶 / 告示牌等同款设 0.3，其余为 1。
- 同一种东西只收一条：七种材质的矛合成「矛」，各种温度的猪牛羊鸡并回「猪 / 牛 / 鸡」，铜方块按氧化 / 涂蜡收成一条。
- 反馈颜色：🟩 完全对上、🟨 沾边、⬜ 不对，⬆️⬇️ 表示答案版本更新 / 更旧；带颜色物品只认后缀（「羊毛」和「红色羊毛」都算中）。
- 第 16 轮提示名字首字、第 18 轮提示末字；冷场三分钟催一句（最多两次，不占轮数）。
- 一局十分钟没人动就散场（重启清空）；榜单落盘 `data/mc_guess_rank.json`。局内其它命令照旧管用。

单独校验题库：`python tools/mc_guess_check.py`（只读，不启动机器人）。

#### 恶魔轮盘赌（按钮面板对枪）

Buckshot Roulette 群聊版：12 号霰弹枪，实弹和空包混着轮流朝自己 / 朝对方开枪。
**朝自己开空包，枪还归你**——这是核心博弈。双方各 5 点电，打到见底结算。全程点按钮。

| 命令 | 行为 |
| --- | --- |
| `恶魔轮盘赌` / `恶魔轮盘` / `轮盘赌` | 开主菜单（第二行是本群榜） |
| `恶魔轮盘赌 @对方` | 发定向挑战帖，只有被 @ 的人能接受 |
| 主菜单「公开挑战」 | 摆一桌，除发起人外谁都能接 |
| `恶魔轮盘赌 榜单` / `排行` | 完整前十 |
| `恶魔轮盘赌 规则` | 玩法 + 九件道具说明 |
| `恶魔轮盘赌 状态` / `结束` / `认输` | 重发面板 / 按弃权结算 |

- 弹匣：第 1 轮 2 实弹 + 1 空包，第 2 轮 3+2，第 3 轮 4+3，第 4 轮起 4+4；顺序随机，只报各剩几发。
- 弹匣打空只补新弹 + 每人补 2 件道具，**血量不回满、手牌不清空**。
- 朝自己开空包不交枪；朝自己开实弹、或朝对方开（不论实弹空包）都交枪。
- 道具模式每轮发 2 件（手牌上限 8，可跨轮攒）；纯赌模式无道具。
- **入场费 100 银币**：道具模式赢返 140、输全赔；纯赌赢返 120、输退 50；超时散桌原路全退。
- 挑战帖 3 分钟有效，模式由接受方选，发起人先手，按钮只签给当前该点的人。
- 榜单按群落盘 `data/devil_roulette_rank.json`（胜场 → 负场 → 最长连胜）；一群同时只有一桌，30 分钟没人动自动散桌。
- 已知取舍：QQ 群没有私聊，放大镜 / 电话看到的情报只能写在公开面板上。

规则和数值口径见 `config/恶魔轮盘赌.txt`。

#### 宠物冒险（位面塔）

把锻造出来的剑交给大肥鱼，爬 **8 位面 × 5 层**的肉鸽位面塔；通关存档后打「哦鲸鲸大挑战」，
结算带回鲸鳞，鲸鳞可在场外兑换启程资金和道具。全程点按钮。

| 命令 | 行为 |
| --- | --- |
| `宠物 冒险` / `冒险面板` | 唤出首页 / 继续没打完的那一趟 |
| `宠物 剑库` / `剑库` | 看剑、换剑、磨刀 |
| `宠物 养成` / `养成` | 花鲸鳞做永久升级 |
| `宠物 挑战` / `大挑战` | 用通关存档挑战三位首领（随机一位） |
| `宠物 兑换` / `鲸鳞兑换` | 用鲸鳞买启程资金 / 道具（进仓库） |
| `宠物 面板` | 原来的宠物面板（吃饭、打工、学习），不受影响 |

锻造收工走 `NewForge(on_forged=self.swords.record_forge)`，剑自动进剑库（银币照旧全额到账，剑是额外留下的）。
数据存在 `data/pet_swords_official.json`，重启不丢；按钮只签给唤出面板的人。
数值与文案见 `config/宠物冒险系统.txt`，引擎是 `qqbot/pet_sword.py`，内容表是 `qqbot/pet_sword_data.py`。

#### 锻造与排行榜

规则写在 `config/新锻造系统.txt`，`qqbot/forge_new.py` 照它实现（改规则请改那个文件）。
四阶段：**选材 → 锻造 → 淬火 → 测试**，发 `锻造` 开出第一块面板，全程点按钮。

| 阶段 | 可选操作 | 说明 |
| --- | --- | --- |
| 选材 | 草钢 140 / 陨铁 280 / 弹簧钢 620 / 强化合金 1288 | 扣银币买料，随机出一种刀型；银币不够直接拒绝 |
| 锻造 | `用力砸` / `回火` / `结束锻造` | 没有次数上限；第 n 锤三项属性各在 ±min(9+n, 15) 内随机，再被塑性整体平移；任一属性掉到 0 立刻报废 |
| 淬火 | `水淬` / `油淬` | 只决定图案模板概率，不动属性；只能淬一次 |
| 测试 | 无需操作 | 三项属性各按正态分布出成绩，给出每项得分、总分和总价值 |

**关键数值：**

- 材料初始属性（强度 / 硬度 / 韧性）：草钢 20/15/15、陨铁 25/30/20、弹簧钢 35/30/45、强化合金 60/55/40。
- 刀型基础价值 B（八种，依次上升）：廓尔喀刀 120、折叠刀 230、骷髅匕首 310、刺刀 390、锯齿爪刀 490、蝴蝶刀 680、爪子刀 920、M9刺刀 1200。越贵的料越容易出好刀。
- 图案倍率 P：12 个基础模板从狩猎网格 0.8 到渐变之色 6.0；4 个特殊模板蓝 / 红 / 绿宝石 10.0、全蓝淬火 15.0。水淬宽而平，油淬高而窄。
- 塑性（0~100）只影响用力砸：期望 `10 × (塑性-50)/50`，并直接平移每锤变化范围（宽度不变）；每砸一锤塑性 -3；`回火` 距上次砸够 5 锤才能用，重摇塑性 `N(55, 15)`，不改变三项属性。
- 磨损度按三项属性占比差异度经正态 CDF 映射成 0~0.80：崭新出厂 ×1.15、略有磨损 ×1.05、久经沙场 ×1.00、破损不堪 ×0.95、战痕累累 ×0.85。
- 测试成绩 ~ `N(属性, 属性/10)`，下限 0、无上限；性能系数 `T = 4.35 × (e^(S'/120) - 1) ÷ (e^2.5 - 1)`，超过 300 分的部分按 35% 折算，避免价值爆炸。
- **总价值 = B × P × T × 材料系数**（四种材料系数都是 1.00），直接加进银币余额；测试 0 分没有保底。
  例如 M9刺刀 + 红宝石 + 270 分 = 39,621 银币。
- **砸得多不等于赚得多**：波动是零和随机游走，砸下去只放大方差、不改期望，属性见底就报废。
  按水 / 油淬各半、2 万次估算：草钢不砸 0.81×、砸 5 锤 1.65×（14% 报废率）；强化合金不砸 1.37×、砸 5 锤 1.18×（2% 报废率）。

每局有一个锻造 id，每发一块面板 `seq` 加一；点旧面板或同一块面板点第二次会提示「这条面板已经用过了」，
按钮只签给开这一局的人。同一个人在群里有未完成的局时拒绝开新局；超过 2 小时没动静再发 `锻造` 直接开新局。
局内进度只在内存里，重启就散。

`锻造排行榜` 把**总价值最高的十次**渲染成图（名次 / 总价值 / 锻造人 / 时间 / 刀型 / 图案 / 测试分数），
渲染失败退回文字。每次测试出分记一条，0 分不记；新记录要严格高于第十名；
落盘 `data/forge_rank.json`，整个机器人一份榜，不分群。

**旧锻造 / 附魔已停用**：`qqbot/forge.py` 那套石剑 / 铁剑 / 钻石剑、`用力砸N`、附魔书代码还在，
但 `qqbot/handler.py` 的 `LEGACY_FORGE_ENABLED` 是 `False`，相关命令完全没反应（也不会掉进 AI 闲聊）。
附魔书自 2026-11-19 起不在开箱奖池里，库存里已有的仍会显示。想恢复就把开关改成 `True`。

#### 打卡 / 签到

| 命令 | 行为 |
| --- | --- |
| `打卡` | 记一次当月打卡，回「就这点？才打卡 N 次啊，明天继续。」 |
| `签到` | 把今天剩下的抽卡次数一次抽完 + 首次签到给 200-400 银币 + 出签到图 |

签到图用 `napcat_render/checkin_card.py`：左边今日老婆 + 底部提示卡，右边自动抽卡结果、银币、今日运势。
渲染失败依次退回 `card_image.py` 简版、纯文字。

运势读 `data/daily_luck/daily_luck.json`，按 **(群, 人, 日期)** 定死，同一天永远是同一档。
打卡记录在 `data/attendance.json`；卡片数据仍写 `data/card_users_official.json`。

#### 歌词接龙与自动复读

**歌词接龙**：以 `~` / `～` 结尾的消息被当成一句歌词，机器人只回下一句（同样带 `~`），不套人设、不加解释。
先查网易云歌词库（`lyrics_line.lookup_next_line`，命中就是确定答案），库里没有才问 DeepSeek（低温度 0.2、只准回一行）。
两条都失败回「哼，这句歌词我没听过，接不上~」。判定排在所有命令最前面（`抽卡~` 会被当歌词），机器人自己的消息不算。

**自动复读 +1**：同一群里，同一条没被任何规则处理的消息连发两次，机器人跟着复读一遍原话。
命令、关键词、歌词、@AI 命中过的都不跟；每个群只记上一条（内存，重启清空）；只认纯文本；
需要开启「接收群内全部消息」，只订阅 @ 消息时不会触发。`QQCHATBOT_REPEAT=0` 关掉。

### 工具与杂项

#### 语音条

发 `语音：你好呀`，机器人把冒号后的内容念成一条语音。`说 你好`、`念 你好` 是同义短写法。
**必须带分隔符**（空格 / `：` / `:` / `，`）——全量消息模式下「说得好」不该被当成命令，这条实测很容易误伤。
不带内容时回用法。总上限 1000 字，单条超过 150 字（约 30 秒）按标点拆成几条连着念。

这是唯一会触发语音的入口：@机器人 的 AI 回复只发文字，不会自动再念一遍。

底层是富媒体上传，只是把 `file_type` 换成 3：

```text
TTS（mp3 / wav）→ POST /v2/groups/{openid}/files  file_type=3
                → POST /v2/groups/{openid}/messages  msg_type=7
```

平台认 silk / mp3 / wav / ogg，不用自己编码 silk，省掉 ffmpeg + pilk。图片和语音共用 `upload_media(file_type)`。

三个引擎（`qqbot/voice.py`），auto 顺序 **gsv → edge → sapi**，前一档失败自动退下一档：

| 引擎 | 说明 |
| --- | --- |
| `gsv` | 本地自训 GPT-SoVITS（默认铃兰，群里可换），48kHz；服务没起来会自动拉起，之后常驻 |
| `edge` | Edge 大声朗读在线接口，`pip install edge-tts` 即可；默认 `zh-CN-XiaoyiNeural` |
| `sapi` | Windows 自带 SAPI（这台机器是 `Microsoft Huihui Desktop`），离线、装机就有 |

固定引擎：`set QQCHATBOT_TTS=gsv`（或 `edge` / `sapi`）。换 edge 音色：`set QQCHATBOT_TTS_VOICE=zh-CN-YunxiNeural`。

**GPT-SoVITS 自训音色**：配置全在环境变量里，默认值就是这台机器的布局。

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `QQCHATBOT_GSV` | 开 | `0` 关掉整个 gsv 引擎 |
| `QQCHATBOT_GSV_DIR` | `F://GPTSoVITS` | 整合包根目录（要有 `api_v2.py`） |
| `QQCHATBOT_GSV_PYTHON` | miniconda3 环境里的 python | 跑 api 的 python（要装好 torch） |
| `QQCHATBOT_GSV_PORT` | `9880` | 服务端口（只监听 127.0.0.1） |
| `QQCHATBOT_GSV_GPT_WEIGHTS` / `_SOVITS_WEIGHTS` | 铃兰的权重 | 相对整合包目录 |
| `QQCHATBOT_GSV_REF_AUDIO` / `_REF_TEXT` | 铃兰的参考音频 / 台本 | 台本必须逐字对得上 |
| `QQCHATBOT_GSV_MODELS_DIR` | `models/我的模型` | 可切换的音色目录，一个子目录一个角色 |
| `QQCHATBOT_GSV_ROLE` | `铃兰` | 没在群里换过时用哪个 |
| `QQCHATBOT_GSV_MODEL_STATE` | `data/voice_model.json` | 群里换过的音色记在这，删掉回默认 |
| `QQCHATBOT_VOICE_SWITCH_ANYONE` | 开 | 谁能在群里换嗓子；`0` 只认白名单 |
| `QQCHATBOT_VOICE_SWITCH_ALLOW` | 空 | 允许换嗓子的 openid，逗号分隔 |
| `QQCHATBOT_VOICE_SWITCH_COOLDOWN` | `60` | 两次切换至少隔多少秒（换一次要重载 40 秒） |
| `QQCHATBOT_GSV_STEPS` / `_SPEED` / `_TIMEOUT` | `16` / `1.0` / `300` | 采样步数 / 语速 / 合成超时（秒） |
| `QQCHATBOT_GSV_PREWARM` | 开 | 启动 bot 时就把服务拉起来 |

群里换音色：

```text
语音模型            → 看有哪些角色、现在是哪个
语音模型 凯尔希      → 换过去
换语音 铃           → 打半个名字也认
```

`models/我的模型/` 自带四个角色：**铃兰**（默认）、**能天使**、**凯尔希**、**羽毛笔**；
新角色建目录丢进去就行，要求有 `*SoVITS*.pth`、`*.ckpt`、`参考音频.wav`、`参考文本.txt`，缺一样会被跳过。
换嗓子只是记一笔状态，**真正的模型重载发生在下一条语音**（要等 30~40 秒）。切换是全局的，不按群。
4060 Laptop 上 27 字：32 步约 8s、16 步约 2.7s、8 步约 1.9s；模型常驻约 4.5~5GB 显存。
更多实现坑见[附录 B](#b-实现细节与历史遗留)。

先验语音通路，不用等群里发：

```bat
python -m qqbot.voice --voices                       :: 列引擎和可选音色
python -m qqbot.voice 你好呀，我是奶龙。              :: 合成一条到 ./voice-preview.mp3
python -m qqbot.voice 你好呀 --engine sapi           :: 只用离线音色
```

要念的文本会先洗掉 @ 标记、URL、markdown 符号、表情；中文文本写进临时 UTF-8 文件再传路径
（Windows 命令行直接传中文会被代码页啃成问号）。音频合成到系统临时目录，发完即删。
合成失败会说「呜……这条我念不出来，换短一点的话试试？」，原因写日志。

#### 功能列表 / 更新日志

| 命令 | 读哪个文件 | 说明 |
| --- | --- | --- |
| `功能列表` | `config/help.txt` | 功能说明，自己维护 |
| `更新日志` | `config/changelog.txt` | 版本日志，自己维护 |

两条都是只读文件，每次重读，改完立刻生效。正文按 `QQCHATBOT_CHANGELOG_CHARS`（默认 1500 字）切片，
最多 8 条，超出补一句「后面的太长了」；切法字符级无损，优先在换行处断开。
文件不在 / 为空时有兜底文案。

#### 今日猫娘 / 随机老婆

| 命令 | 行为 |
| --- | --- |
| `今日猫娘` | 随机挑一位**见过的**群友，发 markdown 卡片：`# 今日猫娘` + 「这是今日的猫娘 @某某 哦！❤️」+ 一张老婆图 |
| `随机老婆` | 「XXX 今日的老婆是 XX 哦❤️」+ 一张老婆图 |

两个实现要点：@ 必须走 markdown 卡片（`msg_type=2`），普通文本里的 `<qqbot-at-user …/>` 会原样显示；
平台没有群成员列表接口（11253 无权限），所以名册只收「见过的人」，按群攒进 `data/members_official.json`。

### 消息发送机制

- **超过 5MB 的图自动分片上传**（二进制直传硬上限 5MB，图片软限制 20MB）：
  `upload_prepare`（md5 / sha1 / md5_10m）→ 逐片 PUT 预签名 URL → `upload_part_finish` → 带 `upload_id` 调 files 合并。
  实测 7.68MB 的图全程约 7 秒。
- **长数字自动千分位**：出群文本里 6 位以上连续数字每三位加逗号（`1234567` → `1,234,567`），
  URL、CQ 码、小数位、版本号跳过不动。这是原插件为防 QQ 风控做的，所有发送统一过一遍。
- **长回复自动分条**：超过 800 字按段落切；被动回复 `msg_seq` 自增，回满 5 条自动转主动消息（受群主开关限制）。
- **事件去重**：平台会重推同一条消息，按 `msg_id` 去重，日志里的 `[事件] 跳过重复消息` 是正常的。
- **每条事件独立处理**：AI 慢不会阻塞其它命令。

---

## 配置与数据

按「**会不会变**」分成两个目录：`config/` 是静态配置和凭据（你会手动编辑），`data/` 是运行时数据（程序自己写）。
`config_file()`（`qqbot/config.py`）按「`config/` 优先 → `data/` 兜底」查找，把文件挪回 `data/` 也照样能用。

### 配置文件（config/）

```text
config/
  appid.txt                AppID
  secret.txt               AppSecret
  deepseek_api.txt         DeepSeek key（对话 + 联网搜索共用）
  search_api.txt           旧版博查 / Tavily 的 key，现在没用到
  bilibili_cookie.txt      B站登录态（整段 Cookie，推荐）
  bilibili_sessdata.txt    B站登录态（只存一个 SESSDATA 的备用写法）
  persona.txt              人设（每次请求都重读）
  help.txt                 「功能列表」的正文
  changelog.txt            「更新日志」的正文
  新锻造系统.txt            新锻造规则说明（写给人看，代码照它实现）
  锻造系统.txt              旧锻造规则说明（入口已关，代码保留）
  恶魔轮盘赌.txt            轮盘赌规则与数值
  宠物冒险系统.txt          宠物冒险规则与数值
  mc_guess_easy.json       弗一把简单题库
  mc_guess_hard.json       弗一把困难题库
```

各文件的格式和注意事项见 [`config/README.md`](config/README.md)。

### 数据文件（data/）

```text
data/
  card_users_official.json  抽卡记录（openid → 卡 / 银币 / 次数）
  memory_bank_official.json 记忆库
  profiles_official.json    群友画像
  members_official.json     见过的群成员名册
  attendance.json           打卡记录
  forge_rank.json           锻造排行榜（全机器人一份）
  mc_guess_rank.json        弗一把本群榜
  devil_roulette_rank.json  轮盘赌本群榜
  pet_swords_official.json  剑库 / 存档 / 鲸鳞 / 仓库
  pets_official.json        宠物面板数据（吃饭 / 打工 / 学习）
  voice_model.json          群里换过的音色
  official_rules.json       自定义规则（见下）
  diaotu/                   无名吊图
  named_diaotu/             命名吊图 + records.json
  images/                   图库：关键词图 + 表情图（原先的 faces/ 已并入）
  card/                     卡池：rare_card / epic_card / myth_card / legend_card / box_card / limited_card
  wife/ / situation/        老婆图 / 场景图素材
  gsv/                      GPT-SoVITS 的 tts_infer.yaml 与试听音频
  daily_luck/daily_luck.json 运势等级 → 图片文件名
```

生成的签到图 / 库存图 / 语音 / TTS 音频都是临时文件，放在系统临时目录，发完即删，
`data/checkin/` 是历史遗留的空目录，不会留下新生成的图。

### 环境变量速查

| 环境变量 | 作用 |
| --- | --- |
| `QQ_BOT_APPID` / `QQ_BOT_SECRET` | 凭据（优先于文件） |
| `QQCHATBOT_DATA_DIR` | 换数据目录（运行时记录、图片） |
| `QQCHATBOT_CONFIG_DIR` | 换配置目录，默认 `config/` |
| `QQ_BOT_API_BASE` | 换 API 域名，默认 `https://api.bot.qq.com` |
| `QQCHATBOT_DEBUG` | `1/true/yes/on` 时打印收到的原始正文 |
| `QQCHATBOT_KEEP_AWAKE` | `0` 关掉防睡眠，默认开 |
| `DEEPSEEK_API_KEY` | 优先于 `config/deepseek_api.txt` |
| `DEEPSEEK_API_URL` / `DEEPSEEK_MODEL` | 换端点 / 模型，默认 `api.deepseek.com` + `deepseek-flash` |
| `QQCHATBOT_MAX_TOKENS` / `QQCHATBOT_AI_TIMEOUT` | 回复上限（1500）/ 超时（60s） |
| `QQCHATBOT_MEMORY_RECENT` / `QQCHATBOT_MEMORY_CHARS` | 每群记忆条数（20）/ 注入提示词字数（1200） |
| `QQCHATBOT_MEMORY_BANK` | `0/false/no/off` 关掉记忆库，默认开 |
| `QQCHATBOT_MEMORY_BANK_MAX` / `_NOTE` / `_CONTEXT` | 每群条数（200）/ 单条字数（200）/ 注入字数（1500） |
| `QQCHATBOT_MEMORY_SUMMARIZE_EVERY` / `_COOLDOWN` / `QQCHATBOT_MEMORY_SAMPLES` | 画像总结门槛（25）/ 冷却（600s）/ 样本池（40） |
| `QQCHATBOT_REPLY_CHUNK` | 长回复分条阈值，默认 800 字 |
| `QQCHATBOT_REPEAT` | 关掉自动复读，默认开 |
| `QQCHATBOT_AI_THINKING` | `enabled` / `disabled`，默认 disabled（更快） |
| `QQCHATBOT_LYRIC` / `_LYRIC_LIBRARY` | 关掉歌词接龙 / 只留模型兜底，默认都开 |
| `QQCHATBOT_LYRIC_SUFFIX` / `_FALLBACK` | 歌词标记 / 兜底文案 |
| `QQCHATBOT_VISION` | 关掉识图，默认开 |
| `QQCHATBOT_VISION_MAX_IMAGES` / `_MAX_MB` | 最多几张（2）/ 单张上限 MB（8） |
| `QQCHATBOT_VISION_DETAIL` | `low/high/original/auto`，默认 auto |
| `QQCHATBOT_VISION_LAST_IMAGE_TTL` / `_RECENT_IMAGE_TTL` | 上一张图多久内还算数（600s）/ 没提图时（120s） |
| `QQCHATBOT_SEARCH` | 关掉联网搜索，默认开 |
| `DEEPSEEK_SEARCH_URL` | 默认 `api.deepseek.com/v1/tools/search` |
| `QQCHATBOT_SEARCH_ROUNDS` | 最多搜几轮，默认 3 |
| `QQCHATBOT_SEARCH_RESULTS` / `_SNIPPET` | 每次几条（5）/ 每条摘要字数（600） |
| `QQCHATBOT_SEARCH_TIMEOUT` / `_MIN_SCORE` | 超时（20s）/ 相关性阈值（0.25） |
| `QQCHATBOT_SEARCH_CONTEXT` | 搜索结果回喂总字数上限（4000） |
| `QQCHATBOT_VIDEO` | 关掉 B站视频总结，默认开 |
| `BILIBILI_COOKIE` / `BILIBILI_SESSDATA` | 优先于 `config/` 下同名文件 |
| `QQCHATBOT_VIDEO_MAX_MINUTES` / `_TRANSCRIPT` | 超过多少分钟不看（60）/ 文稿截多少字（6000） |
| `QQCHATBOT_VIDEO_FRAMES` | 额外抓几张画面截图（6，0 关掉；需 Pillow） |
| `QQCHATBOT_VIDEO_TIMEOUT` / `_LINK_TTL` | 取文稿超时（25s）/ 旧链接有效期（600s） |
| `QQCHATBOT_VIDEO_TITLE_MATCH` | 按标题搜时的相似度门槛（0.55） |
| `QQCHATBOT_NUMBER_SEPARATOR` / `_MIN_DIGITS` | 千分位开关 / 起始位数（6），默认开 |
| `QQCHATBOT_VOICE` | 关掉语音条，默认开 |
| `QQCHATBOT_TTS` | `auto`（gsv → edge → sapi）/ `gsv` / `edge` / `sapi` |
| `QQCHATBOT_GSV*` | 本地 GPT-SoVITS 的一整套配置，见[语音条](#语音条) |
| `QQCHATBOT_TTS_VOICE` | edge 音色，默认 `zh-CN-XiaoyiNeural` |
| `QQCHATBOT_TTS_SAPI_VOICE` | SAPI 音色，默认 `Microsoft Huihui Desktop` |
| `QQCHATBOT_TTS_RATE` / `_PITCH` | 语速（`+20%`）/ 音调（`+8Hz`）；SAPI 把百分比折成 -10~10 |
| `QQCHATBOT_VOICE_MAX_CHARS` / `_CHUNK_CHARS` | 总上限（1000）/ 单条上限（150） |
| `QQCHATBOT_VOICE_TIMEOUT` | 合成超时（40s） |

### 自定义规则

不想改代码就新建 `data/official_rules.json`：

```json
{
  "text":  { "早上好": "早上好呀" },
  "face":  { "无语": "yiwuyan.jpg" },
  "image": { "好家伙": "zhemeqiang.jpg" }
}
```

---

## 运行与维护

### 启动方式

| 方式 | 做法 | 说明 |
| --- | --- | --- |
| 双击 | `start-official-bot.bat` | 开控制台窗口跑，日志同时追加到 `logs/bot.log`；关窗口就停 |
| 开机自启 | `Win+R` → `shell:startup`，放入 bat 的**快捷方式** | 登录后自动开窗口 |
| 后台无窗口 | 任务计划程序：触发器「登录时」+ 操作「启动程序」指向 bat | 选「只在用户登录时运行」 |

- **同时只能跑一个**：两个进程连同一个机器人会抢事件，并且都整份写 `data/`，后写的盖掉先写的。
- 停：窗口里 `Ctrl+C`，或直接关窗口。
- 换数据目录 / 凭据后重启即可；人设 `persona.txt` 不用重启，每次请求都重读。

### 自检

```bat
python official_bot.py --selftest
```

离线、用临时目录、不碰 `data/`，约 930 项检查（实测 932 项）。题库改动也可以单独校验：

```bat
python tools/mc_guess_check.py
python -m qqbot.videosum --refresh
```

### 防止电脑睡眠

**休眠状态跑不了任何程序**，这里做的是「不让电脑睡」。启动时 `keep_awake()` 调 Windows 的 `SetThreadExecutionState`：

```text
ES_CONTINUOUS | ES_SYSTEM_REQUIRED   ← 系统保持唤醒
（故意不加 ES_DISPLAY_REQUIRED）     ← 屏幕照样可以关，省电
```

进程活着就生效，退出时自动解除；标准库 `ctypes` 实现，不装任何东西。启动日志会有：

```text
[电源] 已请求阻止系统睡眠（显示器仍可关闭；要关掉设 QQCHATBOT_KEEP_AWAKE=0）
```

还是睡了，按这个顺序查：

| 场景 | 处理 |
| --- | --- |
| 笔记本合盖 | 控制面板 → 电源选项 → 关闭盖子的功能 → 接电源 / 用电池都改成「不采取任何操作」 |
| 现代待机 | 管理员 PowerShell：`powercfg /requestsoverride PROCESS python.exe SYSTEM` |
| 干脆关睡眠 | 管理员 PowerShell：`powercfg /change standby-timeout-ac 0`（电池把 `-ac` 换 `-dc`） |
| 关机 / 注销 / 断网 | 软件层无解；要常驻建议用小主机或云服务器 |

睡眠期间机器人是**离线**的：QQ 会把消息留在服务端，醒来后能补收到一部分，但别指望一条不落。

---

## 排错

### 启动与凭据

| 现象 | 原因 / 处理 |
| --- | --- |
| `取 access_token 失败：{'code': 100016 ...}` | AppID / Secret 写错 |
| `取 access_token 失败：{'code': 100007 ...}` | 机器人被封禁 / 已删除 |
| 启动后一条事件都没有 | 群里没 @ 它；或没开「接收全部消息」 |
| `保存吊图` 报 `[Errno 13] Permission denied` | 工作区子目录没有写权限；给 `data/` 恢复权限或用完全权限运行 |
| 手打「@机器人 什么」没反应 | 手打不是真 @；用 QQ 的 @ 选择器点机器人头像 |
| 日志 `[事件] 跳过重复消息` | 正常，平台重推，已按 `msg_id` 去重 |

### 消息与 AI

| 现象 | 原因 / 处理 |
| --- | --- |
| 启动日志「没配 config/deepseek_api.txt」 | 没有 key，@机器人 只走关键词规则 |
| 回复「呜……AI暂时走丢了」 | 看日志 `[AI] 调用失败` 的真实原因 |
| 只回一句「我去搜搜」就没下文 | 开搜前提示和答案是两条消息；若确实断了，查 `[搜索] 模型只说不搜`（只催一次，还这样就追问一句） |
| 搜完只发提示没有答案 | 答案那步失败（看 `[AI] 调用失败`）；同条消息最多 5 条被动回复，长答案切太多条可能被限流 |
| 机器人记不住刚才聊的 | 短期记忆只在内存里，重启清空，且只装**被 @ 到的对话** |
| AI 把别人的话当成他说的 | 记忆群内共享，靠群名片和行首 `→` 区分；同名群名片改个不重名的 |
| AI 记错了 / 记了不该记的 | 改 `data/memory_bank_official.json` 删掉那条；或设 `QQCHATBOT_MEMORY_BANK=0` |
| 记忆库好像没生效 | 看日志有没有 `[记忆库]`；写进去了但没进提示词，多半被 `_CONTEXT` 字数上限挤掉 |
| @ 别人时机器人也搭话 | 2026-10-20 已修：只认启动时从 `/users/@me` 取到的 id / union_openid |
| 发出去的 @ 显示成 `<qqbot-at-user …/>` 原文 | 要 markdown 卡片（`msg_type=2`），普通文本不解析 |
| 「今日猫娘」说群里还没见过人 | 名册只记见过的发言人，等大家说几句话 |

### 图片与语音

| 现象 | 原因 / 处理 |
| --- | --- |
| 发图片失败 `850019` | 图片格式不被接受（只认 png/jpg/gif/webp/bmp） |
| 大图报 `850031 上传文件超过大小限制` | 超过 200MB 硬限制；图片软限制 20MB，超了会降级成文件 |
| 分片报 `40093001 文件上传失败，请重试` | 分片通道偶发异常，重试一次通常就过 |
| 问图时说「没看到图片」 | 图单独发且超过 120s（或没提「图」）；重发一张再问 |
| 日志 `[识图] 下载失败` | CDN 链接过期 / 网络不通，这条按纯文字处理 |
| 问图卡 60s 后回「AI 走丢」 | 动图 / 大图让模型超时；换 jpg/png 或调大 `QQCHATBOT_AI_TIMEOUT` |
| `语音：…` 回「念不出来」 | 看 `[语音] 合成失败`：gsv 服务没起来查 `QQCHATBOT_GSV_DIR` / `_PYTHON`（日志在 `%TEMP%\qqchatbot-gsv.log`）；edge 没装就 `pip install edge-tts`；sapi 没有 PowerShell 就检查 PATH |
| 语音是机械音 | 正在用离线 SAPI；装 edge-tts 会自动切到自然音 |
| `语音：你好` 没反应 | 命令必须带分隔符（空格 / `：` / `:`）；「说得好」这类不会被当成命令 |
| 语音发成文件卡片不是语音条 | `file_type` 要传 3；平台认 silk / mp3 / wav / ogg |

### B站视频总结

| 现象 | 原因 / 处理 |
| --- | --- |
| 说「只看到标题和简介」 | `没配 SESSDATA` 或 `SESSDATA 被拒（-101）`；后者要重新取一次 |
| 日志「读到 N 个 cookie 但没有 SESSDATA」 | 从「应用 → Cookie」表格复制漏了 HttpOnly 行；改从 Network 的 document 请求头复制 |
| 没退出登录，cookie 一会儿就失效 | SESSDATA 随浏览器访问滚动刷新；用整段 Cookie + 无痕窗口取，取完关窗 |
| `--refresh` 报「续期页面没给 refresh_csrf」 | 会话彻底作废，只能重新取 cookie |
| 有内容的视频却只有标题 | 视频没开 AI 摘要且无 CC 字幕；看日志确认，不是配置问题 |
| 说「B站把我拦下来了」 | 412 风控，通常请求太密或 IP 被盯，等几分钟 |
| 说「链接我没认出来」 | 只认 `bilibili.com/video/BV…`、`b23.tv/…`、`bili2233.cn/…`、`BV…`、`av…`；检查日志有没有旧的裸 BV 误判（已修） |
| 聊别的话题却被拽去总结旧视频 | 复用了 10 分钟内的旧链接；现在要求句子里有「视频」或整句 ≤12 字，还嫌松就调小 `QQCHATBOT_VIDEO_LINK_TTL` |
| 手机分享总结不了 | 看日志有没有 `卡片链接=…`：有是解析问题；没有再看下一条 |
| 日志 `[卡片消息] 小程序 … source: 哔哩哔哩` | 平台把卡片转成了纯文字，没有链接；现在按 `title` 去 B站 搜，搜不到让人重发链接 |
| 按标题搜出来的不是同一条 | 系列视频 `①②③` 或搬运太多；调 `QQCHATBOT_VIDEO_TITLE_MATCH`，或直接发链接 |
| 日志「空正文且没解析出链接」 | 卡片里没有 URL；让用户用「B站 → 分享 → 复制链接」 |

---

## 附录

### A. 工程结构与依赖关系

```text
official_bot.py          入口：CLI / 凭据 / 启动
qqbot/
  config.py              路径、环境变量、人设 / 记忆 / 搜索规则参数
  base.py                日志、事件解析、文本 / HTTP / 图片工具、人设与短期记忆
  ai.py                  DeepSeek 对话 + 联网搜索 + 记忆库工具
  api.py                 QQ 开放平台 HTTP API、分片上传、发送器
  cards.py               抽卡 / 开箱 / 库存
  cs.py / cs_card.py     CS2 取数与卡片渲染
  videosum.py            B站视频文稿、截图与标题搜索
  forge_new.py / forge_rank.py      新锻造 / 排行榜
  forge.py                          旧锻造 / 附魔（入口已关，代码保留）
  mc_guess.py / mc_guess_data*.py   弗一把
  devil_roulette*.py                恶魔轮盘赌
  pet_sword.py / pet_sword_data.py  宠物冒险
  pet.py / pet_card.py              宠物面板 / 卡片
  panel.py                          按钮面板工具
  handler.py                        群消息业务处理
  net.py                            WebSocket / 网关事件循环
  voice.py                          语音合成（gsv / edge / sapi）
  features.py                       功能列表、画像、名单、打卡、运势、老婆图
  selftest.py                       离线自检
card_image.py            库存图 + 简版签到图（Pillow，可选）
napcat_render/           原版签到图渲染器的副本 + 替身 config / wife
start-official-bot.bat   双击启动
logs/                    bot.log / console.log
```

依赖方向是单向的：`config` ← `base` ← `ai` / `api` / `cards` / `cs` / `features` / `forge` / `voice` ← `handler`；
`net` 只用 `base`，入口用 `handler` + `net`。各模块沿用了 `from .base import *` 以保持和单文件时行为一致，
以后要收窄依赖就换成显式导入。

### B. 实现细节与历史遗留

**B站链接解析**：

- 短链是 302，先跟到最终地址再取 BV 号；最终地址没有就翻落地页 HTML，只认 `/video/BV…`、`bvid=` 这类明确写法。
- 手机端分享文案 `【标题-哔哩哔哩】 https://b23.tv/xxxx`、短链后粘中文、缺协议头、`bili2233.cn`、
  双重序列化（`https:\\/\\/b23.tv\\/…`）、urlencode 整条链接都能认。
- 小程序卡片只有 QQ 中转页 `m.q.qq.com/a/s/…` 时跟一次再找视频地址（只在同时出现「哔哩哔哩」时才认）；
  QQ 自己的 `url.cn` / `t.cn` 同理。
- 事件 JSON 里的裸 `BV…` 只在同时出现「哔哩哔哩 / bilibili / b23.tv」时才认——不加这条，
  某个随机字段凑巧挨出 `BV`+10 位就会劫持后面的「总结」（实测踩过，报 `code=-400`）。
- 手机端卡片连链接都没有时（平台转成一段纯文字），从 `title` 去 `x/web-interface/wbi/search/type` 搜
  （要登录态、走 Wbi 签名），按相似度挑最像的，低于 `QQCHATBOT_VIDEO_TITLE_MATCH` 放弃。
  先带序号（`某某②`）搜，分数不够 0.95 再去掉 `①②③` 搜一轮；打分都用带序号版本，避免 `②` 被 `③` 抢走。
- 请求头必须带浏览器 UA + `Referer: https://www.bilibili.com/video/<bvid>`，否则 412；
  `w_rid` 要现算（nav 取 img_key / sub_key → 混淆表重排 → md5(参数 + mixin_key)），密钥轮换所以只缓存 5 分钟；
  字幕一律走签名版 `player/wbi/v2`，不签名时风控会返回**别的视频**的字幕。
- 分享卡片链接埋在事件 JSON 里，`parse_group_event` 会顺手捞 `Incoming.attached_url`，
  所以「转发卡片 → 再 @」也认。

**GPT-SoVITS**：

- 换权重要重启服务，不能用 `/set_*_weights`：SoVITS 是 v4 底模 + LoRA，运行接口会回 `success` 但音色其实没换。
  现在启动前把权重写进 `data/gsv/tts_infer.yaml` 的 `custom` 段，用 `api_v2.py -c` 启动时加载；
  再用 `%TEMP%\qqchatbot-gsv.stamp` 记当前加载的是哪两个文件，配置变了才杀掉旧服务重开。
- 改 yaml 只动路径：`is_half: true` 是 YAML 布尔，写成 `"true"` 会一半 fp16 一半 fp32，合成崩。
- 本地服务请求必须绕开系统代理（`ProxyHandler({})`），否则 127.0.0.1 走代理报 502；
  `ref_audio_path` 要用正斜杠，反斜杠会被拒。
- 想让一次配置管很久，用无痕窗口登录取 Cookie，取完关窗——别的端不再刷新这套会话，机器人就能一直用、自己续。
- `parse_cookie()` 认 `cookie:` 前缀、分号分隔、多行、带引号、只有值，以及 Network「复制为 cURL」的整条命令。
  不要手动把 `%2C` 解码成逗号，浏览器存的就是编码形式。

**历史遗留**：

- 2026-10-20 清掉了 NapCat 插件的 18 个 `.py`、`README.md` 和 `tests/`，这个工作区只跑官方版。
  原件仍在 `F:/NapCat Desktop/apps/plugins/qqchatbot`，需要查旧实现时去那边看。
  `napcat_render/` 名字带 napcat 是因为它是原版渲染器的副本，签到图直接用它。
- `data/` 里还留着 NapCat 时期的东西（`card_users.json` 的 9 个 QQ 号记录、`config/changelog.txt`、
  `help.txt`、`锻造系统.txt`、`新锻造系统.txt`、`search_api.txt`、`bot_qq.txt`、`forge_rank.json`）。
  它们是素材不是代码；`search_api.txt` 目前没用上，联网搜索走 DeepSeek。
- `faces/` 已并入 `images/`：两者在代码里都是「关键词 → 一个图片文件」，合并后不会出现图放错文件夹就不生效。
- 从原目录只拷了 1MB 以下的小文件，部分卡池条目和大吊图缺图是预期行为，代码会跳过或提示文件不存在。

### C. 与原插件的差异

- 原插件 @ 一律走 AI；本版**命令优先**，`@机器人 保存吊图` 仍然存图。
- 原插件识别手打的「@机器人名字」；本版只认平台的真 @（`<@openid>`）和启动时的机器人 username。
- 原插件 `保存吊图` 没图时回「没有找到上一张图片」，本版一致；`发送吊图 名字` 也是两级回退：
  先 `named_diaotu`，再翻全部卡池（含限定卡）。
- 原插件所有文案过千分位（`textfmt.py`），本版统一过 `format_numbers`。
- 锻造重做过一轮：旧版（石剑 / 铁剑 / 钻石剑 + 附魔书）代码留在 `forge.py` 但入口关了，
  当前入口是 `config/新锻造系统.txt` + `qqbot/forge_new.py`；排行榜兼容旧 `forge_rank.json`，新记录存 openid。
- 联网搜索已补上（DeepSeek Search，key 与对话共用）；歌词补救轮那套搜索没搬（歌词先查网易云库，查不到问模型）。
- 短期记忆群内共享（最近 20 条，内存）+ 长期画像按人（落盘）+ 记忆库按群（模型自己写，落盘）。
- 识图没有「描述里带上 @人」这种附加能力，只做看图说话。

### D. 下一步

1. 抽 `platform.py` 共用层，让 NapCat 版和官方版共用 `media` / `cards` / `forge`；
2. 新锻造暂时没有「赛季」机制（旧版赛季清空银币 / 重置附魔书没搬过来）；
3. 5E / 完美战绩、对局复盘（原插件的 `5e` / `pw` / `match`）要登录态和 LLM 点评，属于下一批。
