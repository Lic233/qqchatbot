# config/ 说明

这个目录放「静态配置 + 凭据」。凭据类文件**不入库**（见根目录 `.gitignore`），
clone 下来后需要自己新建。

## 需要自己创建的文件（一行一个值，UTF-8 无 BOM）

| 文件名 | 内容 | 用途 |
| --- | --- | --- |
| `appid.txt` | QQ 开放平台的 AppID | 机器人鉴权 |
| `secret.txt` | QQ 开放平台的 AppSecret | 机器人鉴权 |
| `deepseek_api.txt` | `sk-...` | AI 对话 + 联网搜索 |
| `search_api.txt` | `sk-...` | 联网搜索（单独计费时用） |
| `bilibili_cookie.txt` | 整段 Cookie（推荐） | 视频总结、字幕 |
| `bilibili_sessdata.txt` | 单个 SESSDATA 值 | 上面的备用写法 |

也可以用环境变量代替：`QQ_BOT_APPID`、`QQ_BOT_SECRET`、`DEEPSEEK_API_KEY`、
`BILIBILI_COOKIE`、`BILIBILI_SESSDATA`，优先级高于同名文件。

## 已经随仓库提供的内容文件

- `persona.txt` —— 人设卡（角色设定 / 说话风格）
- `help.txt` —— 群内帮助文案
- `changelog.txt` / `changelog_legacy.txt` —— 更新日志
- `新锻造系统.txt` —— 现在这套锻造（选材 / 锻造 / 淬火 / 测试）的数值与文案
- `锻造系统.txt` —— 旧锻造（石剑 / 铁剑 / 钻石剑 + 附魔书）的规则，入口已关，留作参考
- `mc_guess_easy.json` —— 弗一把「简单模式」题库（739 条，Java 1.20.2 截止）
- `mc_guess_hard.json` —— 弗一把「困难模式」题库（225 条，1.20.5 ~ 26.3，以及简单题库漏收的老物品）

  改题库只动这两个 JSON：一条题目至少要有 `name` / `version` / `type` / `tags` / `world`，
  `note` 是猜中后的介绍，`aliases` 是别名和英文 id，带 16 色的条目写 `"colored": true`
  就会自动补颜色别名；`weight` 是抽题权重（默认 1，正数，越大越容易被抽到；楼梯 / 台阶 / 告示牌 / 栅栏 / 墙 / 门 / 活板门 / 按钮 / 压力板 / 船这些同款族系现在是 0.3）；`version_names` 是「版本号 → 更新主题名」的映射（如 `1.13: 水域更新`），只用于显示。
  字段拼错、版本 / 类型 / 标签不在词表里、权值不是正数都会当场报错；
  改完跑 `python tools/mc_guess_check.py` 单独验一遍（不用启动机器人）。

改完配置重启进程生效（环境变量在 import 时只读一次）。

## 可选依赖

- **Pillow** —— 库存图 / 签到图 / CS2 卡片；没装就只发文字
- **GPT-SoVITS**（可选）—— 本地自训音色的引擎，默认优先用；要在
  `F://GPTSoVITS` 有整合包 + `GPTSoVits` conda 环境，路径可用 `QQCHATBOT_GSV_DIR` /
  `QQCHATBOT_GSV_PYTHON` 改，`QQCHATBOT_GSV=0` 关掉
- **edge-tts** —— `语音：xxx` 用微软的神经网络音色（`pip install edge-tts`）；
  没装会自动退回 Windows 自带 SAPI 音色，功能不受影响

## 运行时数据不在这个目录

`data/` 下是跑起来才会产生的东西：吊图、老婆图、卡池、库存、签到、运势、
群友画像、排行榜。这些已在 `.gitignore` 里排除，仓库只保留一个空的 `data/`。
