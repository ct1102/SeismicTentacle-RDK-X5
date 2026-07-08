#!/usr/bin/env python3
"""YOLO裂缝检测 - mask>0.5=裂缝，鲜艳填充"""
import sys, cv2, numpy as np, hbm_runtime

MODEL_PATH = "/userdata/models/best_v2.bin"
INPUT_W, INPUT_H, SCORE_THRES, NMS_THRES = 320, 224, 0.52, 0.5

def sigmoid(x): return 1/(1+np.exp(-np.clip(x,-20,20)))
def nms(boxes,scores,thresh):
    if len(boxes)==0: return []
    order=scores.argsort()[::-1]; keep=[]
    areas=(boxes[:,2]-boxes[:,0])*(boxes[:,3]-boxes[:,1])
    while len(order):
        i=order[0]; keep.append(i)
        if len(order)==1: break
        rest=order[1:]
        xx1=np.maximum(boxes[i,0],boxes[rest,0]); yy1=np.maximum(boxes[i,1],boxes[rest,1])
        xx2=np.minimum(boxes[i,2],boxes[rest,2]); yy2=np.minimum(boxes[i,3],boxes[rest,3])
        w=np.maximum(0,xx2-xx1); h=np.maximum(0,yy2-yy1)
        iou=w*h/(areas[i]+areas[rest]-w*h+1e-7)
        order=rest[iou<=thresh]
    return keep

def preprocess(img):
    r=cv2.resize(img,(INPUT_W,INPUT_H))
    yuv=cv2.cvtColor(r,cv2.COLOR_BGR2YUV_I420)
    return np.concatenate([yuv[:INPUT_H,:].ravel(),yuv[INPUT_H:INPUT_H+INPUT_H//2,:].ravel()]).astype(np.uint8).reshape(1,INPUT_H*3//2,INPUT_W,1)

model=hbm_runtime.HB_HBMRuntime(MODEL_PATH)
mname, iname, onames = model.model_names[0], model.input_names[model.model_names[0]][0], model.output_names[model.model_names[0]]

def detect_cracks(img_path, out_path=None):
    img=cv2.imread(img_path)
    if img is None: print(f"ERROR:{img_path}"); return
    ih,iw=img.shape[:2]
    raw=model.run({mname:{iname:preprocess(img)}})[mname]
    o0,protos=raw[onames[0]].squeeze(),raw[onames[1]].squeeze()
    cx,cy,w_arr,h_arr=o0[0,:],o0[1,:],o0[2,:],o0[3,:]
    cls=sigmoid(o0[4,:]); mces=o0[5:37,:].T
    boxes=np.stack([cx-w_arr/2,cy-h_arr/2,cx+w_arr/2,cy+h_arr/2],axis=1)
    mask=cls>SCORE_THRES
    if not mask.sum():
        out=out_path or img_path.replace('.jpg','_cracks.jpg'); cv2.imwrite(out,img); return
    bf,mf=boxes[mask],mces[mask]
    k=nms(bf,cls[mask],NMS_THRES); bf,mf=bf[k],mf[k]
    
    # 裂缝mask
    cm=np.zeros((ih,iw),dtype=np.float32)
    for i in range(len(bf)):
        rm=np.tensordot(mf[i],protos,axes=([0],[0])); seg=sigmoid(rm)
        x1i=max(0,int(bf[i,0]*iw/INPUT_W)); y1i=max(0,int(bf[i,1]*ih/INPUT_H))
        x2i=min(iw,int(bf[i,2]*iw/INPUT_W)); y2i=min(ih,int(bf[i,3]*ih/INPUT_H))
        if x2i<=x1i or y2i<=y1i: continue
        cm[y1i:y2i,x1i:x2i]=np.maximum(cm[y1i:y2i,x1i:x2i],cv2.resize(seg,(x2i-x1i,y2i-y1i)))
    
    # mask>0.5 = 裂缝 → 鲜艳绿
    result=img.astype(np.float32)
    crack=(cm>0.5)
    result[crack]=[50,255,50]
    result=np.clip(result,0,255).astype(np.uint8)
    
    out=out_path or img_path.replace('.jpg','_cracks.jpg')
    cv2.imwrite(out,result)
    print(f"Saved:{out} boxes={len(bf)} cracks={crack.sum()}px")

if __name__=='__main__':
    detect_cracks(sys.argv[1] if len(sys.argv)>1 else '/userdata/models/1.jpg')
