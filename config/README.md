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
- `锻造系统.txt` —— 锻造系统的数值与文案

改完配置重启进程生效（环境变量在 import 时只读一次）。

## 运行时数据不在这个目录

`data/` 下是跑起来才会产生的东西：吊图、老婆图、卡池、库存、签到、运势、
群友画像、排行榜。这些已在 `.gitignore` 里排除，仓库只保留一个空的 `data/`。
