#!/usr/bin/env python3
"""纯摄像头推流（无裂缝检测），指定摄像头索引和端口"""
import cv2, threading, time, sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

CAM_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 2
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8001
CW, CH = 640, 480

# 设备路径映射 —— 通过 /dev/video* 直接打开，避免index不稳定
DEV_MAP = {0: "/dev/video0", 1: "/dev/video1", 2: "/dev/video2",
           3: "/dev/video3", 4: "/dev/video4", 5: "/dev/video5"}

lj, lock = None, threading.Lock()

def loop():
    global lj
    dev = DEV_MAP.get(CAM_ID, CAM_ID)
    cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(3, CW); cap.set(4, CH); cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    while True:
        ok, fr = cap.read()
        if not ok: time.sleep(0.01); continue
        with lock:
            _, arr = cv2.imencode('.jpg', fr, [cv2.IMWRITE_JPEG_QUALITY, 70])
            lj = arr.tobytes()

HTML = b"<!DOCTYPE html><html><body style='margin:0;background:#222'><img src='/video' style='width:100%'></body></html>"

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200); self.send_header('Content-type','text/html'); self.end_headers(); self.wfile.write(HTML)
        elif self.path == '/video':
            self.send_response(200); self.send_header('Content-type','multipart/x-mixed-replace; boundary=frame')
            self.send_header('Cache-Control','no-cache'); self.end_headers()
            while True:
                with lock: d = lj
                if d is not None:
                    try: self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'+d+b'\r\n')
                    except: break
                time.sleep(0.03)

if __name__ == '__main__':
    t = threading.Thread(target=loop, daemon=True); t.start(); time.sleep(2)
    print(f"Camera {CAM_ID} ({DEV_MAP.get(CAM_ID, CAM_ID)}) stream at http://0.0.0.0:{PORT}")
    ThreadingHTTPServer(('0.0.0.0', PORT), H).serve_forever()
