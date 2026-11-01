# -*- coding: utf-8 -*-
"""extract_reference.py —— 参考片拆解（v1.6.0 工程一）

输入一段参考视频，自动产出：
  ① 结构指标（调 replicate.py：镜头数/每镜时长/平均镜长）
  ② 软字幕流（若有）→ srt
  ③ 音轨 → wav（供转录用）
  ④ 接触表（供人读字幕/画面）
  ⑤ 结构卡骨架（钩子/冲突/反转/CTA，语义部分留空待 AI/人填）

**诚实边界**：本地**无 OCR 能力** ⇒ 硬字幕（烧在画面上的）**读不出文字**，只能给人看接触表。
有软字幕流则直接抽；有旁白则抽音轨交转录。
"""

# --- 控制台兼容：中文 Windows 默认 GBK，打印 ✓/✗/⇒/⚠ 会抛 UnicodeEncodeError ---
try:
    import sys as _sys
    _sys.stdout.reconfigure(errors="replace")
    _sys.stderr.reconfigure(errors="replace")
except Exception:
    pass
import io, os, sys, json, subprocess, tempfile, shutil

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))


def ff():
    return subprocess.run([sys.executable, "-c", "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())"],
                          capture_output=True, text=True).stdout.strip()


def run(a):
    return subprocess.run(a, capture_output=True, text=True, errors="replace")


def main():
    if len(sys.argv) < 2:
        print("usage: extract_reference.py <ref_video> [--outdir DIR] [--scene 0.3]")
        return 2
    src = sys.argv[1]
    outdir = os.path.join(os.path.dirname(os.path.abspath(src)), "_refextract")
    thr = "0.3"
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--outdir":
            outdir = sys.argv[i + 1]; i += 2
        elif sys.argv[i] == "--scene":
            thr = sys.argv[i + 1]; i += 2
        else:
            i += 1
    if not os.path.isfile(src):
        print(json.dumps({"error": "not found", "file": src}, ensure_ascii=False)); return 2
    os.makedirs(outdir, exist_ok=True)
    base = os.path.splitext(os.path.basename(src))[0]
    F = ff()
    rep = {"ref": src, "outdir": outdir}

    # ① 结构指标（复用 replicate.py）
    r = run([sys.executable, os.path.join(HERE, "replicate.py"), src, "--scene", thr,
             "--out", os.path.join(outdir, "结构卡_自动.md")])
    try:
        s = json.loads(r.stdout)
        rep["structure"] = {"shots": s["shot_count"], "avg_len_s": s["avg_shot_len_s"],
                            "duration_s": s["spec"]["duration_s"], "spec": s["spec"]}
    except Exception:
        rep["structure"] = {"error": "replicate.py failed", "stderr": r.stderr[-300:]}

    # ② 软字幕流（若有）
    srts = []
    probe = run([F, "-hide_banner", "-i", src])
    has_sub = "Subtitle:" in probe.stderr
    if has_sub:
        for k in range(3):
            dst = os.path.join(outdir, "%s_sub%d.srt" % (base, k))
            rr = run([F, "-hide_banner", "-i", src, "-map", "0:s:%d" % k, "-c:s", "srt", "-y", dst])
            if os.path.isfile(dst) and os.path.getsize(dst) > 0:
                srts.append(dst)
    rep["soft_subtitles"] = {"found": has_sub, "files": [os.path.basename(x) for x in srts]}

    # ③ 音轨 → wav（供转录）
    wav = os.path.join(outdir, "%s_audio.wav" % base)
    has_audio = "Audio:" in probe.stderr
    if has_audio:
        run([F, "-hide_banner", "-i", src, "-vn", "-ac", "1", "-ar", "16000", "-y", wav])
    rep["audio"] = {"found": has_audio,
                    "wav": os.path.basename(wav) if (has_audio and os.path.isfile(wav)) else None,
                    "note": "用 AudioTranscribe 转录此 wav 可得旁白文案" if has_audio else "无音轨"}

    # ④ 接触表（replicate.py 已生成 .refsheet.png，复制进来）
    sheet = src + ".refsheet.png"
    if os.path.isfile(sheet):
        dst = os.path.join(outdir, "接触表.png")
        shutil.copyfile(sheet, dst)
        rep["contact_sheet"] = "接触表.png"

    # ⑤ 结构卡骨架
    card = os.path.join(outdir, "结构卡_待填.md")
    md = """# 《爆款结构卡》（v1.6.0 · 骨架）

> 参考片：`%s`
> 自动部分见 `结构卡_自动.md`（镜头数/镜长）。**以下语义部分必须 AI/人填。**

## 一、四段结构（填这个）

| 段落 | 时间 | 说了什么（逐字） | 拍了什么 | 可复用点 |
|---|---|---|---|---|
| **钩子** | 0–3 s | | | |
| **冲突/痛点** | 3–8 s | | | |
| **反转/转折** | __ s | | | |
| **CTA** | 末 __ s | | | |

## 二、四个数（自动部分照抄）

- 镜头数：__ ｜ 平均镜长：__ s
- 字幕密度：__ 字/秒（看接触表数）
- BGM 情绪：__

## 三、★ 新拍法建议（这才是客户要的）

| 参考片的做法 | 换成你的产品怎么做 | 需要什么素材 |
|---|---|---|
| 钩子用了「__」 | 换成「__」 | |
| 冲突用了「__」 | 换成「__」 | |
| 反转用了「__」 | 换成「__」 | |
| CTA 用了「__」 | 换成「__」 | |

## 四、★ 边界（W7 铁律，不许跳过）

- **拆结构不抄文案**：上面"换成"必须是你自己的句子
- **学镜头不抄画面**：画面必须用你自己的素材
- **BGM 不用原片**：只能同情绪重制

""" % os.path.basename(src)
    open(card, "w", encoding="utf-8").write(md)
    rep["structure_card"] = os.path.basename(card)

    rep["covered"] = ["结构指标（镜头数/镜长）", "软字幕流（若有）", "音轨提取", "接触表", "结构卡骨架"]
    rep["NOT_covered"] = ["硬字幕文字（本地无 OCR）", "BGM 曲名/版权", "画面语义（需人看接触表）"]
    rep["rule"] = "硬字幕读不出：请让 AI/人看接触表逐格读，或用 AudioTranscribe 转录旁白。"

    print(json.dumps(rep, ensure_ascii=False, indent=1))
    json.dump(rep, open(os.path.join(outdir, "_extract.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    # --- 统一 --help：打印本文件用法说明后退出（陌生环境下第一条命令往往就是它）---
    import sys as _helpsys
    if any(_a in ("-h", "--help", "help") for _a in _helpsys.argv[1:]):
        print((__doc__ or "").strip() or "（本工具无文档字符串）")
        raise SystemExit(0)

    sys.exit(main())
