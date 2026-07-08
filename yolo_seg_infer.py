#!/usr/bin/env python3
"""YOLO Seg Inference - 通用推理脚本 (cx,cy,w,h 格式)"""
import sys, cv2, numpy as np, hbm_runtime
from time import time

MODEL_PATH = "/userdata/models/best.bin"
INPUT_W, INPUT_H = 320, 224
SCORE_THRES = 0.52
NMS_THRES = 0.5
MASK_THRES = 0.5

def sigmoid(x):
    return 1/(1+np.exp(-np.clip(x,-20,20)))

def nms(boxes, scores, thresh):
    if len(boxes)==0: return []
    order = scores.argsort()[::-1]; keep = []
    areas = (boxes[:,2]-boxes[:,0])*(boxes[:,3]-boxes[:,1])
    while len(order):
        i = order[0]; keep.append(i)
        if len(order)==1: break
        rest = order[1:]
        xx1=np.maximum(boxes[i,0],boxes[rest,0]); yy1=np.maximum(boxes[i,1],boxes[rest,1])
        xx2=np.minimum(boxes[i,2],boxes[rest,2]); yy2=np.minimum(boxes[i,3],boxes[rest,3])
        w=np.maximum(0,xx2-xx1); h=np.maximum(0,yy2-yy1)
        iou=w*h/(areas[i]+areas[rest]-w*h+1e-7)
        order=rest[iou<=thresh]
    return keep

def preprocess(img):
    resized = cv2.resize(img, (INPUT_W, INPUT_H))
    yuv = cv2.cvtColor(resized, cv2.COLOR_BGR2YUV_I420)
    y=yuv[:INPUT_H,:]; uv=yuv[INPUT_H:INPUT_H+INPUT_H//2,:]
    nv12=np.concatenate([y.ravel(),uv.ravel()]).astype(np.uint8)
    return nv12.reshape(1,INPUT_H*3//2,INPUT_W,1)

def infer_frame(model, img, img_path=""):
    mname=model.model_names[0]; iname=model.input_names[mname][0]; onames=model.output_names[mname]
    nv12=preprocess(img)
    t0=time(); raw=model.run({mname:{iname:nv12}})[mname]; dt=(time()-t0)*1000
    
    o0=raw[onames[0]].squeeze(); o1=raw[onames[1]].squeeze()
    protos=o1
    
    # decode: cx,cy,w,h (in input pixel coords, NO sigmoid)
    cx,cy,w_arr,h_arr=o0[0,:],o0[1,:],o0[2,:],o0[3,:]
    cls_scores=sigmoid(o0[4,:])
    mces=o0[5:37,:].T
    
    x1=cx-w_arr/2; y1=cy-h_arr/2; x2=cx+w_arr/2; y2=cy+h_arr/2
    boxes=np.stack([x1,y1,x2,y2],axis=1)
    
    mask=cls_scores>SCORE_THRES
    if not mask.sum():
        print(f"  No detections (max conf={cls_scores.max():.3f})")
        return img, 0
    
    boxes_f=boxes[mask]; scores_f=cls_scores[mask]; mces_f=mces[mask]
    k=nms(boxes_f,scores_f,NMS_THRES)
    boxes_f,scores_f,mces_f=boxes_f[k],scores_f[k],mces_f[k]
    
    ih,iw=img.shape[:2]
    sx=iw/INPUT_W; sy=ih/INPUT_H
    boxes_f[:,[0,2]]*=sx; boxes_f[:,[1,3]]*=sy
    boxes_f=np.clip(boxes_f,0,[iw,ih,iw,ih])
    
    result=img.copy()
    for i in range(len(boxes_f)):
        x1,y1,x2,y2=boxes_f[i].astype(int)
        cv2.rectangle(result,(x1,y1),(x2,y2),(0,255,0),2)
        cv2.putText(result,f"{scores_f[i]:.2f}",(x1,max(y1-5,10)),
                    cv2.FONT_HERSHEY_SIMPLEX,0.5,(0,255,0),1)
    
    # masks
    if len(mces_f)>0:
        overlay=result.copy()
        for i in range(len(mces_f)):
            mask_map=np.tensordot(mces_f[i],protos,axes=([0],[0]))
            mask_map=sigmoid(mask_map)
            mr=cv2.resize(mask_map,(iw,ih))
            overlay[mr>MASK_THRES]=(0,200,0)
        result=cv2.addWeighted(result,0.6,overlay,0.4,0)
    
    print(f"  {dt:.1f}ms | {len(boxes_f)} detections")
    for i in range(min(len(boxes_f),3)):
        x1,y1,x2,y2=boxes_f[i].astype(int)
        print(f"  [{i}] ({x1},{y1})-({x2},{y2}) conf={scores_f[i]:.3f}")
    
    return result, len(boxes_f)

if __name__=="__main__":
    if len(sys.argv)<2:
        test="/app/pydev_demo/03_instance_segmentation_sample/02_ultralytics_yolo11_seg/bus.jpg"
    else:
        test=sys.argv[1]
    
    m=hbm_runtime.HB_HBMRuntime(MODEL_PATH)
    img=cv2.imread(test)
    if img is None: print(f"ERROR: {test}"); exit(1)
    
    print(f"Image: {test} ({img.shape[1]}x{img.shape[0]})")
    result,n=infer_frame(m, img, test)
    
    out=test.rsplit(".",1)[0]+"_result.jpg"
    cv2.imwrite(out,result)
    print(f"Saved: {out}")
