#!/usr/bin/env python3
"""voice_assistant.py — 录音 → ASR → LLM → TTS → 蓝牙音箱"""

import os, sys, time, json, wave, subprocess, numpy as np, re
import sherpa_onnx, urllib.request
from urllib.error import HTTPError

STUDIO_HOST = os.environ.get("STUDIO_HOST", "192.168.128.100:8787")
DEVICE_ID   = os.environ.get("DEVICE_ID", "2280c5b1-b424-4f84-8dae-dd358dbd6c80")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
MODEL_DIR   = os.environ.get("MODEL_DIR", "/opt/sherpa-models")

REC_DEVICE  = "plughw:0,0"
BT_ADDR     = "41:42:55:03:B7:4C"
BT_DEVICE   = f"bluealsa:SRV=org.bluealsa,DEV={BT_ADDR},PROFILE=sco"
SR          = 16000; REC_SEC = 4; ENERGY_MIN = 2000

MODEL_ASR   = f"{MODEL_DIR}/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/model.int8.onnx"
TOKENS_ASR  = f"{MODEL_DIR}/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/tokens.txt"
MODEL_TTS   = f"{MODEL_DIR}/vits-zh-aishell3/vits-aishell3.onnx"
LEXICON_TTS = f"{MODEL_DIR}/vits-zh-aishell3/lexicon.txt"
TOKENS_TTS  = f"{MODEL_DIR}/vits-zh-aishell3/tokens.txt"

def _num_to_cn(s):
    d = dict(zip('0123456789', '零一二三四五六七八九'))
    try:
        n = int(s)
        if n < 10: return d[s]
        if n < 100:
            r = ''
            if n // 10 > 1: r += d[str(n//10)]
            r += '十'
            if n % 10: r += d[str(n%10)]
            return r
        return s
    except: return s

print("[init] ASR...", flush=True)
asr = sherpa_onnx.OfflineRecognizer.from_sense_voice(
    model=MODEL_ASR, tokens=TOKENS_ASR,
    num_threads=4, sample_rate=SR, language='auto', use_itn=True)

print("[init] TTS...", flush=True)
tts = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(
    model=sherpa_onnx.OfflineTtsModelConfig(
        vits=sherpa_onnx.OfflineTtsVitsModelConfig(
            model=MODEL_TTS, lexicon=LEXICON_TTS, tokens=TOKENS_TTS,
        ), num_threads=4,
    ),
))

prev_bt = None  # 上次蓝牙连接状态

def log(msg):
    s = msg.encode('utf-8', 'surrogatepass').decode('utf-8', 'replace')
    print(f"[{time.strftime('%H:%M:%S')}] {s}", flush=True)

