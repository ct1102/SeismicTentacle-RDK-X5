#!/usr/bin/env python3
"""
RDK X5 - DHT11 温湿度传感器 + Web 可视化
==========================================
接线: DHT11 DATA → 物理 Pin 7 (GPIO4)
           VCC   → 物理 Pin 1 (3.3V)
           GND   → 物理 Pin 6 (GND)
访问: http://<RDK_X5_IP>:5000

读取方式: 调用 C helper (/userdata/dht11_read) 获取精确时序
"""

import json
import os
import subprocess
import threading
import time
from flask import Flask, render_template_string

C_HELPER = "/userdata/dht11_read"
GPIO_SYSFS = 420      # Pin 7 全局 GPIO 编号
POLL_SEC = 3
HTTP_PORT = 5000


class DHT11CReader:
    def __init__(self):
        self.temp = None
        self.hum = None
        self._last = 0
        self._lock = threading.Lock()

    def _reset_gpio(self):
        """释放 GPIO 避免 'Device or resource busy'"""
        try:
            with open("/sys/class/gpio/unexport", "w") as f:
                f.write(str(GPIO_SYSFS))
        except Exception:
            pass

    def read(self):
        now = time.time()
        if now - self._last < POLL_SEC:
            return self.temp, self.hum
        self._reset_gpio()
        time.sleep(0.5)
        try:
            r = subprocess.run(
                [C_HELPER], capture_output=True, text=True, timeout=5
            )
            data = json.loads(r.stdout)
            if data.get("temp") is not None:
                with self._lock:
                    self.temp = data["temp"]
                    self.hum = data["hum"]
                self._last = now
            elif r.stderr:
                # 重试一次（首次可能 GPIO 未完全释放）
                time.sleep(1)
                r2 = subprocess.run(
                    [C_HELPER], capture_output=True, text=True, timeout=5
                )
                data2 = json.loads(r2.stdout)
                if data2.get("temp") is not None:
                    with self._lock:
                        self.temp = data2["temp"]
                        self.hum = data2["hum"]
                    self._last = now
        except Exception:
            pass
        return self.temp, self.hum


sensor = DHT11CReader()

# ═══ Flask Web ══════════════════════════════════════
app = Flask(__name__)

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RDK X5 · 温湿度监控</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,'Segoe UI',sans-serif;background:#0f172a;color:#e2e8f0;
     display:flex;justify-content:center;align-items:center;min-height:100vh}
.card{background:#1e293b;border-radius:24px;padding:48px;text-align:center;
      box-shadow:0 20px 60px rgba(0,0,0,.5);max-width:500px;width:90%}
h1{font-size:22px;color:#94a3b8;margin-bottom:32px;letter-spacing:2px}
.sensors{display:flex;gap:32px;justify-content:center}
.item{flex:1}
.label{font-size:14px;color:#64748b;margin-bottom:8px}
.value{font-size:56px;font-weight:700}
.value.temp{color:#f97316}
.value.hum{color:#38bdf8}
.unit{font-size:20px;font-weight:400}
.status{margin-top:24px;color:#475569;font-size:13px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.dot.online{background:#22c55e}
.dot.offline{background:#ef4444}
</style>
</head>
<body>
<div class="card">
  <h1>🌡️ RDK X5 · 温湿度</h1>
  <div class="sensors">
    <div class="item">
      <div class="label">温度</div>
      <div class="value temp">{{ temp }}<span class="unit">°C</span></div>
    </div>
    <div class="item">
      <div class="label">湿度</div>
      <div class="value hum">{{ hum }}<span class="unit">%</span></div>
    </div>
  </div>
  <div class="status"><span class="dot online"></span>实时更新 · 3s 刷新</div>
</div>
<script>
async function refresh(){
  const r=await fetch('/api');
  const d=await r.json();
  document.querySelector('.value.temp').innerHTML = d.temp+'<span class="unit">°C</span>';
  document.querySelector('.value.hum').innerHTML = d.hum+'<span class="unit">%</span>';
}
setInterval(refresh, 3000);
</script>
</body>
</html>"""


@app.route('/')
def index():
    t, h = sensor.read()
    return render_template_string(
        HTML_PAGE,
        temp=t if t is not None else '--',
        hum=h if h is not None else '--'
    )


@app.route('/api')
def api():
    t, h = sensor.read()
    return json.dumps({
        'temp': t if t is not None else None,
        'hum': h if h is not None else None,
        'unit_temp': '°C',
        'unit_hum': '%'
    })


if __name__ == '__main__':
    try:
        print('━' * 45)
        print(f'  DHT11 监控  |  C helper 读取  |  端口 {HTTP_PORT}')
        print(f'  访问: http://<RDK_X5_IP>:{HTTP_PORT}')
        print('━' * 45)
        app.run(host='0.0.0.0', port=HTTP_PORT, debug=False, threaded=True)
    except KeyboardInterrupt:
        print('\n[退出]')
