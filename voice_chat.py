#!/usr/bin/env python3
"""
RDK X5 在线语音交互（百度 ASR + DeepSeek LLM + 百度 TTS）
录音 → ASR → LLM → TTS → 播放

用法:
  python3 voice_chat.py                按回车录音
  python3 voice_chat.py --wake         唤醒模式（直接播报后交互）
  python3 voice_chat.py asr            只录音+识别
  python3 voice_chat.py tts <文本>     只合成+播放
"""

import base64
import os
import struct
import subprocess
import sys
import tempfile
import time

import requests

# ─── 启动时校准系统时间 ───
# 板子无 RTC 电池，重启后会回退到 2000 年，导致 HTTPS SSL 证书验证失败
try:
    subprocess.run(["date", "-s", "2026-06-20 12:00:00"],
                   capture_output=True, timeout=5)
except Exception:
    pass

# ─── 配置 ───
ACCESS_TOKEN = "24.107ff92ac023c0c5af015cdf9b27aa06.2592000.1783427343.282335-123622944"
LLM_API_KEY = "sk-ad04321f98f245e49bfcdff79213c010"
LLM_BASE_URL = "https://api.deepseek.com/v1"
LLM_MODEL = "deepseek-chat"

CUID = "rdk_x5"
ASR_URL = "https://vop.baidu.com/server_api"
TTS_URL = "https://tsn.baidu.com/text2audio"

RATE = 16000
CHANNELS = 1
RECORD_SECONDS = 5
DEVICE_IN = "plughw:1,0"   # 麦克风（USB 拓展坞）
DEVICE_OUT = "plughw:2,0"   # 扬声器（板载 ES8326）

WAKE_THRESHOLD = 800       # 能量阈值（安静时 ~50-200，说话时 1000+）
WAKE_CHUNK_SEC = 1         # 能量检测块时长（秒）
WAKE_HITS = 2              # 连续超标次数
WAKE_GREETING = "你好，我是小地瓜，请问有什么能帮助你的嘛？"
EXIT_KEYWORDS = ("退出", "再见", "拜拜", "没别的了")


# ─── 辅助 ───

def _has_mpg123():
    return subprocess.run(["which", "mpg123"], capture_output=True).returncode == 0


def _tts_suffix():
    return ".mp3" if _has_mpg123() else ".wav"


def _tts_aue():
    return 3 if _has_mpg123() else 6


def _tts_player(path):
    if os.path.splitext(path)[1].lower() == ".mp3":
        return ["mpg123", "-q", path]
    return ["aplay", "-D", DEVICE_OUT, path]


# ─── 能量检测 ───

def _calc_rms(wav_path):
    with open(wav_path, "rb") as f:
        f.read(44)
        data = f.read()
    if len(data) < 2:
        return 0.0
    data = data[:len(data) - len(data) % 2]
    samples = struct.unpack(f"<{len(data)//2}h", data)
    return (sum(s * s for s in samples) / len(samples)) ** 0.5 if samples else 0.0


def wait_for_speech():
    """持续监听，检测到人声后返回"""
    print("[监听] 等待语音 ...", flush=True)
    hit = 0
    while True:
        chunk = tempfile.mktemp(suffix=".wav", prefix="chk_")
        subprocess.run(
            ["arecord", "-D", DEVICE_IN, "-f", "S16_LE",
             "-r", str(RATE), "-c", "1", "-d", str(WAKE_CHUNK_SEC), chunk],
            capture_output=True,
        )
        rms = _calc_rms(chunk)
        os.remove(chunk)
        if rms > WAKE_THRESHOLD:
            hit += 1
            if hit >= WAKE_HITS:
                print("[唤醒] 检测到语音", flush=True)
                return
        else:
            hit = 0


# ─── 录音 ───

def record_audio(duration=RECORD_SECONDS, path=None):
    if path is None:
        path = tempfile.mktemp(suffix=".wav", prefix="voice_")
    print(f"[录音] 正在录音 {duration} 秒 ...", flush=True)
    r = subprocess.run(
        ["arecord", "-D", DEVICE_IN, "-f", "S16_LE", "-r", str(RATE),
         "-c", str(CHANNELS), "-d", str(duration), path],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(f"[录音] 失败: {r.stderr}")
        return None
    print(f"[录音] 完成 → {path} ({os.path.getsize(path)} bytes)")
    return path


# ─── ASR（百度）───

def baidu_asr(wav_path):
    with open(wav_path, "rb") as f:
        data = f.read()
    payload = {
        "format": "wav", "rate": RATE, "channel": CHANNELS,
        "token": ACCESS_TOKEN, "cuid": CUID,
        "speech": base64.b64encode(data).decode(),
        "len": len(data),
    }
    print("[ASR] 正在识别 ...", flush=True)
    try:
        resp = requests.post(ASR_URL, json=payload, timeout=15)
        result = resp.json()
    except Exception as e:
        print(f"[ASR] 异常: {e}")
        return None
    if result.get("err_no") != 0:
        print(f"[ASR] 错误: {result.get('err_msg')} (err_no={result.get('err_no')})")
        return None
    text = result.get("result", [""])[0]
    if not text:
        print("[ASR] 未识别到语音")
        return None
    print(f"[ASR] 识别结果: 「{text}」")
    return text


# ─── LLM（DeepSeek）───

def llm_reply(user_text, system_prompt="你是一个友好的语音助手，请用简洁的中文回答，不超过50个字。"):
    print("[LLM] 正在请求 DeepSeek ...", flush=True)
    try:
        resp = requests.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
                "temperature": 0.7,
                "max_tokens": 256,
            },
            timeout=20,
        )
        reply = resp.json()["choices"][0]["message"]["content"].strip()
        print(f"[LLM] 回复: 「{reply}」")
        return reply
    except Exception as e:
        print(f"[LLM] 异常: {e}")
        return None