def bt_ensure():
    """确保蓝牙音箱已连接"""
    global prev_bt
    r = subprocess.run(["bluetoothctl", "info", BT_ADDR],
                       capture_output=True, text=True, timeout=10)
    if "Connected: yes" in r.stdout:
        if prev_bt != "ok":
            log("蓝牙已连接")
            prev_bt = "ok"
        return True
    log("正在连接蓝牙音箱...")
    subprocess.run(["bluetoothctl", "connect", BT_ADDR],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    time.sleep(2)
    r2 = subprocess.run(["bluetoothctl", "info", BT_ADDR],
                        capture_output=True, text=True, timeout=10)
    if "Connected: yes" in r2.stdout:
        prev_bt = "ok"
        log("蓝牙已连接")
        return True
    log("蓝牙连接失败，改用板载音频")
    return False

def play_bt(path):
    """播放到蓝牙，失败时尝试重试"""
    for attempt in range(3):
        r = subprocess.run(["aplay", "-D", BT_DEVICE, path],
                           capture_output=True, text=True, timeout=20)
        if r.returncode == 0:
            return True
        if "Device or resource busy" in r.stderr:
            time.sleep(3)  # 等设备释放
            continue
        return False
    return False

def record():
    subprocess.run(["arecord","-d","4","-f","S16_LE","-r","16000","-c","1",
                    "-D",REC_DEVICE,"/tmp/voice_capture.wav"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return "/tmp/voice_capture.wav"

def energy_ok(path):
    with wave.open(path) as f:
        pcm = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16)
    peak = int(np.max(np.abs(pcm)))
    rms = float(np.sqrt(np.mean(pcm.astype(np.float32)**2)))
    return peak > ENERGY_MIN and rms > ENERGY_MIN * 0.3

def asr_recognize(path):
    with wave.open(path) as f:
        s = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    st = asr.create_stream()
    st.accept_waveform(SR, s.tolist())
    asr.decode_stream(st)
    return st.result.text.strip()

def ask_llm(text):
    if not LLM_API_KEY:
        url = f"http://{STUDIO_HOST}/api/agent/chat"
        data = json.dumps({"message":text,"deviceId":DEVICE_ID}).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(url,data=data,
                headers={"Content-Type":"application/json"}), timeout=120) as r:
                cur,parts = "",[]
                for l in r:
                    l = l.decode('utf-8','replace').strip()
                    if l.startswith("event:"): cur=l[6:].strip()
                    elif l.startswith("data:"):
                        try:
                            d=json.loads(l[5:])
                            if d.get("delta","") and d.get("kind")!="reasoning" and cur!="thinking_delta":
                                parts.append(d["delta"])
                        except: pass
                return max(parts,key=len).strip() if parts else ""
        except Exception as e: return f"[ERR {e}]"
    data = json.dumps({"model":"deepseek-chat","messages":[
        {"role":"system","content":"用中文极简短回答（20字内），不加表情符号和度数符号。"},
        {"role":"user","content":text}
    ],"temperature":0.7,"max_tokens":100}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(
            "https://api.deepseek.com/v1/chat/completions", data=data,
            headers={"Content-Type":"application/json","Authorization":f"Bearer {LLM_API_KEY}"}
        ), timeout=30) as r:
            return json.loads(r.read())['choices'][0]['message']['content'].strip()
    except Exception as e: return f"[LLM {e}]"

def clean_tts(text):
    text = re.sub(r'(\d+)\s*°[cC]?', lambda m: _num_to_cn(m.group(1))+'度', text)
    text = re.sub(r'(\d+)', lambda m: _num_to_cn(m.group(1)), text)
    for ch in '～~（）()*🌧☀☁⭐✨🔥': text = text.replace(ch, '')
    text = re.sub(r'[\U0001F300-\U0001FFFF]', '', text)
    return text

def tts_speak(text):
    text = clean_tts(text)
    t0 = time.time()
    audio = tts.generate(text, sid=0, speed=1.0)
    sr = audio.sample_rate
    amp = np.array(audio.samples, dtype=np.float32) * 6.0
    amp = np.clip(amp, -0.95, 0.95)
    s = (amp * 32767).astype(np.int16)
    with wave.open("/tmp/tts_play.wav", 'w') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(sr)
        f.writeframes(s.tobytes())
    log(f"TTS {time.time()-t0:.0f}s，播放中...")
    subprocess.run(["aplay","-D","plughw:1,0","/tmp/tts_play.wav"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def main():
    # 音量最大化
    for c in [["amixer","-c","1","sset","DAC","191"],
              ["amixer","-c","1","sset","HPL","191"],
              ["amixer","-c","1","cset","numid=17","5"],
              ["amixer","-c","1","cset","numid=18","5"]]:
        subprocess.run(c, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    log("启动！")

    try:
        tts_speak("你好，我是你的语音助手。请说指令。")
    except KeyboardInterrupt:
        log("退出"); return

    while True:
        try:
            if not energy_ok(record()):
                time.sleep(0.3); continue
            text = asr_recognize("/tmp/voice_capture.wav")
            log(f"→ {text}")
            if not text or text in ('.','。',''): continue
            reply = ask_llm(text)
            log(f"AI: {reply}")
            if not reply or reply.startswith("["): continue
            tts_speak(reply)
        except KeyboardInterrupt:
            log("退出"); break
        except Exception as e:
            log(f"错误: {e}"); time.sleep(2)

if __name__ == "__main__":
    main()
