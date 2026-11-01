# -*- coding: utf-8 -*-
"""
宣传片分镜 · 抽帧 + 人脸存在性筛查（客观判据）

用法:
  python _frames_facecheck.py <视频> <输出目录> [--save N] [--model <onnx>]

三件事:
  1) 读取视频参数（fps / 帧数 / 分辨率 / 时长 / 体积）
  2) 每 0.25 s 抽一帧跑人脸检测（优先 YuNet DNN，回退 Haar 级联），统计命中
  3) 均匀导出 N 张关键帧 PNG 供人工目检

⚠️ 本机实测（2026-09-26）:
   - opencv-python-headless 5.0.0 已移除 cv2.CascadeClassifier，且 cv2.data 不再分发 haarcascade XML
   - 故主检测器改用 cv2.FaceDetectorYN（YuNet），模型须另行下载
⚠️ 非 ASCII 路径: OpenCV C++ 层读不了中文路径 → 先复制到 ASCII 临时目录；
   写图用 imencode + open()，避开 cv2.imwrite。
"""

# --- 控制台兼容：中文 Windows 默认 GBK，打印 ✓/✗/⇒/⚠ 会抛 UnicodeEncodeError ---
try:
    import sys as _sys
    _sys.stdout.reconfigure(errors="replace")
    _sys.stderr.reconfigure(errors="replace")
except Exception:
    pass
import os
import sys
import shutil
import tempfile

import cv2
import numpy as np

HAAR_DIR = os.path.join(os.path.dirname(cv2.__file__), "data")


def build_detector(model, w, h):
    """返回 (名称, setInputSize_fn, detect_fn)；失败返回 None。"""
    if model and os.path.isfile(model):
        for name in ("create",):
            fn = getattr(cv2.FaceDetectorYN, name, None)
            if fn:
                try:
                    det = fn(model, "", (w, h), 0.5, 0.3, 5000)
                    if det is not None:
                        return ("YuNet(DNN)", lambda s: det.setInputSize(s),
                                lambda fr: det.detect(fr)[1])
                except Exception as e:
                    print("  ! YuNet 初始化失败: %s" % e)
        fn2 = getattr(cv2, "FaceDetectorYN_create", None)
        if fn2:
            try:
                det = fn2(model, "", (w, h), 0.5, 0.3, 5000)
                if det is not None:
                    return ("YuNet(DNN)", lambda s: det.setInputSize(s),
                            lambda fr: det.detect(fr)[1])
            except Exception as e:
                print("  ! YuNet(_create) 初始化失败: %s" % str(e)[:160])
    # --- Haar 回退 ---
    if hasattr(cv2, "CascadeClassifier"):
        cf = os.path.join(HAAR_DIR, "haarcascade_frontalface_default.xml")
        cp = os.path.join(HAAR_DIR, "haarcascade_profileface.xml")
        if os.path.isfile(cf):
            c1 = cv2.CascadeClassifier(cf)
            c2 = cv2.CascadeClassifier(cp) if os.path.isfile(cp) else None

            def _det(fr):
                g = cv2.equalizeHist(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY))
                d = list(c1.detectMultiScale(g, 1.1, 5, minSize=(36, 36)))
                if c2 is not None:
                    d += list(c2.detectMultiScale(g, 1.1, 5, minSize=(36, 36)))
                return np.array(d) if d else None
            return ("Haar(cascade)", lambda s: None, _det)
    return None


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2

    src = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2])
    n_save, model = 6, None
    if "--save" in sys.argv:
        n_save = int(sys.argv[sys.argv.index("--save") + 1])
    if "--model" in sys.argv:
        model = sys.argv[sys.argv.index("--model") + 1]

    if not os.path.isfile(src):
        print("!! 找不到视频: %s" % src)
        return 2

    tmp = os.path.join(tempfile.gettempdir(), "ymj_frames")
    os.makedirs(tmp, exist_ok=True)
    tmp_src = os.path.join(tmp, "src.mp4")
    shutil.copyfile(src, tmp_src)

    cap = cv2.VideoCapture(tmp_src)
    if not cap.isOpened():
        print("!! 无法打开视频")
        return 2

    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    nfr = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    dur = (nfr / fps) if fps else 0.0

    print("== 视频参数 ==")
    print("  时长   = %.2f s" % dur)
    print("  帧率   = %.3f fps" % fps)
    print("  帧数   = %d" % nfr)
    print("  分辨率 = %dx%d" % (w, h))
    print("  体积   = %d B" % os.path.getsize(src))

    # ⚠️ OpenCV 的 ONNX 加载器同样读不了中文路径 → 模型也复制到 ASCII 临时目录
    if model and os.path.isfile(model) and not model.isascii():
        m2 = os.path.join(tmp, "yunet.onnx")
        shutil.copyfile(model, m2)
        print("  (模型已复制到 ASCII 路径: %s)" % m2)
        model = m2

    det = build_detector(model, w, h)
    if det is None:
        print("\n!! 无可用人脸检测器（无模型且无级联）—— 仅抽帧，须人工目检")
    else:
        aname, set_size, detect = det
        print("\n== 人脸筛查（每 0.25s，检测器 = %s）==" % aname)
        set_size((w, h))
        step, t, n_samp, hits = 0.25, 0.0, 0, []
        while t <= dur + 1e-6:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, fr = cap.read()
            if not ok:
                break
            n_samp += 1
            faces = detect(fr)
            k = 0 if faces is None else len(faces)
            if k:
                conf = float(np.max(faces[:, -1])) if faces.shape[1] >= 15 else float("nan")
                hits.append((round(t, 2), k, conf))
            t += step
        print("  采样帧数 = %d" % n_samp)
        if not hits:
            print("  命中 = 0  →  【无面部检测命中】")
        else:
            print("  命中 = %d 处:" % len(hits))
            for tt, k, c in hits:
                print("    t=%.2fs  框数=%d  最高置信=%.3f" % (tt, k, c))

    os.makedirs(out, exist_ok=True)
    saved = []
    for i in range(n_save):
        tt = dur * (i / max(n_save - 1, 1)) * 0.995
        cap.set(cv2.CAP_PROP_POS_MSEC, tt * 1000.0)
        ok, fr = cap.read()
        if not ok:
            continue
        p = os.path.join(out, "k%02d_t%05.2f.png" % (i, tt))
        ok2, buf = cv2.imencode(".png", fr)
        if ok2:
            with open(p, "wb") as f:
                f.write(buf.tobytes())
            saved.append((os.path.basename(p), os.path.getsize(p)))

    print("\n== 导出关键帧 ==")
    for nm, sz in saved:
        print("  %s  (%d B)" % (nm, sz))

    cap.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
