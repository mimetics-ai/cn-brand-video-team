# -*- coding: utf-8 -*-
"""
structure_card.py —— 爆款结构卡 v1.7-d（七层模块化拆解 + 槽位复用变体生成）

七层（用户拍板，槽位全部可替换）：
  1 hook          钩子：首镜时长/首个切点/开场声压/开场运动量
  2 beats         节拍：切点表 + 每拍时长（结构骨架，变体只换内容不动拍）
  3 visual_grammar 画面语法：画幅方向/亮度走势/饱和度/运动量（Ken Burns 或实拍运动代理）
  4 subtitle_style 字幕样式：文字带密度窗（自动观测）+ 字体/落位（人工确认位）
  5 broll_rules   B-roll 规则：每 10s 切点数/镜长分布/蒙太奇判定
  6 fx_sound      特效音效：响度峰/静音窗/声音起点/BGM 常驻判定
  7 pacing        节奏参数：每 10s 切点数/逐秒响度曲线/能量峰谷

用法：
  python structure_card.py analyze --video ref.mp4 --out card.json [--name X]
  python structure_card.py analyze --text copy.txt --out card.json [--rate 4.5]
  python structure_card.py variants --card card.json --product "某防水品牌A" \
        --category "家装防水涂料" --feature "水性配方；按规范施工形成连续防水层；屋面施工" \
        --cta "某防水品牌A" --n 2 --outdir variants [--duration 30] [--scan]
  python structure_card.py md --card card.json [--out card.md]

纪律：
  - 结构复用是硬承诺：变体脚本的节拍表 = 卡片节拍表（可整体缩放，不许改拍数）
  - 变体文案经 banword_scan_local（--scan）硬扫，hard 命中 ⇒ rc=3 不出稿
  - 本工具只做可度量观测；字体/位置/情绪类槽位标「需人工确认」，不冒充自动结论
"""

# --- 控制台兼容：中文 Windows 默认 GBK，打印 ✓/✗/⇒/⚠ 会抛 UnicodeEncodeError ---
try:
    import sys as _sys
    _sys.stdout.reconfigure(errors="replace")
    _sys.stderr.reconfigure(errors="replace")
except Exception:
    pass
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np

SCHEMA = "structure-card/1.0"
LAYERS = ["hook", "beats", "visual_grammar", "subtitle_style", "broll_rules", "fx_sound", "pacing"]

# 禁词扫描器：与 structure_card.py 同目录，按相对位置解析（可整体搬目录/改名）
BANWORD_TOOL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "banword_scan_local.py")


def _ff():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _sh(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, errors="replace", **kw)


def probe(path):
    r = _sh([_ff(), "-hide_banner", "-i", path])
    s = r.stderr
    d = re.search(r"Duration: (\d+):(\d+):([\d.]+)", s)
    v = re.search(r"Video: .*?(\d{2,5})x(\d{2,5})", s)
    fps = re.search(r"([\d.]+) fps", s)
    dur = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3)) if d else 0
    w, h = (int(v.group(1)), int(v.group(2))) if v else (0, 0)
    return dur, w, h, float(fps.group(1)) if fps else None


def scene_cuts(path, thresh=0.2, max_shots=40):
    r = _sh([_ff(), "-i", path, "-vf", "select='gt(scene,%s)',showinfo" % thresh, "-f", "null", "-"])
    ts = [float(x) for x in re.findall(r"pts_time:([0-9.]+)", r.stderr)]
    ts = sorted(t for t in ts if 0.05 < t)
    return ts[:max_shots - 1]