# ─── TTS（百度）───

def baidu_tts(text, path=None):
    if path is None:
        path = tempfile.mktemp(suffix=_tts_suffix(), prefix="tts_")
    params = {
        "tex": text, "tok": ACCESS_TOKEN, "cuid": CUID,
        "ctp": 1, "lan": "zh",
        "spd": 5, "pit": 5, "vol": 9, "per": 0,
        "aue": _tts_aue(),
    }
    print("[TTS] 正在合成语音 ...", flush=True)
    try:
        resp = requests.post(TTS_URL, data=params, timeout=15)
    except Exception as e:
        print(f"[TTS] 异常: {e}")
        return None
    if "audio" not in resp.headers.get("Content-Type", ""):
        print(f"[TTS] 错误: {resp.text[:200]}")
        return None
    with open(path, "wb") as f:
        f.write(resp.content)
    print(f"[TTS] 合成完成 → {path} ({len(resp.content)} bytes)")
    return path


def play_audio(audio_path):
    if not os.path.exists(audio_path):
        print("[播放] 文件不存在")
        return False
    print("[播放] ...", flush=True)
    r = subprocess.run(_tts_player(audio_path), capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[播放] 失败: {r.stderr}")
        return False
    print("[播放] 完成")
    return True


def _say(text):
    path = baidu_tts(text)
    if path:
        play_audio(path)
        os.remove(path)


# ─── 唤醒模式 ───

def wake_loop():
    print("\n" + "=" * 56)
    print("  RDK X5 语音交互 · 唤醒模式")
    print("  百度 ASR + DeepSeek LLM + 百度 TTS")
    print("=" * 56)
    print("  启动后会播报打招呼 → 直接说话即可")
    print("  说「退出」「再见」结束")
    print("  Ctrl+C 退出")
    print("=" * 56)
    if not _has_mpg123():
        print("[提示] mpg123 未安装，TTS 使用 WAV 格式")
    print()

    try:
        while True:
            _say(WAKE_GREETING)

            print("\n[对话] 请说出你的问题（说「退出/再见」结束）\n")
            while True:
                wait_for_speech()
                wav = record_audio()
                if not wav:
                    continue
                user_text = baidu_asr(wav)
                os.remove(wav)
                if not user_text:
                    continue
                if any(kw in user_text for kw in EXIT_KEYWORDS):
                    _say("好的，再见")
                    print("[对话] 结束本轮对话\n")
                    time.sleep(1)
                    break
                reply = llm_reply(user_text)
                if not reply:
                    continue
                _say(reply)

            time.sleep(1.5)
            print("\n--- 重新开始 ---\n")

    except KeyboardInterrupt:
        print("\n\n退出唤醒模式")


# ─── 交互模式（按回车录音） ───

def interactive_loop():
    print("\n" + "=" * 56)
    print("  RDK X5 语音交互 | 百度 ASR → DeepSeek LLM → 百度 TTS")
    print("=" * 56)
    print("  按回车 → 录音 5 秒")
    print("  输入 q  → 退出")
    print("  提示: 用 --wake 启动唤醒模式")
    print("=" * 56)
    if not _has_mpg123():
        print("[提示] mpg123 未安装，TTS 使用 WAV 格式")
    print()

    while True:
        try:
            cmd = input("\n>>> 按回车录音 (q 退出): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n退出")
            break
        if cmd.lower() in ("q", "quit", "exit"):
            break
        wav = record_audio()
        if not wav:
            continue
        text = baidu_asr(wav)
        os.remove(wav)
        if not text:
            continue
        reply = llm_reply(text)
        if not reply:
            continue
        _say(reply)


# ─── 单次命令 ───

def one_shot_asr():
    wav = record_audio()
    if not wav or not baidu_asr(wav):
        sys.exit(1)
    os.remove(wav)


def one_shot_tts(text):
    _say(text)


# ─── 入口 ───

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--wake" in sys.argv:
        wake_loop()
    elif len(args) > 0:
        if args[0] == "asr":
            one_shot_asr()
        elif args[0] == "tts":
            one_shot_tts(" ".join(args[1:]) if len(args) > 1 else "你好，我是小地瓜")
        else:
            print(f"用法: {sys.argv[0]} [--wake|asr|tts <文本>]")
    else:
        interactive_loop()
