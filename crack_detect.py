#!/usr/bin/env python3
"""传统图像处理 - 检测黑色裂缝（白色=石块，黑色=裂缝）"""
import cv2, numpy as np, threading, time, socket
from http.server import HTTPServer, BaseHTTPRequestHandler

CAM_ID, CAM_W, CAM_H = 0, 1280, 720
CRACK_THRESH = 60  # 低于此灰度值 = 裂缝
MIN_AREA = 200     # 最小裂缝面积（去噪）
PORT = 8000

latest_jpeg = None
fps_val = 0
lock = threading.Lock()

def detect_cracks(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    # 黑色 = 低灰度 → 裂缝
    _, crack_bin = cv2.threshold(gray, CRACK_THRESH, 255, cv2.THRESH_BINARY_INV)
    # 形态学去噪 + 连接
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    crack_clean = cv2.morphologyEx(crack_bin, cv2.MORPH_OPEN, kernel, iterations=1)
    crack_clean = cv2.morphologyEx(crack_clean, cv2.MORPH_CLOSE, kernel, iterations=2)
    # 过滤小区域
    contours, _ = cv2.findContours(crack_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    crack_mask = np.zeros_like(crack_clean)
    crack_contours = []
    for c in contours:
        if cv2.contourArea(c) > MIN_AREA:
            cv2.drawContours(crack_mask, [c], -1, 255, -1)
            crack_contours.append(c)
    return crack_mask, crack_contours

def inference_loop():
    global latest_jpeg, fps_val
    cap = cv2.VideoCapture(CAM_ID)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(3, CAM_W); cap.set(4, CAM_H); cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    fc, t0 = 0, time.time()
    while True:
        ret, frame = cap.read()
        if not ret: time.sleep(0.01); continue
        crack_mask, contours = detect_cracks(frame)
        if contours:
            result = frame.astype(np.float32)
            cf = (crack_mask > 0).astype(np.float32)
            # 裂缝涂鲜艳绿色
            result[cf > 0] = [50, 255, 50]
            frame = np.clip(result, 0, 255).astype(np.uint8)
            # 轮廓线
            cv2.drawContours(frame, contours, -1, (0, 200, 0), 1)
        fc += 1
        if fc % 30 == 0: fps_val = 30 / (time.time() - t0); t0 = time.time()
        cv2.putText(frame, f"FPS:{fps_val:.1f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
        with lock:
            _, arr = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
            latest_jpeg = arr.tobytes()

HTML = b"""<!DOCTYPE html><html><body style="margin:0;background:#222">
<h2 style="color:#0f0;text-align:center">Crack Detection</h2>
<p style="color:#aaa;text-align:center">Threshold=%d</p>
<img src="/video" style="width:100%%"></body></html>""" % CRACK_THRESH

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200); self.send_header('Content-type', 'text/html'); self.end_headers()
            self.wfile.write(HTML)
        elif self.path == '/video':
            self.send_response(200)
            self.send_header('Content-type', 'multipart/x-mixed-replace; boundary=frame')
            self.send_header('Cache-Control', 'no-cache'); self.end_headers()
            while True:
                with lock: data = latest_jpeg
                if data:
                    try: self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + data + b'\r\n')
                    except: break
                time.sleep(0.03)

if __name__ == '__main__':
    t = threading.Thread(target=inference_loop, daemon=True); t.start(); time.sleep(3)
    try: ip = socket.gethostbyname(socket.gethostname())
    except: ip = "127.0.0.1"
    print(f"=== http://{ip}:{PORT} ===")
    HTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
