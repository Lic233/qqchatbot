"""锻造排行榜：只保留锻造收益最高的**十次**历史记录。

* 每次**成功收工**（「结束锻造」/「收工」）记一条：收益（见
  ``forge.reward_for``：``完成度/100 × 5000 × ln(1+价值/5000)``，四舍五入成
  整数，跟实际发的碎片一致）、锻造人、锻造时间（精确到分
  ``YYYY-MM-DD HH:MM``）；砸碎（完成度归零、拿 0 碎片）不记。
* 记录里同时存下当时的**锻造价值**（``forge_value``）和**完成度**
  （``completion``），读榜时按**当前**收益公式重算 ``value``——以后调 K 不用
  手动改榜单；只有 ``value`` 的老记录（旧版 / 手工改的）沿用存下来的数字。
* 收益带额外倍率时（无头骑士剑诅咒「易碎」的 ×1.6）额外存一个 ``reward_factor``，
  重算时**连这个倍率一起乘**，所以榜上记的就是真正发到手的那份收益。
* 顺带存下这局砸的是哪把剑（``sword``），排行榜图上要显示；老记录没有就留空。
* 只留前十：新记录要**严格高于**第十名才挤得进去；同分先到先得。
* 整个机器人一份榜（不分群），落盘到 ``data/forge_rank.json``，
  写临时文件再原子替换，重启不丢。
* 兼容旧 NapCat 版的文件格式：``user_id`` 可能是数字，读进来统一转成字符串；
  渲染只用 ``value`` / ``name`` / ``time``，``user_id`` 只是内部留存。
  （字段名沿用旧版的 ``value``，装的是这一局的收益。）

对外是 :class:`ForgeRank` 实例（路径由调用方注入），这样自检可以指向临时目录，
不会碰真实榜单。
"""
from __future__ import annotations

import datetime
import json
import tempfile
from pathlib import Path

from .base import log

TOP_N = 10
COMMAND = "锻造排行榜"
TIME_FORMAT = "%Y-%m-%d %H:%M"
# 第 1~3 名的后缀是 1st/2nd/3rd，其余 th（11~13 也走 th）。
_ORDINAL_SUFFIX = {1: "st", 2: "nd", 3: "rd"}


def is_rank_command(text: str) -> bool:
    """是不是「锻造排行榜」这条命令（只有这五个字，多一个字都不算）。"""
    return (text or "").strip() == COMMAND


def ordinal(number: int) -> str:
    """1 → ``1st``、2 → ``2nd``、3 → ``3rd``、4 → ``4th``、11 → ``11th``。"""
    if 10 <= number % 100 <= 20:
        suffix = "th"
    else:
        suffix = _ORDINAL_SUFFIX.get(number % 10, "th")
    return f"{number}{suffix}"


def _sort_key(record: dict) -> tuple[float, str]:
    """收益高的在前；同分按时间早的在前（时间字符串可直接比较）。"""
    return (-float(record.get("value") or 0), str(record.get("time") or ""))


def _factor_of(raw: object) -> float:
    """把存下来的额外倍率收拾成浮点数；没写 / 写坏了都当 1.0（不乘）。"""
    if raw is None:
        return 1.0
    try:
        factor = float(raw)
    except (TypeError, ValueError):
        return 1.0
    return factor if factor > 0 else 1.0


def _reward_for(forge_value: float, completion: float) -> int:
    """按**当前**收益公式把「锻造价值 + 完成度」折成收益。

    延迟导入 ``forge``：``forge`` 反过来要用本模块，模块级导入会成环。
    """
    from .forge import reward_for

    return reward_for(forge_value, completion)


