# -*- coding: utf-8 -*-
"""replicate.py —— W7 结构复刻 · 参考片结构量化（v1.5.5）

**能自动做的**：规格 / 时长 / **镜头数与每镜时长（场景切点检测）** / 平均镜长 / 音频情况
**做不了的（留空待填）**：钩子文案、段落语义、字幕密度（需人看接触表）
⇒ 不假装自动化，只把"可测的"测准。

用法:
    python replicate.py <参考视频> [--scene 0.3] [--out 结构卡.md]
"""

# --- 控制台兼容：中文 Windows 默认 GBK，打印 ✓/✗/⇒/⚠ 会抛 UnicodeEncodeError ---
try:
    import sys as _sys
    _sys.stdout.reconfigure(errors="replace")
    _sys.stderr.reconfigure(errors="replace")
except Exception:
    pass
import io, os, sys, re, json, subprocess, datetime, tempfile, shutil

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def ffmpeg_exe():
    return subprocess.run([sys.executable, "-c", "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())"],
                          capture_output=True, text=True).stdout.strip()


def run(args):
    return subprocess.run(args, capture_output=True, text=True, errors="replace")


def parse_spec(stderr):
    s = {"w": None, "h": None, "fps": None, "duration_s": None, "has_audio": False}
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", stderr)
    if m:
        s["duration_s"] = round(int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)), 3)
    mv = re.search(r"Stream #\d+:\d+.*?: Video: \w+.*?, (\d+)x(\d+).*?, ([\d.]+) fps", stderr)
    if mv:
        s["w"], s["h"], s["fps"] = int(mv.group(1)), int(mv.group(2)), float(mv.group(3))
    s["has_audio"] = bool(re.search(r"Stream #\d+:\d+.*?: Audio:", stderr))
    return s


