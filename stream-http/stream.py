#!/usr/bin/env python3
"""
DV20 RGB 摄像头 MJPEG 推流服务
自动识别 DV20 设备，支持 ?t=xxx 查询参数
"""

import cv2
import sys
import os
import signal
import threading
import time
import argparse
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse

# 全局状态
capture = None
latest_jpeg = None
jpeg_lock = threading.Lock()
running = True

# ===== 自动识别 DV20 设备路径 =====
def find_dv20_device():
    """通过 v4l2-ctl --list-devices 找到 DV20 的第一个 /dev/video*"""
    try:
        output = subprocess.check_output(
            ['v4l2-ctl', '--list-devices'],
            stderr=subprocess.STDOUT, timeout=5
        ).decode()
    except Exception as e:
        print(f"[警告] v4l2-ctl 失败: {e}", flush=True)
        return '/dev/video0'

    current_name = ''
    for line in output.splitlines():
        line = line.rstrip()
        # 设备名行（不含缩进）
        if line and not line.startswith((' ', '\t')):
            current_name = line
        # 设备路径行（缩进的 /dev/video 行）
        elif '/dev/video' in line and current_name:
            if 'DV20' in current_name.upper() or 'DV' in current_name:
                path = line.strip()
                print(f"[发现] DV20 设备: {current_name} → {path}", flush=True)
                return path
            current_name = ''

    # 没找到 DV20，fallback
    print(f"[警告] 未找到 DV20 设备，使用默认 /dev/video0", flush=True)
    return '/dev/video0'


# ===== 后台抓帧线程 =====
def capture_loop(device, width, height):
    global capture, latest_jpeg, running

    cap = cv2.VideoCapture(device)
    if not cap.isOpened():
        print(f"[错误] 无法打开 {device}", flush=True)
        running = False
        return

    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, 25)

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"[相机] {device} → {actual_w}x{actual_h} @ MJPG", flush=True)

    capture = cap
    drain_count = 0

    while running:
        ret, frame = cap.read()
        if not ret:
            drain_count += 1
            if drain_count > 10:
                print(f"[错误] 连续 {drain_count} 帧读取失败，尝试重连...", flush=True)
                cap.release()
                time.sleep(1)
                cap = cv2.VideoCapture(device)
                if not cap.isOpened():
                    print(f"[错误] 重连失败", flush=True)
                    running = False
                    return
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
                cap.set(cv2.CAP_PROP_FPS, 25)
                capture = cap
                print(f"[相机] 重连成功", flush=True)
                drain_count = 0
            time.sleep(0.05)
            continue

        drain_count = 0
        ret, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not ret:
            continue
        with jpeg_lock:
            latest_jpeg = jpeg.tobytes()
        # ~25fps
        time.sleep(0.005)


# ===== HTTP 请求处理 =====
class StreamHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        path = urlparse(self.path).path

        if path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            html = """<!DOCTYPE html>
<html><head><title>DV20 摄像头推流</title>
<style>
body{background:#111;display:flex;flex-direction:column;align-items:center;color:#fff;font-family:sans-serif;padding:20px;margin:0}
h1{font-size:20px;margin:10px 0}
img{width:95vw;max-width:1280px;border-radius:8px;box-shadow:0 0 20px rgba(0,150,255,0.15)}
.info{color:#888;font-size:13px;margin-top:8px}
</style></head><body>
<h1>📷 DV20 摄像头实时画面</h1>
<img src="/video_feed" />
<p class="info">MJPEG 推流 · 支持 ?t= 防缓存参数</p>
</body></html>"""
            self.wfile.write(html.encode())
            return

        if path == '/video_feed':
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Connection', 'close')
            self.end_headers()

            frame_count = 0
            reconnect_delay = 0.01
            while running:
                with jpeg_lock:
                    data = latest_jpeg
                if data is None:
                    time.sleep(0.03)
                    reconnect_delay = min(reconnect_delay + 0.01, 0.5)
                    continue
                reconnect_delay = 0.01

                try:
                    self.wfile.write(b'--FRAME\r\n')
                    self.wfile.write(b'Content-Type: image/jpeg\r\n')
                    self.wfile.write(f'Content-Length: {len(data)}\r\n'.encode())
                    self.wfile.write(b'\r\n')
                    self.wfile.write(data)
                    self.wfile.write(b'\r\n')
                    self.wfile.flush()
                    frame_count += 1
                except (BrokenPipeError, OSError):
                    # 客户端断开是正常行为，静默退出
                    break
                time.sleep(0.025)

            return

        self.send_response(404)
        self.end_headers()


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    global running

    parser = argparse.ArgumentParser(description='DV20 摄像头推流')
    parser.add_argument('--port', type=int, default=8080, help='端口（默认 8080）')
    parser.add_argument('--device', type=str, default='', help='设备路径，不填自动识别 DV20')
    parser.add_argument('--resolution', type=str, default='640x480',
                        help='分辨率 WxH（默认 640x480）')
    args = parser.parse_args()

    try:
        w, h = map(int, args.resolution.lower().split('x'))
    except:
        w, h = 640, 480

    # 自动识别设备路径
    device = args.device if args.device else find_dv20_device()
    print(f"[设备] {device}", flush=True)

    # 启动抓帧线程
    t = threading.Thread(target=capture_loop, args=(device, w, h), daemon=True)
    t.start()
    time.sleep(2)

    if capture is None or not running:
        print("[错误] 摄像头初始化失败", flush=True)
        sys.exit(1)

    # HTTP 服务
    server = ThreadedHTTPServer(('0.0.0.0', args.port), StreamHandler)
    print(f"[服务] http://0.0.0.0:{args.port}/", flush=True)
    print(f"[服务] 视频流 http://<IP>:{args.port}/video_feed", flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        running = False
        if capture:
            capture.release()
        server.shutdown()


if __name__ == '__main__':
    main()
