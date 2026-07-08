# competition
Designed for earthquake rescue, this system is based on the RDK X5 platform, integrating computer vision, large language models, bionic mechanisms, and multi-sensing technologies. Its tracked chassis adapts to complex terrain. The RDK X5 deploys YOLOv8-seg for crack detection, segmentation, and dimension measurement, while a panoramic camera captures images of fissures. The DeepSeek LLM enables voice-interactive Q&A. A bionic multi‑DOF robotic arm integrates radar, oxygen, and carbon dioxide sensors. The A7670C module and GPS enable distress signaling and positioning, with data uploaded to the cloud for remote monitoring. MaixCam provides infrared thermal imaging to assist in personnel search and rescue. The system can replace human operators in high‑risk areas for detection and material transport tasks.


## Directory Structure
```
/userdata/
├── dht11_read               # Compiled GPIO binary (DHT11 reader)
├── dht11_read.c             # DHT11 sensor C driver (libgpiod bit-banging)
├── dht11_web.py             # Flask web dashboard for DHT11
├── voice_chat.py            # Online voice assistant (Baidu ASR → DeepSeek → Baidu TTS)
├── stream.py                # MJPEG stream server for DV20 camera
├── stream_http.py           # MJPEG stream server for generic USB camera
├── models/
│   ├── best.bin / best_v2.bin   # YOLO crack detection BPU models (v1 / v2)
│   ├── realtime_cam.py          # [Core] Live YOLO crack detection + web stream
│   ├── crack_detect.py          # Classical CV crack detection + web stream
│   ├── yolo_seg_infer.py        # Generic YOLO segmentation inference (single image)
│   ├── fill_gaps.py             # YOLO crack detection with region fill (single image)
│   ├── cam_stream.py            # Minimal camera stream server
│   ├── ff_cam_stream.py         # ffmpeg pipe-based stream server
│   ├── opencv_stream.py         # OpenCV-based stream server
│   ├── coco_classes.names       # Class label file
│   └── *.jpg                    # Test images
└── voice-assistant/
    └── voice_assistant.py       # Offline voice assistant (sherpa-onnx ASR + TTS)
```
---
## 1. Camera Streaming
### stream.py — DV20 Dedicated Stream
- Auto-detects DV20 via `v4l2-ctl --list-devices`
- Background capture thread + ThreadedHTTPServer MJPEG stream
- Default resolution 640×480, supports `--port`, `--device`, `--resolution`
- Visit: `http://<board_ip>:8080/`
```bash
python3 /userdata/stream.py --port 8080 --resolution 1280x720
```
### stream_http.py — Generic USB Camera Stream
- Pure `http.server`, multi-threaded, stable with multiple clients
- Auto-searches cam_id ~ cam_id+2 for first working camera
- Supports `--port`, `--camera-id`, `--resolution`
```bash
python3 /userdata/stream_http.py --camera-id 1 --port 8080
```
### models/cam_stream.py — Lightweight Stream
- Specify camera index or device path, optional port
- Device mapping: `/dev/video0` ~ `/dev/video5`
### models/ff_cam_stream.py — ffmpeg Pipe Stream
- Reads JPEG frames via ffmpeg pipe
### models/opencv_stream.py — OpenCV Stream
- Direct OpenCV VideoCapture
---
## 2. Crack Detection
### 2.1 YOLO BPU Real-time Detection (realtime_cam.py)
- Loads `best_v2.bin` (BPU model), runs inference on live USB camera feed
- Outputs: Bounding boxes + Semantic mask (crack regions colored green)
- MJPEG web stream on port 8000
- Uses `hbm_runtime` for BPU acceleration
- Input size: 320×224, NV12 format
```bash
python3 /userdata/models/realtime_cam.py 0    # camera index
```
### 2.2 YOLO Single Image Inference (fill_gaps.py / yolo_seg_infer.py)
- `fill_gaps.py`: Reads image → BPU inference → cracks painted bright green (mask > 0.5)
- `yolo_seg_infer.py`: Generic inference, outputs result with bbox + mask
- Output: `input_cracks.jpg`
```bash
python3 /userdata/models/fill_gaps.py test.jpg
python3 /userdata/models/yolo_seg_infer.py test.jpg
```
### 2.3 Classical CV Detection (crack_detect.py)
- No BPU model required, pure OpenCV
- Grayscale threshold (< 60 = crack) + morphological open/close + area filter (> 200px)
- Web stream on port 8000
```bash
python3 /userdata/models/crack_detect.py
```
---
## 3. DHT11 Temperature & Humidity Monitor
### dht11_read.c — C Driver
- Uses **libgpiod** to directly drive GPIO (gpiochip3 line 9 / physical Pin 7)
- Strict DHT11 timing protocol (20ms pull-low → pull-high → 40-bit read)
- Outputs JSON: `{"temp": 25, "hum": 60}`
Build:
```bash
gcc -o dht11_read dht11_read.c -lgpiod
```
### dht11_web.py — Flask Web Dashboard
- Calls C helper for data, polls every 3 seconds
- Dark-themed web UI showing temperature + humidity
- JSON API at `/api`
```bash
python3 /userdata/dht11_web.py
# Visit http://<board_ip>:5000
```
**Wiring:**
| DHT11 | RDK X5 40-PIN |
|-------|---------------|
| DATA  | Pin 7 (GPIO4) |
| VCC   | Pin 1 (3.3V)  |
| GND   | Pin 6 (GND)   |
---
## 4. Voice Interaction
### voice_chat.py — Online Voice Assistant
- Pipeline: Record → Baidu ASR → DeepSeek LLM → Baidu TTS → Playback
- Three modes:
  - `default`: Press Enter → record 5s → recognize → reply → speak
  - `--wake`: Wake-word mode, auto-detect voice to start conversation
  - `asr` / `tts <text>`: One-shot commands
- Requires Baidu API token + DeepSeek API key (hardcoded at file top)
```bash
python3 /userdata/voice_chat.py              # interactive mode
python3 /userdata/voice_chat.py --wake       # wake mode
python3 /userdata/voice_chat.py tts hello    # synthesize speech
```
### voice-assistant/voice_assistant.py — Offline Voice Assistant
- Fully offline, powered by **sherpa-onnx** (SenseVoice ASR + VITS TTS)
- Supports Bluetooth speaker playback (default addr `41:42:55:03:B7:4C`)
- Energy detection (> 2000 peak) filters silence automatically
- LLM via DeepSeek API or RDK Studio Agent API
- ASR + TTS models under `/opt/sherpa-models/`
```bash
python3 /userdata/voice-assistant/voice_assistant.py
```
---
## Dependencies
| Category | Requirements |
|----------|-------------|
| System | RDK OS 3.x (Ubuntu 22.04), ROS2 Humble (optional) |
| Camera | OpenCV (`apt install python3-opencv`), v4l-utils |
| Audio | `arecord` / `aplay` / `mpg123`, sherpa-onnx (offline) |
| BPU | `hbm_runtime` (pre-installed on RDK X5), `hobot-dnn` |
| GPIO | `libgpiod` (`apt install gpiod libgpiod-dev python3-libgpiod`) |
| Web | Flask (DHT11), stdlib http.server (streaming) |
| Online AI | `requests` (Baidu ASR/TTS, DeepSeek API) |
---
## Quick Start
```bash
# 1. Camera stream
python3 /userdata/stream_http.py --camera-id 0
# 2. YOLO crack detection live
python3 /userdata/models/realtime_cam.py 0
# 3. DHT11 weather monitor
python3 /userdata/dht11_web.py
# 4. Voice assistant
python3 /userdata/voice_chat.py --wake
```
