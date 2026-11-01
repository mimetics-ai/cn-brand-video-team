# -*- coding: utf-8 -*-
"""media_check.py —— 素材体检（v1.5.2）

**能稳做的自动做，不稳的给你看，不假装自动。**

自动（可靠）: 规格 / 音轨 / 时长 / 黑边比例 / 抽帧接触表
**不自动**: 硬字幕判定 —— 改为**生成接触表让你一眼看**，并明写"该层未自动覆盖"

设计取舍（本轮实测）：亮度阈值法检测硬字幕**不可靠** ——
- 不设高度上限 ⇒ 底部固定水印因"跨帧 100% 命中"被误判成字幕带（实测报到 y=1850）
- 设上限后 ⇒ 真字幕因"有窗（部分帧无字）"过不了 60% 投票门槛 ⇒ 漏检
- 两难无解 ⇒ **放弃自动判定，改给接触表**（比一个可能错的数字有用）

用法:
    python media_check.py <素材> [--grid 16] [--out report.md]
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
    s = {"w": None, "h": None, "fps": None, "duration_s": None, "has_audio": False,
         "audio_rate": None, "audio_channels": None, "video_codec": None, "bitrate_kbps": None,
         "pix_fmt": None, "sar": None}
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", stderr)
    if m:
        s["duration_s"] = round(int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)), 3)
    mv = re.search(r"Stream #\d+:\d+.*?: Video: (\w+).*?, ([a-z0-9]+)(?:\([^)]*\))?, (\d+)x(\d+)(.*?), ([\d.]+) fps", stderr)
    if mv:
        s["video_codec"] = mv.group(1)
        s["pix_fmt"] = mv.group(2)
        s["w"], s["h"] = int(mv.group(3)), int(mv.group(4))
        ms = re.search(r"SAR (\d+:\d+)", mv.group(5) or "")
        if ms:
            s["sar"] = ms.group(1)
        s["fps"] = float(mv.group(6))
    ma = re.search(r"Stream #\d+:\d+.*?: Audio: \w+.*?, (\d+) Hz, (\w+)", stderr)
    if ma:
        s["has_audio"], s["audio_rate"], s["audio_channels"] = True, int(ma.group(1)), ma.group(2)
    mb = re.search(r"bitrate:\s*(\d+) kb/s", stderr)
    if mb:
        s["bitrate_kbps"] = int(mb.group(1))
    return s


def black_borders(paths):
    """四边黑边比例（这项可靠：纯黑均值极低，几乎不会误判）"""
    from PIL import Image
    import numpy as np
    hits = {"top": 0, "bottom": 0, "left": 0, "right": 0}
    n = 0
    for p in paths:
        try:
            a = np.asarray(Image.open(p).convert("L"), dtype=np.uint8)
        except Exception:
            continue
        fh, fw = a.shape
        n += 1
        if float(a[: int(fh * 0.12), :].mean()) < 18.0:
            hits["top"] += 1
        if float(a[int(fh * 0.88):, :].mean()) < 18.0:
            hits["bottom"] += 1
        if float(a[:, : int(fw * 0.12)].mean()) < 18.0:
            hits["left"] += 1
        if float(a[:, int(fw * 0.88):].mean()) < 18.0:
            hits["right"] += 1
    return {k: round(v / max(1, n), 2) for k, v in hits.items()}


def make_contact_sheet(paths, out_png, cols=4):
    """接触表：让 AI/人一眼看全片有没有字幕、在哪个位置"""
    from PIL import Image, ImageDraw
    if not paths:
        return None
    picks = paths[:: max(1, len(paths) // (cols * cols))][: cols * cols]
    ims = []
    for p in picks:
        try:
            im = Image.open(p).convert("RGB")
        except Exception:
            continue
        im.thumbnail((280, 500))
        ims.append(im)
    if not ims:
        return None
    cw, ch = ims[0].width, ims[0].height
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cw, rows * ch), (20, 20, 24))
    d = ImageDraw.Draw(sheet)
    for i, im in enumerate(ims):
        x, y = (i % cols) * cw, (i // cols) * ch
        sheet.paste(im, (x, y))
        d.text((x + 4, y + 4), "#%d" % i, fill=(255, 220, 0))
    sheet.save(out_png)
    return out_png


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: media_check.py <file> [--grid N] [--out md]"}, ensure_ascii=False))
        return 2
    src = sys.argv[1]
    out_md = None
    grid = 16
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--out":
            out_md = sys.argv[i + 1]; i += 2
        elif sys.argv[i] == "--grid":
            grid = int(sys.argv[i + 1]); i += 2
        else:
            i += 1

    if not os.path.isfile(src):
        print(json.dumps({"error": "file not found", "file": src}, ensure_ascii=False))
        return 2

    FF = ffmpeg_exe()
    r = run([FF, "-hide_banner", "-i", src])
    spec = parse_spec(r.stderr)
    rep = {"file": src, "bytes": os.path.getsize(src),
           "checked_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
           "spec": spec}

    # 抽帧（一次 fps 抽取，供黑边判定与接触表）
    tmp = tempfile.mkdtemp(prefix="mcheck_")
    dur = spec["duration_s"] or 1
    fps_pick = min(2.0, 60 / dur) if dur > 30 else 2.0
    seq = os.path.join(tmp, "f%05d.png")
    run([FF, "-hide_banner", "-i", src, "-vf", "fps=%g" % fps_pick, "-y", seq])
    paths = sorted([os.path.join(tmp, f) for f in os.listdir(tmp) if f.endswith(".png")])
    rep["frames_sampled"] = len(paths)

    rep["black_border_ratio"] = black_borders(paths) if paths else None
    sheet = make_contact_sheet(paths, src + ".contact_sheet.png", cols=4)
    rep["contact_sheet"] = sheet

    # 判定与建议（只做能确定的）
    warn, todo = [], []
    if not spec["has_audio"]:
        warn.append("**无音轨** —— 需另配 BGM / 旁白")
    if rep["black_border_ratio"] and max(rep["black_border_ratio"].values()) > 0.5:
        sides = [k for k, v in rep["black_border_ratio"].items() if v > 0.5]
        warn.append("存在黑边（%s）⇒ 可直接裁掉" % "、".join(sides))
    if spec["sar"] and spec["sar"] != "1:1":
        warn.append("SAR=%s ⇒ 画面会变形，需校正" % spec["sar"])

    todo.append("**硬字幕：本脚本不自动判定**（实测亮度阈值法不可靠）⇒ 请看 `%s` 接触表目检"
                % (os.path.basename(sheet) if sheet else "(未生成)"))

    rep["verdict"] = {"warnings": warn, "manual_checks_required": todo,
                      "auto_covered": ["规格", "音轨", "时长", "黑边", "接触表"],
                      "not_auto_covered": ["硬字幕位置与空档", "画面内容合规", "人脸"]}
    s = json.dumps(rep, ensure_ascii=False, indent=1)
    print(s)
    try:
        open(src + ".mediacheck.json", "w", encoding="utf-8").write(s)
    except Exception:
        pass
    shutil.rmtree(tmp, ignore_errors=True)

    if out_md:
        md = ["# 素材体检报告", "",
              "| 项 | 值 |", "|---|---|",
              "| 文件 | `%s` |" % os.path.basename(src),
              "| 体积 | %.1f MB |" % (rep["bytes"] / 1048576),
              "| 分辨率 | %s×%s |" % (spec["w"], spec["h"]),
              "| 帧率 | %s fps |" % spec["fps"],
              "| 时长 | %s s |" % spec["duration_s"],
              "| 音轨 | %s |" % ("有（%s Hz %s）" % (spec["audio_rate"], spec["audio_channels"]) if spec["has_audio"] else "**无**"),
              "| 黑边比例 | %s |" % rep["black_border_ratio"],
              "", "## 需要你看的", ""]
        md += ["- " + t for t in todo]
        md += ["", "## 自动确定的结论", ""]
        md += ["- ⚠ " + w if w else "- ✅ 规格/音轨/黑边均正常" for w in (warn or [""])]
        md += ["", "## 未覆盖（本脚本不做）", ""]
        md += ["- " + x for x in rep["verdict"]["not_auto_covered"]]
        open(out_md, "w", encoding="utf-8").write("\n".join(md))
        print("\n  报告已写：%s" % out_md, file=sys.stderr)

    return 0


if __name__ == "__main__":
    # --- 统一 --help：打印本文件用法说明后退出（陌生环境下第一条命令往往就是它）---
    import sys as _helpsys
    if any(_a in ("-h", "--help", "help") for _a in _helpsys.argv[1:]):
        print((__doc__ or "").strip() or "（本工具无文档字符串）")
        raise SystemExit(0)

    sys.exit(main())
