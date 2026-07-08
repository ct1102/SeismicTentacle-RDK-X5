#比赛
面向地震救援，基于RDK X5集成机器视觉、大模型、仿生机械与多传感技术。履带底盘适应复杂地形；RDK X5部署YOLOv8-seg实现裂缝检测分割与尺寸测算；全景摄像头采集裂隙图像；DeepSeek大模型支持语音交互问答；仿生多自由度机械臂融合雷达、氧气/二氧化碳传感器；A7670C与GPS实现求救与定位，数据上传云端远程监控；MaixCam红外热成像辅助人员搜救。系统可替代人员进入高危区域执行探测与物资搬运。 


## 项目结构
```
/userdata/
├── dht11_read               # C 编译的 GPIO 读取二进制
├── dht11_read.c             # DHT11 温湿度传感器驱动（libgpiod 时序）
├── dht11_web.py             # DHT11 Flask Web 可视化页面
├── voice_chat.py            # 在线语音交互（百度 ASR → DeepSeek → 百度 TTS）
├── stream.py                # DV20 摄像头 MJPEG 推流服务
├── stream_http.py           # 通用 RGB 摄像头 MJPEG 推流服务
├── models/
│   ├── best.bin / best_v2.bin   # YOLO 裂缝检测 BPU 模型（v1 / v2）
│   ├── realtime_cam.py          # [核心] 实时 YOLO 裂缝检测 + Web 推流
│   ├── crack_detect.py          # 传统图像处理的裂缝检测 + Web 推流
│   ├── yolo_seg_infer.py        # YOLO 分割通用推理脚本（单图）
│   ├── fill_gaps.py             # YOLO 裂缝检测 + 裂缝区域填充（单图）
│   ├── cam_stream.py            # 纯摄像头推流（设备路径/索引）
│   ├── ff_cam_stream.py         # ffmpeg pipe 版推流
│   ├── opencv_stream.py         # OpenCV 版推流
│   ├── coco_classes.names       # 类别标签文件
│   └── *.jpg                    # 测试图像
└── voice-assistant/
    └── voice_assistant.py       # 离线语音助手（sherpa-onnx 本地 ASR + TTS）
```
---
## 1. 摄像头推流
### stream.py — DV20 专用推流
- 自动识别 DV20 设备（通过 `v4l2-ctl --list-devices`）
- 后台抓帧线程 + ThreadedHTTPServer MJPEG 推流
- 分辨率默认 640×480，支持 `--port` `--device` `--resolution` 参数
- 访问：`http://<板端IP>:8080/`
```bash
python3 /userdata/stream.py --port 8080 --resolution 1280x720
```
### stream_http.py — 通用 USB 摄像头推流
- 纯 http.server，多线程，多客户端同时连接更稳定
- 自动尝试 cam_id ~ cam_id+2 找到可用的摄像头
- 支持 `--port` `--camera-id` `--resolution` 参数
```bash
python3 /userdata/stream_http.py --camera-id 1 --port 8080
```
### models/cam_stream.py — 轻量推流
- 指定摄像头索引或设备路径，端口可选
- 设备路径映射：`/dev/video0` ~ `/dev/video5`
### models/ff_cam_stream.py — ffmpeg pipe 推流
- 通过 ffmpeg 逐帧读取 JPEG 经 pipe 传递
- 支持指定设备路径和端口
### models/opencv_stream.py — OpenCV 推流
- 通过 OpenCV VideoCapture 直接读取
- 支持设备索引或设备路径
---
## 2. 裂缝检测
### 2.1 YOLO BPU 实时检测（realtime_cam.py）
- 加载 `best_v2.bin`（BPU 模型），实时 USB 摄像头推理
- 输出：Bbox + 语义 Mask（裂缝区域涂绿色）
- 通过 MJPEG 推流到浏览器（端口 8000）
- 使用 `hbm_runtime` 调用 BPU 加速
- 输入尺寸：320×224，NV12 格式
```bash
python3 /userdata/models/realtime_cam.py 0    # 摄像头索引
```
### 2.2 YOLO 单图推理（fill_gaps.py / yolo_seg_infer.py）
- `fill_gaps.py`：读入图片，BPU 推理，裂缝 mask > 0.5 涂鲜艳绿色
- `yolo_seg_infer.py`：通用推理脚本，输出带 bbox + mask 的结果图
- 训练输出图片：`原图名_cracks.jpg`
```bash
python3 /userdata/models/fill_gaps.py test.jpg
python3 /userdata/models/yolo_seg_infer.py test.jpg
```
### 2.3 传统图像处理检测（crack_detect.py）
- 不需要 BPU 模型，纯 OpenCV
- 灰度阈值（< 60 = 裂缝）+ 形态学开闭运算去噪 + 面积过滤（> 200px）
- Web 推流方式查看结果（端口 8000）
```bash
python3 /userdata/models/crack_detect.py
```
---
## 3. DHT11 温湿度监控
### dht11_read.c — C 驱动
- 使用 **libgpiod** 直接操作 GPIO（gpiochip3 line 9 / 物理 Pin 7）
- 严格的 DHT11 时序协议（20ms 拉低 → 拉高 → 等待响应 → 40bit 读取）
- 输出 JSON：`{"temp": 25, "hum": 60}`
编译：
```bash
gcc -o dht11_read dht11_read.c -lgpiod
```
### dht11_web.py — Flask Web 页面
- 调用 C helper 获取数据，3 秒轮询
- 深色主题 Web 页面，显示温度 + 湿度
- REST API `/api` 返回 JSON
```bash
python3 /userdata/dht11_web.py
# 访问 http://<板端IP>:5000
```
**接线：**
| DHT11 | RDK X5 40PIN |
|-------|-------------|
| DATA  | Pin 7 (GPIO4) |
| VCC   | Pin 1 (3.3V) |
| GND   | Pin 6 (GND) |
---
## 4. 语音交互
### voice_chat.py — 在线语音助手
- 链路：录音 → 百度 ASR → DeepSeek LLM → 百度 TTS → 播放
- 三种模式：
  - `默认`：按回车录音 5 秒→识别→回复→播报
  - `--wake`：唤醒模式，持续监听，检测到人声自动启动对话
  - `asr` / `tts <文本>`：单次命令模式
