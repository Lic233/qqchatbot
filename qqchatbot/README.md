# QQ Ping-Pong Bot (Python)

## 1. 安装依赖

在本目录打开 PowerShell：

```powershell
python -m pip install -r requirements.txt
```

## 2. 检查 NapCat

NapCat WebUI -> 网络配置 -> WebSocket服务器

建议本机测试使用：

- Host: 127.0.0.1
- Port: 3001
- 启用：是
- Token：留空

如果你设置了 Token，请把 `config.py` 里的 `TOKEN = ""` 改成你的 Token。

代码按职责拆分为多个模块：

- `bot.py`：WebSocket 连接和程序入口
- `handlers.py`：群消息解析与命令分发
- `media.py`：图片、表情和吊图的保存与发送
- `attendance.py`：签到记录
- `config.py`：路径、规则和连接配置
- `state.py`：运行时状态

## 3. 运行

```powershell
python bot.py
```

看到：

```text
QQ Ping-Pong Bot 已连接
```

后，在 QQ 群中发送：

```text
ping
```

机器人回复：

```text
pong
```

## 4. 签到打卡

在群里发送：

```text
打卡
```

机器人会记录当前用户在当前群的打卡次数，发送文字回复后再发送
`faces/zayu.jpg`。记录保存在 `attendance.json`，程序重启后不会丢失。

## 5. 今日猫娘

在群里发送：

```text
变猫娘
```

机器人会随机选择一名群友，并发送 `今日猫娘是@群名称哦！`。

## 6. 吊图

发送一张图片后，在群里发送：

```text
保存吊图
```

机器人会把最近收到的图片保存到 `diaotu` 文件夹。发送：

```text
发送吊图
```

机器人会从 `diaotu` 和 `named_diaotu` 文件夹中随机发送一张图片。

也可以为上一张图片保存名称：

```text
保存吊图名称
```

命名吊图会保存在 `named_diaotu` 文件夹，并记录名称。之后发送：

```text
发送吊图名称
```

机器人会发送对应的吊图；如果没有找到该名称，会提示未找到。

## 7. 大狗叫

在群里发送：

```text
大狗叫不叫
```

机器人有 80% 概率回复“不叫”，有 20% 概率回复“叫！！！”并发送
`faces/dagoujiao.jpg`。

## 8. 集卡系统

每天每位用户有 5 次抽卡机会。在群里发送：

```text
抽卡
```

抽卡会按稀有、史诗、神话、传奇四种品质进行概率抽取，并分阶段发送过程消息，
最后发送卡片图片。发送：

```text
查看库存
```

可以查看当前用户拥有的卡牌数量。卡片名称和图片的对应关系分别保存在
`rare_card/cards.json`、`epic_card/cards.json`、`myth_card/cards.json` 和
`legend_card/cards.json` 中。

限定卡牌记录保存在 `limited_card/cards.json` 中。限定卡牌不参与普通抽卡，
并且在查看库存时显示在所有普通卡牌之后。目前记录的限定卡牌为“猜对概率的奖励奶龙”。

管理员可以在 Python 中调用 `card_system.add_draws_to_all()`，给所有已经产生过
集卡记录的用户各增加 5 次抽卡机会。也可以传入其他增加次数，例如：

在项目根目录 `F:\qqchatbot` 下执行：

```powershell
Set-Location .\qqchatbot
python -c "from card_system import add_draws_to_all; print(add_draws_to_all(5))"
```

也可以进入 Python 交互环境后调用：

```powershell
Set-Location .\qqchatbot
python
```

```python
from card_system import add_draws_to_all

add_draws_to_all(5)
```

## 9. 最近 CS2 比赛

在群里发送：

```text
大份比赛
```

机器人会分两条消息输出：当前时间之前最近的 5 场比赛，以及当前时间之后最近的 5 场比赛。

需要在程序目录创建 `pandascore_api.txt`，文件中只填写 PandaScore API key，
不要加引号或其他文字：

```text
你的 PandaScore API key
```

也可以使用环境变量：

```powershell
$env:PANDASCORE_TOKEN = "你的 PandaScore API key"
python bot.py
```

## 9. 停止

PowerShell 中按：

```text
Ctrl + C
```