def audio_rms(path, win=0.5):
    """返回 (win 秒粒度的 RMS 列表, sr)。"""
    p = subprocess.run([_ff(), "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                       capture_output=True)
    x = np.frombuffer(p.stdout, dtype=np.float32)
    n = int(16000 * win)
    m = len(x) // n
    rms = [float(np.sqrt(np.mean(x[i * n:(i + 1) * n] ** 2)) + 1e-9) for i in range(m)]
    return rms, win


def _frames(path, times, tmpdir):
    """取若干时间点的缩略帧，返回 [(t, np.ndarray RGB)]。"""
    out = []
    for t in times:
        fp = os.path.join(tmpdir, "f_%08d.jpg" % int(t * 1000))
        r = _sh([_ff(), "-y", "-ss", "%.3f" % t, "-i", path, "-frames:v", "1",
                 "-vf", "scale=160:-1", "-q:v", "5", fp])
        if r.returncode == 0 and os.path.exists(fp):
            from PIL import Image
            out.append((t, np.asarray(Image.open(fp).convert("RGB"))))
            os.remove(fp)
    return out


def _frame_metrics(img):
    """亮度/饱和度/文字带比值（下 22% 边缘密度 vs 中带）。"""
    g = img.mean(axis=2)
    sat = (img.max(axis=2).astype(int) - img.min(axis=2).astype(int)).mean()
    gy, gx = np.gradient(g)
    edge = np.sqrt(gx ** 2 + gy ** 2)
    h = g.shape[0]
    band_bottom = edge[int(h * 0.78):, :].mean() + 1e-6
    band_mid = edge[int(h * 0.35):int(h * 0.65), :].mean() + 1e-6
    return {"brightness": round(float(g.mean()), 1), "saturation": round(float(sat), 1),
            "text_band_ratio": round(float(band_bottom / band_mid), 2)}


def _motion(path, t0, t1, tmpdir):
    """同镜内两点灰度 MAD（运动量代理；Ken Burns/运镜/实拍运动均会抬高）。"""
    a = _frames(path, [t0], tmpdir)
    b = _frames(path, [t0 + max(0.2, (t1 - t0) * 0.6)], tmpdir)
    if not a or not b:
        return None
    ga = a[0][1].mean(axis=2)
    gb = b[0][1].mean(axis=2)
    if ga.shape != gb.shape:
        return None
    return round(float(np.abs(ga - gb).mean()), 2)


def analyze_video(path, name, scene_thresh=0.2):
    dur, w, h, fps = probe(path)
    cuts = scene_cuts(path, thresh=scene_thresh)
    bounds = [0.0] + cuts + ([dur] if dur else [])
    shots = [{"i": i, "t0": round(bounds[i], 3), "t1": round(bounds[i + 1], 3),
              "dur": round(bounds[i + 1] - bounds[i], 3)} for i in range(len(bounds) - 1)]
    rms, win = audio_rms(path)
    rmax = max(rms) if rms else 0
    peaks = [round(i * win, 2) for i in range(1, len(rms) - 1)
             if rms[i] > rms[i - 1] and rms[i] >= rms[i + 1] and rms[i] > 1.6 * np.mean(rms)]
    sils, s0 = [], None
    for i, v in enumerate(rms):
        if v < 0.02 * rmax:
            s0 = s0 if s0 is not None else i
        elif s0 is not None:
            if (i - s0) * win >= 0.4:
                sils.append([round(s0 * win, 2), round(i * win, 2)])
            s0 = None
    tmpdir = tempfile.mkdtemp(prefix="sca_", dir=r"C:\temp_e1")
    fm, motion = [], []
    for s in shots:
        ts = min(s["t0"] + min(0.4, s["dur"] * 0.3), max(0.0, dur - 0.1))
        fr = _frames(path, [ts], tmpdir)
        fm.append(_frame_metrics(fr[0][1]) if fr else {})
        motion.append(_motion(path, s["t0"], s["t1"], tmpdir))
    shutil_rmtree(tmpdir)
    durs = [s["dur"] for s in shots]
    durs_sorted = sorted(durs)
    med = durs_sorted[len(durs_sorted) // 2] if durs_sorted else 0
    text_windows = []
    cur = None
    for s, f in zip(shots, fm):
        hot = f.get("text_band_ratio", 0) > 1.6
        if hot and cur is None:
            cur = [s["t0"], s["t1"]]
        elif hot and cur:
            cur[1] = s["t1"]
        elif cur:
            text_windows.append(cur)
            cur = None
    if cur:
        text_windows.append(cur)
    first3 = float(np.mean(rms[:6])) if len(rms) >= 6 else 0
    overall = float(np.mean(rms)) if rms else 0
    rms_curve = [round(float(np.mean(rms[i:i + 10])), 4) for i in range(0, len(rms), 10)]
    layers = {
        "hook": {"observed": {"first_shot_dur": durs[0] if durs else 0,
                              "first_cut_t": cuts[0] if cuts else None,
                              "first3s_rms_vs_mean": round(first3 / (overall + 1e-9), 2),
                              "first_shot_motion": motion[0] if motion else None},
                 "slot": {"pattern": "需人工确认（悬念/利益/冲突/奇观）", "first_shot_budget_s": durs[0] if durs else 0},
                 "note": "开场声压/运动量只作能量观测，钩子类型须人工判读"},
        "beats": {"observed": {"n_shots": len(shots), "cut_times": [round(c, 3) for c in cuts],
                               "shot_durations": [round(x, 3) for x in durs]},
                  "slot": [{"i": s["i"], "dur": s["dur"]} for s in shots],
                  "note": "节拍表=结构骨架；变体只换槽位内容，不改拍数"},
        "visual_grammar": {"observed": {"orientation": "portrait" if h > w else "landscape",
                                        "w": w, "h": h, "fps": fps,
                                        "brightness_trend": [f.get("brightness") for f in fm],
                                        "saturation_mean": round(float(np.mean([f.get("saturation", 0) for f in fm])) or 0, 1),
                                        "motion_per_shot": motion},
                           "slot": {"grammar": "需人工确认（推拉摇移/固定/蒙太奇）"},
                           "note": "运动量为帧差代理：Ken Burns、实拍运镜都会抬高"},
        "subtitle_style": {"observed": {"text_band_ratio_threshold": 1.6,
                                        "text_dense_windows": text_windows},
                           "slot": {"font": "需人工确认", "position": "需人工确认",
                                    "size_ratio": "需人工确认"},
                           "note": "边缘密度只能给『哪里有字』，不能给字体/落位"},
        "broll_rules": {"observed": {"cuts_per_10s": round(len(cuts) / (dur / 10.0), 2) if dur else 0,
                                     "shot_len_p25": durs_sorted[len(durs_sorted) // 4] if durs_sorted else 0,
                                     "shot_len_p50": med,
                                     "shot_len_p75": durs_sorted[(len(durs_sorted) * 3) // 4] if durs_sorted else 0},
                        "slot": {"montage": "快剪蒙太奇" if (cuts and len(cuts) / (dur / 10.0) >= 1.5) else "长镜头/少切",
                                 "broll_pool": "按新品 B-roll 清单替换（槽位）"}},
        "fx_sound": {"observed": {"loudness_peaks_t": peaks[:12], "silence_windows": sils[:8],
                                  "rms_floor_vs_peak": round(float(np.mean(rms)) / (rmax + 1e-9), 3)},
                     "slot": {"bgm": "需人工确认（常驻/分段）", "sfx_points": "按峰位人工对位"},
                     "note": "响度峰≈重音/转场/音效落点候选，非音效分类"},
        "pacing": {"observed": {"cuts_per_10s": round(len(cuts) / (dur / 10.0), 2) if dur else 0,
                                "rms_curve_per_5s": rms_curve,
                                "energy_peak_t": round(float(np.argmax(rms)) * win, 2) if rms else None,
                                "energy_min_t": round(float(np.argmin(rms)) * win, 2) if rms else None},
                   "slot": {"target_cuts_per_10s": round(len(cuts) / (dur / 10.0), 2) if dur else 0,
                            "curve_shape": "需人工确认（升/降/双峰）"}},
    }
    card = {"schema": SCHEMA, "name": name or os.path.basename(path), "created": _now(),
            "source": {"type": "video", "path": os.path.abspath(path),
                       "duration": round(dur, 3), "w": w, "h": h, "fps": fps},
            "layers": layers}
    card["hash"] = _card_hash(card)
    return card


def analyze_text(path, rate=4.5, name=None):
    txt = open(path, encoding="utf-8", errors="replace").read()
    sents = [s.strip() for s in re.split(r"[。！？\n]+", txt) if s.strip()]
    t, beats = 0.0, []
    for s in sents:
        dur = round(len(s) / rate + 0.4, 2)
        beats.append({"i": len(beats), "t0": round(t, 2), "dur": dur, "text": s})
        t += dur
    durs = [b["dur"] for b in beats]
    layers = {
        "hook": {"observed": {"first_sentence": sents[0] if sents else "", "first_dur": durs[0] if durs else 0},
                 "slot": {"pattern": "需人工确认", "first_shot_budget_s": durs[0] if durs else 0},
                 "note": "文本模式无音视频证据"},
        "beats": {"observed": {"n_shots": len(beats),
                               "shot_durations": [b["dur"] for b in beats]},
                  "slot": [{"i": b["i"], "dur": b["dur"]} for b in beats],
                  "note": "按语速 %.1f 字/秒估算；拍数=句数" % rate},
        "visual_grammar": {"observed": None, "slot": {"grammar": "文本模式：按新品 B-roll 清单填"},
                           "note": "无视频证据"},
        "subtitle_style": {"observed": None, "slot": {"font": "按 SUBTITLE_SPEC 全局规范",
                                                      "position": "按 SUBTITLE_SPEC 全局规范"},
                           "note": "默认走 lead.md 全局字幕排版规范"},
        "broll_rules": {"observed": None, "slot": {"montage": "文本模式：按节拍密度定",
                                                   "broll_pool": "按新品 B-roll 清单替换"},
                        "note": "无视频证据"},
        "fx_sound": {"observed": None, "slot": {"bgm": "按情绪曲线人工定", "sfx_points": "按节拍人工对位"},
                     "note": "无音频证据"},
        "pacing": {"observed": {"n_sentences": len(sents),
                                "avg_sentence_len": round(float(np.mean([len(s) for s in sents])) or 0, 1)},
                   "slot": {"target_cuts_per_10s": round(len(sents) / ((t or 1) / 10.0), 2)},
                   "note": "由句密度推算"},
    }
    card = {"schema": SCHEMA, "name": name or os.path.basename(path), "created": _now(),
            "source": {"type": "text", "path": os.path.abspath(path),
                       "duration": round(t, 2), "sentences": sents},
            "layers": layers}
    card["hash"] = _card_hash(card)
    return card


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _canon(o):
    return json.dumps(o, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _card_hash(card):
    body = {k: v for k, v in card.items() if k != "hash"}
    return hashlib.sha256(_canon(body).encode("utf-8")).hexdigest()[:16]


def shutil_rmtree(d):
    import shutil
    shutil.rmtree(d, ignore_errors=True)


# ---------------- 变体生成（结构复用 · 槽位替换 · 模板驱动 · 确定性） ----------------

HOOK_POOL = [
    ("悬念", "你有没有注意过，{pain}？"),
    ("过程", "30 秒，看{product}怎么把一件事做对。"),
    ("利益", "{feature0}——{product}先做到这一步。"),
    ("场景", "{scene}，问题就出在这里。"),
]
PAIN_DEFAULT = "问题总藏在不起眼的地方"          # 无极限词（禁词闸实测抓过「最」）
SCENE_DEFAULT = "每一个寻常的角落"


def _fmt_beats(skeleton, total=None):
    durs = [b["dur"] for b in skeleton] if isinstance(skeleton[0], dict) else list(skeleton)
    if total:
        s = sum(durs)
        durs = [round(d * total / s, 2) for d in durs]
        durs[-1] = round(total - sum(durs[:-1]), 2)
    t, out = 0.0, []
    for i, d in enumerate(durs):
        out.append({"i": i, "t0": round(t, 2), "dur": d})
        t += d
    return out


_CALLS = []


def gen_variant(card, beats, product, category, features, cta, tone):
    """按节拍骨架填槽位：钩子池按变体序取式，特性句均摊到中段拍，末拍=CTA。"""
    vi = len(_CALLS)
    _CALLS.append(1)
    hook_style, hook_tpl = HOOK_POOL[vi % len(HOOK_POOL)]
    pain = PAIN_DEFAULT
    scene = SCENE_DEFAULT
    hook = hook_tpl.format(product=product, pain=pain, feature0=features[0] if features else category,
                           scene=scene)
    n = len(beats)
    lines = []
    feats = (features * 10)[:max(0, n - 2)]          # 中段拍均摊特性
    for i, b in enumerate(beats):
        if i == 0:
            vo, pic = hook, "开场镜头：{grammar}，呈现「{topic}」".format(
                grammar=(card["layers"]["visual_grammar"]["slot"].get("grammar") or "按结构卡画面语法"),
                topic=pain)
        elif i < n - 1:
            vo = feats[i - 1] if i - 1 < len(feats) else ("%s，第%d步。" % (product, i))
            pic = "B-roll 槽位 {i}：{broll}".format(i=i, broll=features[min(i - 1, len(features) - 1)] if features else category)
        else:
            vo, pic = cta, "落版：品牌字卡（按 SUBTITLE_SPEC 全局规范）"
        lines.append({"i": i, "t0": b["t0"], "dur": b["dur"], "画面": pic,
                      "旁白": vo, "字幕": vo, "音效": "按结构卡 fx_sound 峰位对位"})
    return {"style": hook_style, "hook": hook, "lines": lines,
            "product": product, "category": category, "cta": cta}


def scan_text_file(path):
    if not os.path.exists(BANWORD_TOOL):
        return {"available": False, "hard": 0, "review": 0, "hits": []}
    r = _sh([sys.executable, BANWORD_TOOL, path, "--json"])
    try:
        data = json.loads(r.stdout[r.stdout.index("{"):])
    except Exception:
        return {"available": True, "hard": -1, "review": 0, "hits": [], "raw": (r.stdout + r.stderr)[-200:]}
    def _n(x):
        return len(x) if isinstance(x, list) else (x or 0)
    return {"available": True, "hard": _n(data.get("hard_count", data.get("hard", 0))),
            "review": _n(data.get("review_count", data.get("review", 0))), "hits": data.get("hits", [])}


def cmd_analyze(args):
    if args.video:
        card = analyze_video(args.video, args.name, args.scene_thresh)
    elif args.text:
        card = analyze_text(args.text, args.rate, args.name)
    else:
        raise SystemExit("analyze 需要 --video 或 --text")
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(card, f, ensure_ascii=False, indent=2)
    print("结构卡 → %s（hash=%s，%s）" % (args.out, card["hash"], card["source"]["type"]))
    b = card["layers"]["beats"]["observed"]
    print("七层：/%s/ ｜ 节拍 %s 拍 ｜ 时长 %ss" % ("/".join(LAYERS), b.get("n_shots"), card["source"].get("duration")))
    return 0


def cmd_variants(args):
    with open(args.card, encoding="utf-8") as f:
        card = json.load(f)
    skeleton = card["layers"]["beats"]["slot"]
    if not skeleton:
        raise SystemExit("卡片无节拍槽位，无法生成变体")
    beats = _fmt_beats(skeleton, args.duration)
    features = [x.strip() for x in re.split(r"[；;]", args.feature or "") if x.strip()]
    os.makedirs(args.outdir, exist_ok=True)
    results = []
    _CALLS.clear()
    for i in range(args.n):
        v = gen_variant(card, beats, args.product, args.category or "", features, args.cta or args.product, args.tone)
        fp = os.path.join(args.outdir, "variant_%d.md" % (i + 1))
        with open(fp, "w", encoding="utf-8") as f:
            f.write(_render_variant_md(card, i + 1, v))
        sc = scan_text_file(fp) if args.scan else {"available": os.path.exists(BANWORD_TOOL), "hard": 0, "review": 0, "hits": []}
        results.append({"file": os.path.abspath(fp), "style": v["style"], "beats": len(beats),
                        "scan": sc})
        print("变体 %d（%s）→ %s ｜ 禁词 hard=%s review=%s"
              % (i + 1, v["style"], fp, sc["hard"], sc["review"]))
    meta = {"schema": "structure-variants/1.0", "card": os.path.abspath(args.card), "card_hash": card["hash"],
            "product": args.product, "cta": args.cta, "duration": args.duration,
            "beat_table": beats, "variants": results,
            "generated": _now()}
    mp = os.path.join(args.outdir, "variants.json")
    with open(mp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print("variants.json → %s（结构复用：拍数 %d 不变，节拍表见内）" % (mp, len(beats)))
    if args.scan and any(isinstance(r["scan"]["hard"], int) and r["scan"]["hard"] > 0 for r in results):
        print("!! 禁词硬命中 —— 变体稿不得交付（rc=3）")
        return 3
    return 0


def _render_variant_md(card, vi, v):
    L = []
    L.append("# 变体脚本 %d · %s（%s式钩子）" % (vi, v["product"], v["style"]))
    L.append("")
    L.append("- 结构复用：结构卡 `%s`（hash %s）｜ 拍数 %d（骨架不动，槽位全换）"
             % (card.get("name"), card.get("hash"), len(v["lines"])))
    L.append("- 产品槽位：product=%s ｜ category=%s ｜ cta=%s" % (v["product"], v["category"] or "-", v["cta"]))
    L.append("")
    L.append("| 拍 | 入点 | 时长 | 画面 | 旁白 | 字幕 | 音效 |")
    L.append("|---|---|---|---|---|---|---|")
    for ln in v["lines"]:
        L.append("| %d | %.2fs | %.2fs | %s | %s | %s | %s |"
                 % (ln["i"] + 1, ln["t0"], ln["dur"], ln["画面"], ln["旁白"], ln["字幕"], ln["音效"]))
    L.append("")
    L.append("> 合规：本稿仅使用建议单口径内的可验证表述；交付前仍须过 Phase 1a 建议单与盲评。")
    return "\n".join(L) + "\n"


def cmd_md(args):
    with open(args.card, encoding="utf-8") as f:
        card = json.load(f)
    out = args.out or os.path.splitext(args.card)[0] + ".md"
    L = ["# 爆款结构卡 · %s" % card["name"], "",
         "- schema %s ｜ hash `%s` ｜ 来源 %s（%ss）"
         % (card["schema"], card["hash"], card["source"]["type"], card["source"].get("duration")), ""]
    titles = {"hook": "① 钩子", "beats": "② 节拍", "visual_grammar": "③ 画面语法",
              "subtitle_style": "④ 字幕样式", "broll_rules": "⑤ B-roll 规则",
              "fx_sound": "⑥ 特效音效", "pacing": "⑦ 节奏参数"}
    for k in LAYERS:
        lay = card["layers"][k]
        L.append("## %s" % titles[k])
        L.append("```json")
        L.append(json.dumps(lay, ensure_ascii=False, indent=1))
        L.append("```")
        L.append("")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("结构卡 MD → %s" % out)
    return 0


def main():
    ap = argparse.ArgumentParser(description="爆款结构卡 v1.7-d（七层模块化拆解＋槽位复用变体）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("analyze")
    p.add_argument("--video"); p.add_argument("--text")
    p.add_argument("--rate", type=float, default=4.5, help="文本模式语速（字/秒）")
    p.add_argument("--scene-thresh", type=float, default=0.2,
                   help="切点判定阈值（0.12 更敏感，软转场多的片建议调低）")
    p.add_argument("--name"); p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_analyze)
    p = sub.add_parser("variants")
    p.add_argument("--card", required=True); p.add_argument("--product", required=True)
    p.add_argument("--category", default=""); p.add_argument("--feature", default="")
    p.add_argument("--cta", default=""); p.add_argument("--tone", default="")
    p.add_argument("--n", type=int, default=2); p.add_argument("--outdir", required=True)
    p.add_argument("--duration", type=float, default=None, help="目标总时长（等比缩放节拍）")
    p.add_argument("--scan", action="store_true", help="变体稿过本地禁词扫描（hard 命中 rc=3）")
    p.set_defaults(func=cmd_variants)
    p = sub.add_parser("md")
    p.add_argument("--card", required=True); p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_md)
    args = ap.parse_args()
    sys.exit(args.func(args) or 0)


if __name__ == "__main__":
    main()
