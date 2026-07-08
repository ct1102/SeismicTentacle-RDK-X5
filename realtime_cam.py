#!/usr/bin/env python3
"""USB Camera + YOLO Crack - BBox + batch mask"""
import cv2, numpy as np, hbm_runtime, threading, time, sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

MODEL = "/userdata/models/best_v2.bin"
IW, IH, ST, NT = 320, 224, 0.52, 0.5
CAM_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 0
CW, CH, PORT = 320, 240, 8000
SCALE=min(IW/CW,IH/CH); PX=(IW-CW*SCALE)/2; PY=(IH-CH*SCALE)/2

def sig(x): return 1/(1+np.exp(-np.clip(x,-20,20)))
def nms(b,s,t):
    if len(b)==0: return []
    o=s.argsort()[::-1]; k=[]; a=(b[:,2]-b[:,0])*(b[:,3]-b[:,1])
    while len(o):
        i=o[0]; k.append(i)
        if len(o)==1: break
        r=o[1:]
        xx1=np.maximum(b[i,0],b[r,0]); yy1=np.maximum(b[i,1],b[r,1])
        xx2=np.minimum(b[i,2],b[r,2]); yy2=np.minimum(b[i,3],b[r,3])
        w=np.maximum(0,xx2-xx1); h=np.maximum(0,yy2-yy1)
        iou=w*h/(a[i]+a[r]-w*h+1e-7); o=r[iou<=t]
    return k

def bgr_to_nv12(img):
    h,w=img.shape[:2]; yuv=cv2.cvtColor(img,cv2.COLOR_BGR2YUV_I420)
    y=yuv[:h,:]; u=yuv[h:h+h//4,:]; v=yuv[h+h//4:,:]
    uv=np.empty((h//2,w),dtype=np.uint8); uv[0::2,:]=v; uv[1::2,:]=u
    return np.concatenate([y.ravel(),uv.ravel()])

model=hbm_runtime.HB_HBMRuntime(MODEL)
mn=model.model_names[0]; ia=model.input_names[mn][0]; oa=model.output_names[mn]
lj,fps,lock=None,0,threading.Lock()

def pre(fr):
    rw,rh=int(CW*SCALE),int(CH*SCALE); r=cv2.resize(fr,(rw,rh))
    c=np.full((IH,IW,3),114,dtype=np.uint8); c[int(PY):int(PY)+rh,int(PX):int(PX)+rw]=r
    return bgr_to_nv12(c).reshape(1,IH*3//2,IW,1)
def mp(x,y): return (x-PX)/SCALE,(y-PY)/SCALE

def loop():
    global lj,fps
    cap=cv2.VideoCapture(CAM_ID); cap.set(cv2.CAP_PROP_FOURCC,cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(3,CW); cap.set(4,CH); cap.set(cv2.CAP_PROP_BUFFERSIZE,1); fc,t0,ms=0,time.time(),0
    while True:
        ok,fr=cap.read()
        if not ok: time.sleep(0.01); continue
        nv12=pre(fr); raw=model.run({mn:{ia:nv12}})[mn]
        o0=raw[oa[0]].squeeze(); pt=raw[oa[1]].squeeze()
        cx=o0[0,:]; cy=o0[1,:]; ww=o0[2,:]; hh=o0[3,:]; cl=sig(o0[4,:]); mc=o0[5:37,:].T
        bx=np.stack([cx-ww/2,cy-hh/2,cx+ww/2,cy+hh/2],axis=1); mk=cl>ST
        if mk.sum():
            bf=bx[mk]; mf=mc[mk]; kk=nms(bf,cl[mk],NT); bf=bf[kk]; mf=mf[kk]
            # bbox 每帧都画
            for i in range(len(bf)):
                x1,y1=mp(bf[i,0],bf[i,1]); x2,y2=mp(bf[i,2],bf[i,3])
                cv2.rectangle(fr,(max(0,int(x1)),max(0,int(y1))),(min(CW,int(x2)),min(CH,int(y2))),(0,255,0),2)
            # mask 每帧都算（批量tensordot）
            masks=np.tensordot(mf,pt,axes=([1],[0]))
            masks=sig(masks)
            cm=np.zeros((CH,CW),dtype=np.float32)
            for i in range(len(bf)):
                x1,y1=mp(bf[i,0],bf[i,1]); x2,y2=mp(bf[i,2],bf[i,3])
                xi1=max(0,int(x1)); yi1=max(0,int(y1))
                xi2=min(CW,int(x2)); yi2=min(CH,int(y2))
                if xi2<=xi1 or yi2<=yi1: continue
                mr=cv2.resize(masks[i],(xi2-xi1,yi2-yi1))
                cm[yi1:yi2,xi1:xi2]=np.maximum(cm[yi1:yi2,xi1:xi2],mr)
            ov=fr.copy(); ov[cm>0.5]=(50,255,50); fr=cv2.addWeighted(fr,0.6,ov,0.4,0)
        fc+=1; ms+=1
        if fc%30==0: fps=30/(time.time()-t0+1e-7); t0=time.time()
        with lock: _,arr=cv2.imencode('.jpg',fr,[cv2.IMWRITE_JPEG_QUALITY,70]); lj=arr.tobytes()

HTML=b"""<!DOCTYPE html><html><body style="margin:0;background:#222">
<h2 style="color:#0f0;text-align:center">Crack - BBox + Mask</h2>
<img src="/video" style="width:100%"></body></html>"""

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path=='/': self.send_response(200); self.send_header('Content-type','text/html'); self.end_headers(); self.wfile.write(HTML)
        elif self.path=='/video':
            self.send_response(200); self.send_header('Content-type','multipart/x-mixed-replace; boundary=frame')
            self.send_header('Cache-Control','no-cache'); self.end_headers()
            while True:
                with lock: d=lj
                if d is not None:
                    try: self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'+d+b'\r\n')
                    except: break
                time.sleep(0.03)

if __name__=='__main__':
    t=threading.Thread(target=loop,daemon=True); t.start(); time.sleep(4)
    ThreadingHTTPServer(('0.0.0.0',PORT),H).serve_forever()