class ForgeRank:
    """一份磁盘上的锻造排行榜（最多十条）。"""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._records: list[dict] = []
        self._loaded = False

    @staticmethod
    def _normalize(raw: object) -> dict | None:
        """把文件里的一条记录收拾成内部格式；不像样的返回 None（丢掉）。

        带 ``forge_value`` + ``completion`` 时按**当前**公式重算 ``value``；
        只有 ``value`` 的老记录原样沿用，重算不了也不丢。
        """
        if not isinstance(raw, dict):
            return None
        forge_value: float | None = None
        completion: float | None = None
        try:
            if raw.get("forge_value") is not None and raw.get("completion") is not None:
                forge_value = float(raw["forge_value"])
                completion = float(raw["completion"])
        except (TypeError, ValueError):
            forge_value = completion = None
        factor = _factor_of(raw.get("reward_factor"))
        if forge_value is not None and completion is not None:
            value = _reward_for(forge_value, completion)
            if factor != 1.0:
                value = int(round(value * factor))
        else:
            try:
                value = int(round(float(raw.get("value"))))
            except (TypeError, ValueError):
                return None
            forge_value = completion = None
        if value <= 0:
            return None
        record = {
            "value": value,
            "user_id": str(raw.get("user_id") or "").strip(),
            "name": str(raw.get("name") or "").strip() or "群友",
            "time": str(raw.get("time") or "").strip(),
        }
        if forge_value is not None and completion is not None:
            record["forge_value"] = forge_value
            record["completion"] = completion
        if factor != 1.0:
            record["reward_factor"] = factor
        sword_name = str(raw.get("sword") or "").strip()
        if sword_name:
            record["sword"] = sword_name
        return record

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError) as error:
            log(f"[锻造排行榜] 记录读取失败，从空榜开始：{error}")
            return
        # 允许数组，也允许 {"records": [...]} 这种包一层的写法（手工改文件时常见）。
        if isinstance(raw, dict):
            raw = raw.get("records", [])
        if not isinstance(raw, list):
            log("[锻造排行榜] 记录文件格式不对（不是数组），从空榜开始")
            return
        cleaned = [record for record in map(self._normalize, raw) if record]
        cleaned.sort(key=_sort_key)
        self._records[:] = cleaned[:TOP_N]
        log(f"[锻造排行榜] 已载入 {len(self._records)} 条记录")

    def _save(self) -> None:
        temporary: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix="forge_rank_", suffix=".tmp", delete=False,
            ) as file:
                temporary = Path(file.name)
                json.dump(self._records, file, ensure_ascii=False, indent=2)
                file.write("\n")
            temporary.replace(self.path)
        except OSError as error:
            log(f"[锻造排行榜] 记录保存失败：{error}")
            if temporary is not None and temporary.exists():
                temporary.unlink(missing_ok=True)

    def record(
        self,
        value: float | int,
        user_id: str,
        name: str = "",
        when: datetime.datetime | None = None,
        forge_value: float | None = None,
        completion: float | None = None,
        reward_factor: float | None = None,
        sword: str | None = None,
    ) -> int | None:
        """记一次收工的收益；进了前十返回名次（1 起），没进返回 None。

        带上 ``forge_value`` / ``completion`` 时会一起存盘（并按当前公式重算
        收益），以后调 K 只要读榜就会自动跟着变；只传 ``value`` 的老用法兼容。
        ``reward_factor`` 是额外的收益倍率（无头骑士剑诅咒「易碎」的 ×1.6）：
        会跟价值/完成度一起存，重算时连它一起乘，榜上就是实际到手的收益。
        ``sword`` 是这一局砸的剑名（石剑 / 无头骑士剑 …），排行榜图上要显示。
        """
        try:
            forge_value = float(forge_value) if forge_value is not None else None
            completion = float(completion) if completion is not None else None
        except (TypeError, ValueError):
            forge_value = completion = None
        factor = _factor_of(reward_factor)
        if forge_value is not None and completion is not None:
            value = _reward_for(forge_value, completion)
            if factor != 1.0:
                value = int(round(value * factor))
        else:
            try:
                value = int(round(float(value)))
            except (TypeError, ValueError):
                return None
        if value <= 0:
            # 0 收益（砸碎 / 完成度归零）没有上榜的意义。
            return None
        display_name = str(name or "").strip() or "群友"
        timestamp = (when or datetime.datetime.now()).strftime(TIME_FORMAT)
        entry = {
            "value": value,
            "user_id": str(user_id or ""),
            "name": display_name,
            "time": timestamp,
        }
        if forge_value is not None and completion is not None:
            entry["forge_value"] = round(forge_value, 2)
            entry["completion"] = completion
        if factor != 1.0:
            entry["reward_factor"] = factor
        sword_name = str(sword or "").strip()
        if sword_name:
            entry["sword"] = sword_name
        self._ensure_loaded()
        # 榜单满了、又没比第十名高（同分也算没超过）：不记。
        if len(self._records) >= TOP_N and value <= int(self._records[-1]["value"]):
            return None
        self._records.append(entry)
        # list.sort 稳定：同收益、同分钟时，先记的那条仍排在前面。
        self._records.sort(key=_sort_key)
        del self._records[TOP_N:]
        self._save()
        for index, item in enumerate(self._records):
            if item is entry:
                log(
                    f"[锻造排行榜] {display_name} 收益 {value} 进榜："
                    f"第 {index + 1} 名（{timestamp}）"
                )
                return index + 1
        return None

    def leaderboard(self) -> list[dict]:
        """当前榜单的副本（收益从高到低，最多十条）。"""
        self._ensure_loaded()
        return [dict(item) for item in self._records]

    def clear(self) -> None:
        """清空榜单并删掉记录文件（自检专用）。"""
        self._records.clear()
        self._loaded = True
        try:
            self.path.unlink(missing_ok=True)
        except OSError as error:
            log(f"[锻造排行榜] 清空记录文件失败：{error}")
