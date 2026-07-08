#!/usr/bin/env python3
"""纯摄像头推流(OpenCV版)，通过设备路径打开摄像头"""
import cv2, threading, time, sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

DEV = sys.argv[1] if len(sys.argv) > 1 else 0
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8001
CW, CH = 640, 480

try:
    CAM_ID = int(DEV)
except:
    CAM_ID = DEV  # 直接当设备路径用

lj, lock = None, threading.Lock()

def loop():
    global lj
    cap = cv2.VideoCapture(CAM_ID)
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
    print(f"Stream {DEV} at http://0.0.0.0:{PORT}")
    ThreadingHTTPServer(('0.0.0.0', PORT), H).serve_forever()