- 需要百度 API token 和 DeepSeek API key（硬编码在文件头部）
```bash
python3 /userdata/voice_chat.py           # 交互模式
python3 /userdata/voice_chat.py --wake    # 唤醒模式
python3 /userdata/voice_chat.py tts 你好   # 合成语音
```
### voice-assistant/voice_assistant.py — 离线语音助手
- 纯离线，使用 **sherpa-onnx**（SenseVoice ASR + VITS TTS）
- 支持蓝牙音箱播放（默认地址 `41:42:55:03:B7:4C`）
- 能量检测（> 2000 峰值）自动过滤静音
- LLM 支持：通过 DeepSeek API 或 RDK Studio Agent API 两种方式
- ASR 模型 + TTS 模型放在 `/opt/sherpa-models/` 目录
```bash
python3 /userdata/voice-assistant/voice_assistant.py
```
---
## 环境依赖
| 类别 | 依赖 |
|------|------|
| 系统 | RDK OS 3.x (Ubuntu 22.04), ROS2 Humble (可选) |
| 摄像头 | OpenCV (`apt install python3-opencv`), v4l-utils |
| 音频 | `arecord` / `aplay` / `mpg123`, sherpa-onnx (离线) |
| BPU | `hbm_runtime` (RDK X5 预装), `hobot-dnn` |
| GPIO | `libgpiod` (`apt install gpiod libgpiod-dev python3-libgpiod`) |
| Web | Flask (DHT11), 标准库 http.server (推流) |
| 在线 AI | requests (百度 ASR/TTS, DeepSeek API) |
---
## 快速启动示例
```bash
# 1. 摄像头推流
python3 /userdata/stream_http.py --camera-id 0
# 2. YOLO 裂缝实时检测
python3 /userdata/models/realtime_cam.py 0
# 3. DHT11 温湿度监控
python3 /userdata/dht11_web.py
# 4. 语音助手
python3 /userdata/voice_chat.py --wake
```
