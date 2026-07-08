#!/usr/bin/env python3
"""纯摄像头推流(ffmpeg版)，通过pipe逐帧读取JPEG"""
import subprocess, threading, time, sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

DEV = sys.argv[1] if len(sys.argv) > 1 else "/dev/video2"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8001

lj, lock = None, threading.Lock()
running = True

def loop():
    global lj
    cmd = [
        "ffmpeg", "-f", "v4l2",
        "-input_format", "mjpeg",
        "-video_size", "640x480",
        "-framerate", "15",
        "-i", DEV,
        "-f", "image2pipe",
        "-q:v", "5",
        "-"
    ]
    while running:
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
            buf = b""
            while running:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                buf += chunk
                # 找JPEG帧边界（FFD8/FFD9）
                while True:
                    start = buf.find(b"\xff\xd8")
                    if start < 0:
                        break
                    end = buf.find(b"\xff\xd9", start + 2)
                    if end < 0:
                        break
                    frame = buf[start:end+2]
                    buf = buf[end+2:]
                    with lock:
                        lj = frame
        except:
            time.sleep(1)

HTML = b"<!DOCTYPE html><html><body style='margin:0;background:#222'><img src='/video' style='width:100%'></body></html>"

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200); self.send_header('Content-type','text/html'); self.end_headers(); self.wfile.write(HTML)
        elif self.path == '/video':
            self.send_response(200); self.send_header('Content-type','multipart/x-mixed-replace; boundary=frame')
            self.send_header('Cache-Control','no-cache'); self.end_headers()
            while running:
                with lock: d = lj
                if d is not None:
                    try: self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'+d+b'\r\n')
                    except: break
                time.sleep(0.03)

if __name__ == '__main__':
    t = threading.Thread(target=loop, daemon=True); t.start(); time.sleep(2)
    print(f"ffmpeg stream {DEV} at http://0.0.0.0:{PORT}")
    ThreadingHTTPServer(('0.0.0.0', PORT), H).serve_forever()
