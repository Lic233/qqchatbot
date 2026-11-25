"""发语音：把一段文字念成语音条。

QQ 的语音条走富媒体上传（file_type=3），认 silk / mp3 / wav / ogg，所以这里
只要产出一个音频文件就行，**不用自己编码 silk**（省掉 ffmpeg + pilk）。

两个引擎都只是「外部命令」，不引入硬依赖：

  edge —— Edge「大声朗读」的在线接口（`pip install edge-tts`），音质自然，
          zh-CN-XiaoxiaoNeural 这类神经网络音色；
  sapi —— Windows 自带 SAPI 音色（装机就有，离线可用），音质老派但绝对能用。

auto 先试 edge，不可用就退 sapi。
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import importlib.util
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass

from .base import *  # noqa: F401,F403


class VoiceError(RuntimeError):
    """合成失败：调用方据此退回文字，不往上抛。"""


# `语音：你好` 优先，`说 你好` / `说话 你好` / `念 你好` 是同义的短写法。
# **必须带分隔符**才认：全量消息模式下群里随口一句「说得好」不该被当成命令。
VOICE_COMMANDS: tuple[str, ...] = ("语音", "说话", "说", "念")
VOICE_SEPARATORS = (" ", "\u3000", "：", ":", "，", ",")

VOICE_USAGE = (
    f"想听我说话就发「语音：你好呀」，冒号后面写要念的内容"
    f"（最长 {VOICE_MAX_CHARS} 字，太长了会自动拆成几条）"
)

_SENTENCE_CUT = "。！？!?；;…\n"
_SOFT_CUT = "，,、：: "   # 句子太长时退一步，在这些地方断

_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_TAG_RE = re.compile(r"<[^>]{1,60}>")          # <qqbot-at-user id="…" />
_MARK_RE = re.compile(r"[*_`#>~|\[\]{}]")
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D\u2b00-\u2bff]"
)
_SPACE_RE = re.compile(r"\s+")


# --------------------------------------------------------------------------
# 命令解析 / 文本清洗
# --------------------------------------------------------------------------


def tts_payload(command: str) -> str | None:
    """``语音：你好`` → ``你好``；``/说 你好`` → ``你好``。

    不是语音命令时返回 None；是命令但没带内容时返回空字符串（调用方提示用法）。
    """
    text = (command or "").strip().lstrip("/／").strip()
    for prefix in VOICE_COMMANDS:
        if not text.startswith(prefix):
            continue
        if text == prefix:
            return ""            # 只写了命令、没带内容 → 调用方提示用法
        rest = text[len(prefix):]
        if rest[0] not in VOICE_SEPARATORS:
            continue
        return rest[1:].strip()
    return None


# 「语音模型」换嗓子：这几个前缀后面跟角色名就是切换，不跟就是看列表。
# 长的放前面，否则「换语音模型」会被「换语音」先吃掉。
VOICE_MODEL_PREFIXES: tuple[str, ...] = (
    "换语音模型", "语音模型", "语音音色", "语音角色", "换语音", "换嗓子",
)
_LIST_WORDS = ("列表", "清单", "有什么", "能换什么", "都有什么", "哪些")


def voice_model_payload(command: str) -> tuple[str, str] | None:
    """``语音模型 铃兰`` → ``("switch", "铃兰")``；``语音模型`` → ``("list", "")``。

    不是换音色的命令时返回 None。
    """
    text = (command or "").strip().lstrip("/／").strip()
    for prefix in VOICE_MODEL_PREFIXES:
        if not text.startswith(prefix):
            continue
        rest = text[len(prefix):].strip(" \u3000：:，,").strip()
        if not rest or rest in _LIST_WORDS:
            return ("list", "")
        return ("switch", rest)
    return None


def clean_for_tts(text: str) -> str:
    """把要念的文本洗一遍：去掉 @ 标记、链接、markdown 符号和表情。

    语音里念出「星号星号」或者一长串 URL 很难听，这些留着没意义。
    """
    cleaned = (text or "").replace("\r", " ").replace("\n", "，")
    cleaned = _URL_RE.sub("，链接，", cleaned)
    cleaned = _TAG_RE.sub(" ", cleaned)
    cleaned = _MARK_RE.sub("", cleaned)
    cleaned = _EMOJI_RE.sub("", cleaned)
    cleaned = _SPACE_RE.sub(" ", cleaned).strip()
    return cleaned.strip("，,。 ")


def split_for_voice(text: str, limit: int | None = None) -> list[str]:
    """把长文本按标点切成若干段，每段不超过 ``limit`` 字。

    一条语音条几十秒还行，几分钟的语音在客户端上不好拖，也容易触平台限制，
    所以超长的就拆成几条连续语音发出去（每段都在句号 / 逗号处断开，不会拦腰砍）。
    总字数超过 ``VOICE_MAX_CHARS`` 时抛 VoiceError（这种就该让用户自己缩短）。
    """
    cleaned = clean_for_tts(text)
    if not cleaned:
        return []
    if len(cleaned) > VOICE_MAX_CHARS:
        raise VoiceError(
            f"太长了，一次最多念 {VOICE_MAX_CHARS} 字（这条 {len(cleaned)} 字）"
        )
    limit = max(40, int(limit or VOICE_CHUNK_CHARS))
    if len(cleaned) <= limit:
        return [cleaned]

    segments: list[str] = []
    rest = cleaned
    while len(rest) > limit:
        window = rest[:limit]
        cut = max(window.rfind(mark) for mark in _SENTENCE_CUT)
        if cut < limit // 3:
            # 整段没有句号：退一步在逗号/顿号处断，实在没有就硬切。
            cut = max(cut, *(window.rfind(mark) for mark in _SOFT_CUT))
        if cut < limit // 4:
            cut = limit - 1
        piece = rest[:cut + 1].lstrip("，,、：:。 ")
        if piece:
            segments.append(piece)
        rest = rest[cut + 1:].lstrip("，,、：:。 ")
    if rest.strip("，,、：:。 "):
        segments.append(rest.strip("，,、：:。 "))
    return segments


def _ps_str(value: str) -> str:
    """PowerShell 单引号字符串（内部单引号要写两遍）。"""
    return "'" + str(value).replace("'", "''") + "'"


def sapi_rate() -> int:
    """把 ``+20%`` 换算成 SAPI 的 -10~10 档。"""
    match = re.search(r"[-+]?\d+(?:\.\d+)?", TTS_RATE)
    if not match:
        return 0
    return max(-10, min(10, int(round(float(match.group()) / 10))))


# --------------------------------------------------------------------------
# TTS 引擎
# --------------------------------------------------------------------------


def edge_available() -> bool:
    try:
        return importlib.util.find_spec("edge_tts") is not None
    except (ImportError, ValueError):
        return False


def sapi_available() -> bool:
    return sys.platform == "win32" and shutil.which("powershell") is not None


# --- GPT-SoVITS（本地自训模型）--------------------------------------------
#
# 它自己带一套 FastAPI 服务（api_v2.py），接口：
#   POST /tts  {text, ref_audio_path, prompt_text, …}  → 直接回 wav
#   GET  /set_gpt_weights?weights_path=…     换 GPT 权重（**不可靠，别用**）
#   GET  /set_sovits_weights?weights_path=…  换 SoVITS 权重（同上）
#
# 踩过的坑：SoVITS 是 v4 底模 + LoRA，用 /set_sovits_weights 在运行中换，
# 接口照样回 success，但音色其实还是上一个模型的（实测基频 335Hz，
# 而重启后加载同一份权重是 356Hz，官方样音 380Hz）。所以换模型一律
# **重启服务 + 启动时从 yaml 加载**，不用 set 接口。
#
# 服务没起来时这里会自己拉起来（模型加载 20~40 秒），拉过就不再重复拉；
# 权重变了（脚本指纹对不上）会自动杀掉旧服务重开。
# 注意：**本机请求必须绕开系统代理**，否则 127.0.0.1 会走到代理上 502。

_GSV_OPENER = None
_GSV_LOCK: asyncio.Lock | None = None

# 权重指纹：记「当前这个服务加载的是哪两个文件」。和配置对不上就重开服务。
_GSV_STAMP = Path(tempfile.gettempdir()) / "qqchatbot-gsv.stamp"

# 给 api_v2 用的 yaml（复制一份到项目里，方便按配置改写 custom 段的权重）。
_GSV_CONFIG = DATA_DIR / "gsv" / "tts_infer.yaml"
_GSV_BASE_CONFIG = Path(GSV_DIR, "GPT_SoVITS", "configs", "tts_infer.yaml")


def _gsv_api(path: str = "") -> str:
    return f"http://{GSV_HOST}:{GSV_PORT}{path}"


def gsv_available() -> bool:
    """能不能用 gsv：只看配置齐不齐（服务不在线也能自己拉起来）。"""
    if not GSV_ENABLED:
        return False
    return Path(GSV_DIR, "api_v2.py").is_file()


# --- 音色目录：一个子目录一个角色，群里发消息就能换 -------------------------


@dataclass(frozen=True)
class GsvModel:
    """一套自包含的音色：权重 + 参考音频 + 台本。"""

    name: str        # 目录名，也是群里叫的名字（铃兰 / 能天使）
    gpt: str         # GPT 权重（相对 GSV_DIR 或绝对路径）
    sovits: str      # SoVITS 权重（同上）
    ref_audio: str   # 参考音频绝对路径
    ref_text: str    # 参考音频的台本

    def label(self) -> str:
        return f"{self.name}（{Path(self.sovits).stem}）"


_MODEL_CACHE: GsvModel | None = None


def _as_weight(path: Path) -> str:
    """能写成相对整合包目录的就写相对（yaml 里短、换盘符也不炸）。"""
    try:
        return path.resolve().relative_to(Path(GSV_DIR).resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


def _first_match(directory: Path, patterns: tuple[str, ...],
                 exclude: tuple[str, ...] = ()) -> Path | None:
    for pattern in patterns:
        for path in sorted(directory.glob(pattern)):
            if path.is_file() and not any(word in path.name for word in exclude):
                return path
    return None


def scan_models() -> list[GsvModel]:
    """扫音色目录，返回完整的角色（缺权重/参考音频/台本的目录直接跳过）。"""
    root = Path(GSV_MODELS_DIR)
    if not root.is_dir():
        return []
    models: list[GsvModel] = []
    for directory in sorted(p for p in root.iterdir() if p.is_dir()):
        sovits = _first_match(
            directory, ("*SoVITS*.pth", "*sovits*.pth", "*_e*.pth", "*.pth")
        )
        gpt = _first_match(directory, ("*GPT*.ckpt", "*gpt*.ckpt", "*.ckpt"))
        # 参考音频不能拿「样音_xx.wav」顶替：那是合成结果，不是真人原声。
        ref = _first_match(
            directory,
            ("参考音频.wav", "ref.wav", "*.wav"),
            exclude=("样音", "sample", "preview"),
        )
        text = _first_match(directory, ("参考文本.txt", "ref_text.txt", "*.txt"))
        if not (sovits and gpt and ref and text):
            continue
        try:
            ref_text = text.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not ref_text:
            continue
        models.append(
            GsvModel(
                name=directory.name,
                gpt=_as_weight(gpt),
                sovits=_as_weight(sovits),
                ref_audio=str(ref),
                ref_text=ref_text,
            )
        )
    return models


def _default_model() -> GsvModel:
    """没换过（或换过的角色被删了）时用哪个：先按 GSV_DEFAULT_ROLE 找，再退配置。"""
    models = scan_models()
    for wanted in (GSV_DEFAULT_ROLE, Path(str(GSV_SOVITS_WEIGHTS)).parent.name):
        for model in models:
            if wanted and model.name == wanted:
                return model
    if models:
        return models[0]
    # 目录里一个都认不出来，就退回 config 里写死的那套（可能是散装权重）。
    sovits = Path(str(GSV_SOVITS_WEIGHTS))
    return GsvModel(
        name=sovits.parent.name or sovits.stem or "默认",
        gpt=str(GSV_GPT_WEIGHTS),
        sovits=str(GSV_SOVITS_WEIGHTS),
        ref_audio=str(GSV_REF_AUDIO),
        ref_text=GSV_REF_TEXT,
    )


def current_model() -> GsvModel:
    """现在用的音色：优先群里换过的（状态文件），否则配置默认。"""
    global _MODEL_CACHE
    if _MODEL_CACHE is not None:
        return _MODEL_CACHE
    wanted = ""
    with contextlib.suppress(OSError, ValueError):
        data = json.loads(Path(GSV_MODEL_STATE).read_text(encoding="utf-8"))
        wanted = str(data.get("model", "")).strip()
    if wanted:
        for model in scan_models():
            if model.name == wanted:
                _MODEL_CACHE = model
                return model
        log(f"[语音] 记着的音色「{wanted}」不在了，回到默认音色")
    _MODEL_CACHE = _default_model()
    return _MODEL_CACHE


def switch_model(name: str) -> GsvModel:
    """换音色：只记到状态文件，服务会在下一次合成时自己重开（约 40 秒）。"""
    global _MODEL_CACHE
    wanted = (name or "").strip()
    models = scan_models()
    if not models:
        raise VoiceError(
            f"没找到能换的嗓子（{GSV_MODELS_DIR} 里每个角色要有权重、参考音频和台本）"
        )
    hit = next((m for m in models if m.name == wanted), None)
    if hit is None and wanted:
        # 「铃」「兰」这种只打了半个名字也认。
        hit = next(
            (m for m in models if wanted in m.name or m.name in wanted), None
        )
    if hit is None:
        names = "、".join(m.name for m in models)
        raise VoiceError(
            f"没有「{wanted}」这个嗓子，能换的是：{names}"
            if wanted else f"要换哪个？能换的是：{names}"
        )
    if hit.name == current_model().name:
        return hit
    state = Path(GSV_MODEL_STATE)
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(
        json.dumps({"model": hit.name, "at": int(time.time())}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _MODEL_CACHE = hit
    # 让下一次合成重新判断题「权重换了」→ 自动重启服务。
    with contextlib.suppress(OSError):
        _GSV_STAMP.unlink()
    log(f"[语音] 音色已切换：{hit.name}（{hit.sovits}）")
    return hit


def models_text() -> str:
    """给「语音模型」命令用的列表文案。"""
    models = scan_models()
    current = current_model()
    if not models:
        return (
            f"没找到能换的嗓子。要放 {GSV_MODELS_DIR}/<角色>/ 里，"
            f"每个角色一个目录，里面有权重、参考音频和参考文本。"
        )
    names = "、".join(
        f"{m.name}（当前）" if m.name == current.name else m.name for m in models
    )
    example = next((m.name for m in models if m.name != current.name), current.name)
    return (
        f"现在用的是 {current.name}。能换的：{names}。"
        f"发「语音模型 {example}」这样换。"
    )


def can_switch_voice(user_openid: str) -> bool:
    """谁能换嗓子：默认谁都能（小群自己人），配了白名单就只认白名单。"""
    if VOICE_SWITCH_ANYONE:
        return True
    return bool(VOICE_SWITCH_ALLOW) and user_openid in VOICE_SWITCH_ALLOW


def _gsv_opener():
    global _GSV_OPENER
    if _GSV_OPENER is None:
        _GSV_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return _GSV_OPENER


def _gsv_http(method: str, path: str, payload: dict | None = None,
              timeout: float = 30) -> bytes:
    """同步调本地服务（放线程里跑，别堵事件循环）。"""
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        _gsv_api(path), data=data, method=method, headers=headers
    )
    with _gsv_opener().open(request, timeout=timeout) as response:
        return response.read()


def _gsv_port_open(timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((GSV_HOST, GSV_PORT), timeout=timeout):
            return True
    except OSError:
        return False


def _gsv_stamp_text() -> str:
    """当前权重指纹：路径 + 文件修改时间 + 大小，换文件/换角色都能认出来。"""
    model = current_model()
    parts = []
    for weights in (model.gpt, model.sovits):
        path = Path(str(weights))
        if not path.is_absolute():
            path = Path(GSV_DIR, str(weights))
        try:
            stat = path.stat()
            parts.append(f"{path.name}:{int(stat.st_mtime)}:{stat.st_size}")
        except OSError:
            parts.append(f"{path.name}:missing")
    return "|".join(parts)


def _gsv_stamp_ok() -> bool:
    try:
        return _GSV_STAMP.read_text(encoding="utf-8").strip() == _gsv_stamp_text()
    except OSError:
        return False


def _gsv_write_stamp() -> None:
    with contextlib.suppress(OSError):
        _GSV_STAMP.write_text(_gsv_stamp_text(), encoding="utf-8")


def _gsv_write_config() -> Path:
    """把 custom 段（服务启动时默认加载的那段）改成当前配置的权重。

    api_v2 启动时读 `TTS_Config.default_configs["custom"]`，只认 yaml，
    没有命令行参数可以直接指定权重，所以这里改一份副本丢给 `-c`。
    """
    source = _GSV_BASE_CONFIG
    text = source.read_text(encoding="utf-8") if source.is_file() else ""
    if not text.strip():
        raise VoiceError(f"找不到 GPT-SoVITS 的配置文件：{source}")

    def sub_field(block: str, key: str, value: str) -> str:
        pattern = re.compile(rf"^(\s*{key}:\s*).*$", re.MULTILINE)

        def repl(match: re.Match) -> str:
            return f"{match.group(1)}{json.dumps(str(value), ensure_ascii=True)}"

        new, count = pattern.subn(repl, block, count=1)
        if count == 0:                   # 原本没这个字段就补一行
            new = block.rstrip() + f'\n  {key}: {json.dumps(str(value), ensure_ascii=True)}\n'
        return new

    # 只动 custom 段：从 `custom:` 到下一个顶格键为止。
    # **只替换两个权重路径**，device / is_half / version 原样保留——
    # 布尔值写成带引号的字符串会变成 "true"，模型一半 fp16 一半 fp32 直接崩
    # （RuntimeError: Input type Half and bias type float should be the same）。
    model = current_model()
    match = re.search(r"^custom:.*?(?=^\S)", text, re.MULTILINE | re.DOTALL)
    if match:
        block = match.group(0)
        block = sub_field(block, "t2s_weights_path", model.gpt)
        block = sub_field(block, "vits_weights_path", model.sovits)
        text = text[: match.start()] + block + text[match.end():]
    else:
        text = (f"custom:\n  device: cuda\n  is_half: true\n  version: v4\n"
                f"  t2s_weights_path: {json.dumps(str(model.gpt), ensure_ascii=True)}\n"
                f"  vits_weights_path: {json.dumps(str(model.sovits), ensure_ascii=True)}\n"
                + text)

    _GSV_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    _GSV_CONFIG.write_text(text, encoding="utf-8")
    return _GSV_CONFIG


def _gsv_port_pids() -> list[int]:
    """谁在监听本机 GSV_PORT（只用于结束自己拉起来的旧服务）。"""
    if sys.platform != "win32":
        return []
    try:
        output = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, timeout=10,
        ).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return []
    pids: list[int] = []
    port = f":{GSV_PORT}"
    for line in output.splitlines():
        cols = line.split()
        if len(cols) >= 5 and cols[1].endswith(port) and cols[3] == "LISTENING":
            with contextlib.suppress(ValueError):
                pid = int(cols[4])
                if pid not in pids:
                    pids.append(pid)
    return pids


def _gsv_stop_old() -> None:
    """把占着端口的旧服务结束掉（换权重必须先重开，运行中切换不可靠）。"""
    for pid in _gsv_port_pids():
        try:
            name = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, timeout=10,
            ).stdout.decode("utf-8", "replace")
        except (OSError, subprocess.SubprocessError):
            name = ""
        if "python" not in name.lower():     # 不是 python 就别碰
            raise VoiceError(
                f"端口 {GSV_PORT} 被别的程序占着（PID {pid}），先关掉再试"
            )
        log(f"[语音] 结束旧 GPT-SoVITS 服务（PID {pid}），准备换权重重启")
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F"],
                capture_output=True, timeout=10,
            )
    deadline = time.time() + 15
    while time.time() < deadline and _gsv_port_open(0.5):
        time.sleep(0.5)


def _gsv_spawn(config_path: Path) -> None:
    """把 api_v2.py 拉起来（独立进程，bot 退出它也留着，下次直接用）。"""
    python = Path(GSV_PYTHON)
    if not python.is_file():
        raise VoiceError(f"找不到跑 GPT-SoVITS 的 python：{python}")
    log_path = Path(tempfile.gettempdir()) / "qqchatbot-gsv.log"
    log(f"[语音] 启动 GPT-SoVITS 服务：{python} api_v2.py -p {GSV_PORT}")
    # DETACHED_PROCESS：脱开 bot 的控制台，bot 重启/关窗口时不跟着一起死，
    # 模型就不用每次都重新加载（加载一次 40 秒左右）。
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    with open(log_path, "ab") as sink:
        subprocess.Popen(
            [str(python), "api_v2.py", "-a", GSV_HOST, "-p", str(GSV_PORT),
             "-c", str(config_path)],
            cwd=GSV_DIR,
            stdout=sink,
            stderr=sink,
            stdin=subprocess.DEVNULL,
            creationflags=flags,
        )


async def _ensure_gsv(timeout_note: str = "") -> None:
    """保证服务在跑，而且加载的是配置里那两个权重。"""
    global _GSV_LOCK
    if _GSV_LOCK is None:
        _GSV_LOCK = asyncio.Lock()
    async with _GSV_LOCK:
        running = await asyncio.to_thread(_gsv_port_open, 0.5)
        if running and await asyncio.to_thread(_gsv_stamp_ok):
            return
        if running:
            log("[语音] 权重和当前服务不一致，重启 GPT-SoVITS 换个模型")
            await asyncio.to_thread(_gsv_stop_old)
        config_path = await asyncio.to_thread(_gsv_write_config)
        await asyncio.to_thread(_gsv_spawn, config_path)
        deadline = time.time() + GSV_START_TIMEOUT
        while time.time() < deadline:
            await asyncio.sleep(1.0)
            if await asyncio.to_thread(_gsv_port_open, 0.5):
                break
        else:
            raise VoiceError(
                f"GPT-SoVITS 服务 {timeout_note}没起来（等了 "
                f"{GSV_START_TIMEOUT:.0f}s，日志见临时目录 qqchatbot-gsv.log）"
            )
        log("[语音] GPT-SoVITS 服务就绪，权重已在启动时加载")
        await asyncio.to_thread(_gsv_write_stamp)


async def _synth_gsv(text: str, directory: Path) -> Path:
    model = current_model()
    if not Path(model.ref_audio).is_file():
        raise VoiceError(f"参考音频不存在：{model.ref_audio}")
    await _ensure_gsv()
    payload = {
        "text": text,
        "text_lang": "zh",
        "ref_audio_path": str(model.ref_audio).replace("\\", "/"),
        "prompt_text": model.ref_text,
        "prompt_lang": "zh",
        "media_type": "wav",
        "streaming_mode": False,
        "parallel_infer": True,
        "sample_steps": GSV_STEPS,
        "speed_factor": GSV_SPEED,
    }
    try:
        raw = await asyncio.to_thread(
            _gsv_http, "POST", "/tts", payload, GSV_TIMEOUT
        )
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:200]
        # 服务可能被重启过（或者状态乱了），下次重新检查/重开，别用带病状态硬跑。
        with contextlib.suppress(OSError):
            _GSV_STAMP.unlink()
        raise VoiceError(f"GPT-SoVITS 返回 {error.code}：{detail}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise VoiceError(f"GPT-SoVITS 请求失败：{error}") from error
    if len(raw) < 2048 or not raw.startswith(b"RIFF"):
        raise VoiceError("GPT-SoVITS 返回的不是 wav")
    path = directory / f"{uuid.uuid4().hex}.wav"
    path.write_bytes(raw)
    return path


async def prewarm() -> None:
    """bot 启动时先把服务拉起来，第一条语音就不用等模型加载。"""
    if not (VOICE_ENABLED and gsv_available() and GSV_PREWARM):
        return
    try:
        await _ensure_gsv("预热")
        log("[语音] GPT-SoVITS 预热完成")
    except VoiceError as error:
        log(f"[语音] GPT-SoVITS 预热失败（合成时会再试）：{error}")


def engine_available(engine: str) -> bool:
    if engine == "gsv":
        return gsv_available()
    if engine == "edge":
        return edge_available()
    return sapi_available()


def engine_order(choice: str | None = None) -> list[str]:
    """auto 的顺序：gsv（自训音色）→ edge（自然音）→ sapi（离线兜底）。"""
    picked = (choice or TTS_ENGINE or "auto").strip().lower()
    if picked in {"gsv", "edge", "sapi"}:
        return [picked]
    return ["gsv", "edge", "sapi"]


def active_engine() -> str:
    """启动日志用：这一台机器实际会用哪个引擎。"""
    for name in engine_order():
        if engine_available(name):
            return name
    return "none"


def describe() -> str:
    engine = active_engine()
    if not VOICE_ENABLED:
        return "语音功能已关闭（QQCHATBOT_VOICE=0）"
    if engine == "gsv":
        model = current_model()
        head = f"发语音：GPT-SoVITS（{model.label()}，{GSV_STEPS} 步）"
    elif engine == "edge":
        head = f"发语音：edge（{TTS_VOICE}，音调 {TTS_PITCH}）"
    elif engine == "sapi":
        # 退到离线音色时把「哪个 python 缺 edge-tts」直接写出来：这台机器上
        # 同时装了好几个 python，装错地方不写清楚根本查不出来。
        head = (
            f"发语音：sapi（{TTS_SAPI_VOICE}，离线音色，机械味）"
            f"；这个 python 没装 edge-tts，要自然音请运行："
            f'"{sys.executable}" -m pip install edge-tts'
        )
    else:
        head = "发语音：没有可用引擎（装 edge-tts 或换 Windows）"
    # 语音条只在群友发「语音：…」时触发，AI 回复不会自动念一遍。
    return head + "；只有发「语音：…」才念"


def _tmp_dir() -> Path:
    # 和其他渲染产物一样放系统临时目录，发完就删，不占 data/。
    directory = Path(tempfile.gettempdir()) / "qqchatbot-voice"
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise VoiceError(f"建临时目录失败：{error}") from error
    return directory


async def _run(cmd: list[str], timeout: float) -> tuple[int, str, str]:
    """跑一个外部合成程序，返回（退出码, stdout, stderr）。"""
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except (OSError, ValueError) as error:
        raise VoiceError(f"启动合成程序失败：{error}") from error
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError, OSError):
            process.kill()
        raise VoiceError(f"合成超时（{timeout:.0f}s）") from None
    return (
        process.returncode or 0,
        (stdout or b"").decode("utf-8", "replace"),
        (stderr or b"").decode("utf-8", "replace"),
    )


async def _synth_edge(text: str, directory: Path) -> Path:
    """Edge 在线朗读。文本走临时文件（`--file`），避开 Windows 命令行的编码坑。"""
    stem = uuid.uuid4().hex
    text_path = directory / f"{stem}.txt"
    audio_path = directory / f"{stem}.mp3"
    text_path.write_text(text, encoding="utf-8")
    cmd = [
        sys.executable, "-m", "edge_tts",
        "--voice", TTS_VOICE,
        "--rate", TTS_RATE,
        "--pitch", TTS_PITCH,
        "--file", str(text_path),
        "--write-media", str(audio_path),
        "--no-progress",
    ]
    try:
        code, _, stderr = await _run(cmd, VOICE_TIMEOUT)
    finally:
        text_path.unlink(missing_ok=True)
    if code != 0 or not audio_path.is_file() or audio_path.stat().st_size < 1024:
        audio_path.unlink(missing_ok=True)
        raise VoiceError(f"edge 合成失败（{code}）：{stderr.strip()[:200]}")
    return audio_path


async def _synth_sapi(text: str, directory: Path) -> Path:
    """Windows 自带音色：文本和输出路径都走临时文件 + -EncodedCommand。

    用 -EncodedCommand（UTF-16LE base64）而不是拼接命令行，中文和引号都不会
    在系统代码页上被啃掉——实测直接传中文参数会变问号。
    """
    stem = uuid.uuid4().hex
    text_path = directory / f"{stem}.txt"
    audio_path = directory / f"{stem}.wav"
    text_path.write_text(text, encoding="utf-8")
    script = "\r\n".join((
        "Add-Type -AssemblyName System.Speech",
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer",
        f"try {{ $s.SelectVoice({_ps_str(TTS_SAPI_VOICE)}) }} catch {{ }}",
        f"$s.Rate = {sapi_rate()}",
        f"$s.SetOutputToWaveFile({_ps_str(str(audio_path))})",
        f"$s.Speak([IO.File]::ReadAllText({_ps_str(str(text_path))}, [Text.Encoding]::UTF8))",
        "$s.Dispose()",
    ))
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        code, _, stderr = await _run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            VOICE_TIMEOUT,
        )
    finally:
        text_path.unlink(missing_ok=True)
    if code != 0 or not audio_path.is_file() or audio_path.stat().st_size < 1024:
        audio_path.unlink(missing_ok=True)
        raise VoiceError(f"sapi 合成失败（{code}）：{stderr.strip()[:200]}")
    return audio_path


async def synthesize(text: str, *, out_dir: Path | None = None,
                     engine: str | None = None) -> Path:
    """把一段文字念成音频文件，返回路径（调用方发完要删）。

    失败一律抛 VoiceError，里面带每个引擎试过的原因。
    """
    payload = clean_for_tts(text)
    if not payload:
        raise VoiceError("没有可以念的内容")
    if len(payload) > VOICE_MAX_CHARS:
        raise VoiceError(f"太长了，一次最多念 {VOICE_MAX_CHARS} 字")
    directory = out_dir or _tmp_dir()
    reasons: list[str] = []
    for name in engine_order(engine):
        if name not in {"gsv", "edge", "sapi"}:
            reasons.append(f"{name}：不认识的引擎")
            continue
        if not engine_available(name):
            reasons.append(
                f"{name}：{_unavailable_reason(name)}"
            )
            continue
        try:
            if name == "gsv":
                path = await _synth_gsv(payload, directory)
            elif name == "edge":
                path = await _synth_edge(payload, directory)
            else:
                path = await _synth_sapi(payload, directory)
        except VoiceError as error:
            reasons.append(f"{name}：{error}")
            continue
        log(f"[语音] {name} 合成完成（{path.stat().st_size / 1024:.0f}KB）")
        return path
    raise VoiceError("；".join(reasons) or "没有可用的语音引擎")


def _unavailable_reason(name: str) -> str:
    if name == "gsv":
        return f"没找到 {Path(GSV_DIR, 'api_v2.py')}"
    if name == "edge":
        return "没装 edge-tts"
    return "这台机器没有 PowerShell"


# --------------------------------------------------------------------------
# 命令行：验通路用（不经过 QQ，只看能不能出声）
# --------------------------------------------------------------------------


def _list_engines() -> None:
    service = "在线" if _gsv_port_open(0.5) else "未启动（合成时会自动拉起）"
    print(f"GPT-SoVITS：{'已配置' if gsv_available() else '未配置（检查 QQCHATBOT_GSV_DIR）'}"
          f"，服务 {service}")
    if gsv_available():
        model = current_model()
        print(f"  当前音色：{model.name}")
        print(f"  权重：{model.sovits} + {model.gpt}")
        print(f"  参考：{model.ref_audio}")
        others = [m.name for m in scan_models() if m.name != model.name]
        print(f"  可切换：{'、'.join(others) if others else '（没有别的角色）'}")
    print(f"edge-tts：{'已安装' if edge_available() else '未安装（pip install edge-tts）'}")
    print(f"Windows SAPI：{'可用' if sapi_available() else '不可用'}")
    engine = active_engine()
    voice_name = {
        "gsv": current_model().label(),
        "edge": TTS_VOICE,
        "sapi": TTS_SAPI_VOICE,
    }.get(engine, "—")
    print(f"当前会用的引擎：{engine}，音色 {voice_name}")


async def _list_voices() -> None:
    if edge_available():
        _, output, _ = await _run(
            [sys.executable, "-m", "edge_tts", "--list-voices"], 60
        )
        lines = [line.strip() for line in output.splitlines() if "zh-CN" in line]
        print("\nedge 中文音色（前 12 个）：")
        for line in lines[:12]:
            print("  " + line)
    if sapi_available():
        script = "\r\n".join((
            "$ProgressPreference = 'SilentlyContinue'",
            "Add-Type -AssemblyName System.Speech",
            "[Console]::OutputEncoding = [Text.Encoding]::UTF8",
            "(New-Object System.Speech.Synthesis.SpeechSynthesizer)"
            ".GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }",
        ))
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        _, output, _ = await _run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], 60
        )
        print("\nSAPI 音色：")
        for line in output.splitlines():
            if line.strip():
                print("  " + line.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="发语音自检：看引擎、试合成")
    parser.add_argument("text", nargs="*", help="要念的文本；给了就合成一条音频")
    parser.add_argument("--voices", action="store_true", help="列出可用引擎和音色")
    parser.add_argument("--engine", default="", help="edge / sapi，默认按配置（auto）")
    parser.add_argument("--out", default="", help="输出路径，默认 ./voice-preview.*")
    args = parser.parse_args(argv)

    print(describe())
    if args.voices:
        _list_engines()
        asyncio.run(_list_voices())
    if not args.text:
        if not args.voices:
            print("用法：python -m qqbot.voice 你好呀   或   --voices")
        return 0

    text = " ".join(args.text)
    try:
        path = asyncio.run(synthesize(text, engine=args.engine or None))
    except VoiceError as error:
        print(f"合成失败：{error}")
        return 1
    target = Path(args.out) if args.out else Path.cwd() / f"voice-preview{path.suffix}"
    try:
        shutil.move(str(path), str(target))
    except OSError as error:
        print(f"移到 {target} 失败，留在 {path}：{error}")
        return 0
    print(f"已合成：{target}（{target.stat().st_size / 1024:.0f}KB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
