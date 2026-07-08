#!/usr/bin/env python3
"""
RGB Camera MJPEG 推流服务（纯 http.server，更稳）
用法: python3 /tmp/stream_http.py [--port 8080] [--camera-id 1]
"""

import cv2
import sys
import os
import signal
import threading
import time
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse

# 全局摄像头句柄
capture = None
cam_lock = threading.Lock()
latest_jpeg = None
jpeg_lock = threading.Lock()
running = True

# ===== 后台抓帧线程 =====
def capture_loop(cam_id, width, height):
    global capture, latest_jpeg, running
    cap = None

    # 试 cam_id ~ cam_id+2
    for offset in range(3):
        idx = cam_id + offset
        c = cv2.VideoCapture(idx, cv2.CAP_V4L2)
        if not c.isOpened():
            continue
        c.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        c.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        c.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        c.set(cv2.CAP_PROP_FPS, 30)
        ret, frame = c.read()
        if ret:
            cap = c
            h, w = frame.shape[:2]
            print(f"[相机] OpenCV index {idx} → {w}x{h} @ MJPG", flush=True)
            break
        c.release()

    if cap is None:
        print("[错误] 无法打开摄像头", flush=True)
        running = False
        return

    capture = cap
    while running:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.05)
            continue
        ret, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        if not ret:
            continue
        with jpeg_lock:
            latest_jpeg = jpeg.tobytes()
        # ~30fps
        time.sleep(0.01)

# ===== HTTP 请求处理 =====
class StreamHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 静默日志，减少干扰

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            html = """<!DOCTYPE html>
<html><head><title>RDK X5 RGB 摄像头</title>
<style>
body{background:#111;display:flex;flex-direction:column;align-items:center;color:#fff;font-family:sans-serif;padding:20px;margin:0}
h1{font-size:20px;margin:10px 0}
img{width:95vw;max-width:1280px;border-radius:8px;box-shadow:0 0 20px rgba(0,150,255,0.15)}
.info{color:#888;font-size:13px;margin-top:8px}
</style></head><body>
<h1>📷 RDK X5 摄像头实时画面</h1>
<img src="/video_feed" />
<p class="info">MJPEG 推流 · 刷新页面可恢复</p>
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
            while running:
                with jpeg_lock:
                    data = latest_jpeg
                if data is None:
                    time.sleep(0.03)
                    continue
                try:
                    self.wfile.write(b'--FRAME\r\n')
                    self.wfile.write(b'Content-Type: image/jpeg\r\n')
                    self.wfile.write(f'Content-Length: {len(data)}\r\n'.encode())
                    self.wfile.write(b'\r\n')
                    self.wfile.write(data)
                    self.wfile.write(b'\r\n')
                    self.wfile.flush()
                    frame_count += 1
                except BrokenPipeError:
                    print(f"[客户端] 断开连接，已发送 {frame_count} 帧", flush=True)
                    break
                except OSError:
                    break
                time.sleep(0.02)
            return

        # favicon
        self.send_response(404)
        self.end_headers()

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

def main():
    global running
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--camera-id', type=int, default=1)
    parser.add_argument('--resolution', type=str, default='640x480')
    args = parser.parse_args()

    try:
        w, h = map(int, args.resolution.lower().split('x'))
    except:
        w, h = 1280, 720

    # 启动抓帧线程
    t = threading.Thread(target=capture_loop, args=(args.camera_id, w, h), daemon=True)
    t.start()
    time.sleep(2)

    if capture is None or not running:
        print("[错误] 摄像头初始化失败", flush=True)
        sys.exit(1)

    # 启动 HTTP 服务
    server = ThreadedHTTPServer(('0.0.0.0', args.port), StreamHandler)
    print(f"[服务] http://0.0.0.0:{args.port}/", flush=True)
    print(f"[服务] 线程式 MJPEG 推流，多客户端同时连接", flush=True)

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