def scene_cuts(ff, src, thr):
    """场景切点：ffmpeg select=gt(scene,T) + showinfo ⇒ pts_time 列表"""
    r = run([ff, "-hide_banner", "-i", src, "-vf", "select='gt(scene,%s)',showinfo" % thr,
             "-an", "-f", "null", "-"])
    times = [float(x) for x in re.findall(r"pts_time:([\d.]+)", r.stderr)]
    return sorted(set(round(t, 3) for t in times))


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: replicate.py <ref_video> [--scene T] [--out md]"}, ensure_ascii=False))
        return 2
    src = sys.argv[1]
    thr = 0.3
    out_md = None
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--scene":
            thr = float(sys.argv[i + 1]); i += 2
        elif sys.argv[i] == "--out":
            out_md = sys.argv[i + 1]; i += 2
        else:
            i += 1
    if not os.path.isfile(src):
        print(json.dumps({"error": "file not found", "file": src}, ensure_ascii=False))
        return 2

    FF = ffmpeg_exe()
    spec = parse_spec(run([FF, "-hide_banner", "-i", src]).stderr)
    dur = spec["duration_s"] or 0.0
    cuts = scene_cuts(FF, src, thr)
    bounds = [0.0] + [c for c in cuts if 0.0 < c < dur] + [dur]
    shots = []
    for a, b in zip(bounds, bounds[1:]):
        if b - a >= 0.05:
            shots.append({"start": round(a, 2), "end": round(b, 2), "dur": round(b - a, 2)})
    avg = round(sum(s["dur"] for s in shots) / len(shots), 2) if shots else None

    # 接触表（供人填语义/字幕密度）
    tmp = tempfile.mkdtemp(prefix="repl_")
    seq = os.path.join(tmp, "f%05d.png")
    fps_pick = min(2.0, 60 / dur) if dur > 30 else 2.0
    run([FF, "-hide_banner", "-i", src, "-vf", "fps=%g" % fps_pick, "-y", seq])
    pngs = sorted([os.path.join(tmp, f) for f in os.listdir(tmp) if f.endswith(".png")])
    sheet = None
    if pngs:
        try:
            from PIL import Image, ImageDraw
            picks = pngs[:: max(1, len(pngs) // 16)][:16]
            ims = []
            for p in picks:
                im = Image.open(p).convert("RGB"); im.thumbnail((280, 500)); ims.append(im)
            if ims:
                cw, ch = ims[0].width, ims[0].height
                cols = 4
                rows = (len(ims) + cols - 1) // cols
                sh = Image.new("RGB", (cols * cw, rows * ch), (20, 20, 24))
                d = ImageDraw.Draw(sh)
                for k, im in enumerate(ims):
                    x, y = (k % cols) * cw, (k // cols) * ch
                    sh.paste(im, (x, y)); d.text((x + 4, y + 4), "#%d" % k, fill=(255, 220, 0))
                sheet = src + ".refsheet.png"
                sh.save(sheet)
        except Exception:
            pass
    shutil.rmtree(tmp, ignore_errors=True)

    rep = {
        "ref_file": src, "checked_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "spec": spec,
        "scene_threshold": thr,
        "shot_count": len(shots),
        "avg_shot_len_s": avg,
        "shots": shots,
        "contact_sheet": sheet,
        "auto_covered": ["规格", "时长", "镜头数", "每镜时长", "平均镜长", "音频有无", "接触表"],
        "must_fill_by_human": ["钩子逐字（0-3s 说了什么）", "各段落语义", "字幕密度（看接触表数）", "BGM 情绪"],
        "rule": "本脚本只量化**结构**，不判断内容好坏，也不判断“为什么这条火了”。",
    }
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    try:
        open(src + ".refstruct.json", "w", encoding="utf-8").write(json.dumps(rep, ensure_ascii=False, indent=1))
    except Exception:
        pass

    if out_md:
        md = ["# 参考片 · 结构量化（W7-S2 自动部分）", "",
              "| 项 | 值 |", "|---|---|",
              "| 参考片 | `%s` |" % os.path.basename(src),
              "| 分辨率 / 帧率 | %s×%s @%s fps |" % (spec["w"], spec["h"], spec["fps"]),
              "| 时长 | **%s s** |" % dur,
              "| **镜头数** | **%d** |" % len(shots),
              "| **平均镜长** | **%s s** |" % avg,
              "| 音轨 | %s |" % ("有" if spec["has_audio"] else "无"),
              "| 接触表 | `%s` |" % (os.path.basename(sheet) if sheet else "未生成"),
              "", "## 逐镜（场景切点阈值 %s）" % thr, "",
              "| # | 起 | 止 | 时长 |", "|---|---|---|---|"]
        for k, s in enumerate(shots[:60], 1):
            md.append("| %d | %.2f | %.2f | **%.2f** |" % (k, s["start"], s["end"], s["dur"]))
        if len(shots) > 60:
            md.append("| … | 共 %d 镜（仅列前 60） | | |" % len(shots))
        md += ["", "## ★ 以下必须人工/AI 填（脚本做不了）", "",
               "- [ ] **钩子逐字**（0–3 s 说了什么、拍了什么）",
               "- [ ] **各段落语义**（冲突/痛点 → 主体几段 → CTA）",
               "- [ ] **字幕密度**（看接触表数：每镜几个字 / 几字每秒）",
               "- [ ] **BGM 情绪**（激昂/温柔/悬疑…）",
               "", "> **判据**：结构可学，**文案/画面/BGM 必须换**（换骨不换肉）。", ""]
        open(out_md, "w", encoding="utf-8").write("\n".join(md))
        print("\n  结构卡已写：%s" % out_md, file=sys.stderr)

    return 0


if __name__ == "__main__":
    # --- 统一 --help：打印本文件用法说明后退出（陌生环境下第一条命令往往就是它）---
    import sys as _helpsys
    if any(_a in ("-h", "--help", "help") for _a in _helpsys.argv[1:]):
        print((__doc__ or "").strip() or "（本工具无文档字符串）")
        raise SystemExit(0)

    sys.exit(main())
