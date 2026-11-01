# -*- coding: utf-8 -*-
"""video_selfcheck.py —— 视频成片自检（10-26 复盘补）

**一次执行，输出一份结构化 JSON。** AI 只需读一次，不再「跑一项看一项」。

用法:
    python video_selfcheck.py <video> [--frames N] [--duration S] [--probe K]
                                   [--blind N --seed S]
                                   [--expect-ai-mark] [--script plan.json]
                                   [--ratio-max 0.45] [--grid 2.0]

设计要点:
  v1.5.0：全部判据一次跑完一次输出；帧数+响度合并为一次全解码；抽帧一次进程出 K 张
  10-26 复盘补（三条硬规矩落进脚本，不再只是文字要求）：
    ① **AI 标识双取证**（`--expect-ai-mark`）：头信息 + 原始字节两层，缺一层不算过
    ② **帧数对账**（`--script` 里给 segments）：总帧数 == Σ逐段帧数，对不上不许交付
    ③ **旁白占比 + 逐窗 RMS**（`--script` 里给 narration_total_s / windows）：
       占比超 `--ratio-max` 判失败；每个窗口按「该有声/该静音」逐个验

--script 的 JSON 结构（字段都可缺，缺了就跳过对应判据）:
    {
      "film_frames": 2127,
      "segments": [{"name": "u1", "frames": 120}, ...],
      "narration_total_s": 34.9,
      "windows": [{"label": "vo1", "t0": 0.40, "t1": 3.47, "expect": "sound"},
                  {"label": "cup_silence", "t0": 10.8, "t1": 15.0, "expect": "silence"}]
    }
"""

# --- 控制台兼容：中文 Windows 默认 GBK，打印 ✓/✗/⇒/⚠ 会抛 UnicodeEncodeError ---
try:
    import sys as _sys
    _sys.stdout.reconfigure(errors="replace")
    _sys.stderr.reconfigure(errors="replace")
except Exception:
    pass
import io, os, sys, re, json, subprocess, datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# AI 标识的候选键/值（头信息层按字符串搜，字节层按 ASCII 搜）
AI_KEYS = ["Deeptech-Marking", "AI-Generated", "AIGC", "AI生成", "GeneratedBy"]

SOUND_DB = -40.0      # 该有声的窗口：RMS 必须 > 这个值
SILENCE_DB = -60.0    # 该静音的窗口：RMS 必须 < 这个值


def ffmpeg_exe():
    return subprocess.run([sys.executable, "-c",
                           "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())"],
                          capture_output=True, text=True).stdout.strip()


def run(args):
    return subprocess.run(args, capture_output=True, text=True, errors="replace")


def parse_spec(stderr):
    """从 Stream 行解析规格"""
    s = {"w": None, "h": None, "fps": None, "sar": None, "dar": None,
         "pix_fmt": None, "range": None, "colorspace": None,
         "has_audio": False, "audio": None, "duration_hdr": None}
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", stderr)
    if m:
        s["duration_hdr"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    mv = re.search(r"Stream #\d+:\d+.*?: Video: .*?, (.+?), (\d+)x(\d+)(.*?), ([\d.]+) fps", stderr)
    if mv:
        pixinfo, w, h, tail, fps = mv.group(1), int(mv.group(2)), int(mv.group(3)), mv.group(4), float(mv.group(5))
        s["w"], s["h"], s["fps"] = w, h, fps
        mp = re.match(r"([a-z0-9]+)", pixinfo)
        if mp:
            s["pix_fmt"] = mp.group(1)
        mr = re.search(r"\(([^)]*)\)", pixinfo)
        if mr:
            for part in mr.group(1).split(","):
                part = part.strip()
                if part in ("tv", "pc"):
                    s["range"] = part
                elif part.startswith("bt") and not s["colorspace"]:
                    s["colorspace"] = part.split("/")[0]
        ms = re.search(r"SAR (\d+:\d+) DAR (\d+:\d+)", tail or "")
        if ms:
            s["sar"], s["dar"] = ms.group(1), ms.group(2)
    ma = re.search(r"Stream #\d+:\d+.*?: Audio: ([^,]+), (\d+) Hz, (\w+)", stderr)
    if ma:
        s["has_audio"] = True
        s["audio"] = {"codec": ma.group(1).strip(), "rate": int(ma.group(2)), "channels": ma.group(3)}
    return s


def rms_db(FF, video, t0, dur):
    """取某时间窗的 RMS（dB）。返回 None 表示该窗全静音（-inf）"""
    r = run([FF, "-hide_banner", "-ss", "%.3f" % t0, "-t", "%.3f" % max(dur, 0.05),
             "-i", video, "-map", "0:a:0", "-af", "astats", "-f", "null", "-"])
    m = re.findall(r"RMS level dB:\s*(-?[\d.]+|-inf)", r.stderr)
    if not m:
        return None
    v = m[-1]
    return None if v == "-inf" else float(v)


def ai_mark(FF, video, stderr_hdr):
    """★ 两层取证：① 头信息 ② 原始字节。只查一层不算过。"""
    hdr = [k for k in AI_KEYS if k.lower() in (stderr_hdr or "").lower()]
    raw_hits = []
    try:
        with open(video, "rb") as f:
            blob = f.read()
        for k in AI_KEYS:
            if k.encode("utf-8", "ignore") in blob:
                raw_hits.append(k)
    except Exception as e:
        raw_hits = ["<读文件失败: %s>" % e]
    return {
        "in_header": hdr,
        "in_bytes": raw_hits,
        "pass": bool(hdr) and bool(raw_hits),
        "rule": "两层都要有：头信息能回读、原始字节能搜到。只看 rc 或只看播放器属性都不算取证。",
    }


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: video_selfcheck.py <video> [--frames N] [--duration S] "
                                   "[--probe K] [--blind N --seed S] [--expect-ai-mark] "
                                   "[--script plan.json] [--ratio-max 0.45]"},
                         ensure_ascii=False))
        return 2
    video = sys.argv[1]
    exp_frames = exp_duration = None
    probe_k = 8
    blind_n = 0
    blind_seed = None
    expect_mark = False
    script_path = None
    ratio_max = 0.45
    i = 2
    while i < len(sys.argv):
        a = sys.argv[i]
        if a == "--frames":
            exp_frames = int(sys.argv[i + 1]); i += 2
        elif a == "--duration":
            exp_duration = float(sys.argv[i + 1]); i += 2
        elif a == "--probe":
            probe_k = int(sys.argv[i + 1]); i += 2
        elif a == "--blind":
            blind_n = int(sys.argv[i + 1]); i += 2
        elif a == "--seed":
            blind_seed = sys.argv[i + 1]; i += 2
        elif a == "--expect-ai-mark":
            expect_mark = True; i += 1
        elif a == "--script":
            script_path = sys.argv[i + 1]; i += 2
        elif a == "--ratio-max":
            ratio_max = float(sys.argv[i + 1]); i += 2
        else:
            i += 1

    if not os.path.isfile(video):
        print(json.dumps({"error": "file not found", "file": video}, ensure_ascii=False))
        return 2

    FF = ffmpeg_exe()
    out = {"file": video, "bytes": os.path.getsize(video),
           "checked_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
           "ffmpeg": os.path.basename(FF),
           "scope": {
               "covers": ["规格", "帧数", "时长", "响度", "抽帧是否存在",
                          "AI 标识双取证", "帧数对账", "旁白占比", "逐窗 RMS"],
               "does_NOT_cover": ["画面内容正确性（图里线画错/标签压轴/元素消失）",
                                  "字幕文案正确性", "人脸合规", "色彩/版式美观",
                                  "字幕时间轴与旁白是否真的对得上（只能证明「该有声时有声」）"],
               "rule": "本脚本只证明“结构对”，不证明“内容对”。内容必须靠随机盲抽 + 人眼。",
           }}

    # ① 规格
    r = run([FF, "-hide_banner", "-i", video])
    spec = parse_spec(r.stderr)
    out["spec"] = spec

    # ② 帧数 + 响度：一次全解码
    args = [FF, "-hide_banner", "-i", video, "-map", "0:v:0"]
    if spec["has_audio"]:
        args += ["-map", "0:a:0", "-af", "ebur128"]
    args += ["-f", "null", "-"]
    r2 = run(args)
    err2 = r2.stderr
    frames = None
    mf = re.findall(r"frame=\s*(\d+)", err2)
    if mf:
        frames = int(mf[-1])
    loud = {}
    tail = err2.split("Summary:")[-1] if "Summary:" in err2 else err2
    mi = re.search(r"I:\s*(-?[\d.]+)\s*LUFS", tail)
    mp = re.search(r"Peak:\s*(-?[\d.]+)\s*dBFS", tail)
    if mi:
        loud["integrated_lufs"] = float(mi.group(1))
    if mp:
        loud["peak_dbfs"] = float(mp.group(1))
    if loud:
        loud["clipped"] = bool(loud.get("peak_dbfs", -99) >= -0.1)
        loud["source"] = "ebur128 Summary"
    out["loudness"] = loud or {"note": "no audio stream"}

    dur = (frames / spec["fps"]) if (frames and spec["fps"]) else spec["duration_hdr"]
    out["frames"] = {"actual": frames, "expected": exp_frames,
                     "pass": (frames == exp_frames) if exp_frames else None}
    out["duration"] = {"actual_s": round(dur, 3) if dur else None,
                       "expected_s": exp_duration,
                       "delta_ms": round(abs(dur - exp_duration) * 1000, 1) if (dur and exp_duration) else None,
                       "pass": (abs(dur - exp_duration) <= 0.05) if (dur and exp_duration) else None}

    # ③ 抽帧
    probes = []
    tmp = os.path.join(os.path.dirname(video) or ".", "_sc_probe")
    os.makedirs(tmp, exist_ok=True)
    if frames and probe_k > 0:
        dur_s = frames / spec["fps"]
        for k in range(probe_k):
            t = round(k * dur_s / probe_k, 3)
            p = os.path.join(tmp, "p%02d.png" % k)
            run([FF, "-hide_banner", "-ss", str(t), "-i", video, "-frames:v", "1", "-y", p])
            probes.append({"t": t, "png": p if os.path.isfile(p) else None,
                           "ok": os.path.isfile(p)})
    out["probes"] = {"count": len(probes), "items": probes}

    # ③b 随机盲抽（时刻由 seed 定，产出方无法预知）
    if blind_n > 0 and frames:
        import random as _rnd
        seed = blind_seed or datetime.date.today().strftime("%Y%m%d")
        rng = _rnd.Random(seed)
        dur_s_all = frames / spec["fps"]
        btmp = os.path.join(os.path.dirname(video) or ".", "_sc_blind")
        os.makedirs(btmp, exist_ok=True)
        bl = []
        for k in range(blind_n):
            t = round(rng.uniform(0.2, max(0.3, dur_s_all - 0.2)), 3)
            p = os.path.join(btmp, "b%02d_%.2fs.png" % (k, t))
            run([FF, "-hide_banner", "-ss", str(t), "-i", video, "-frames:v", "1", "-y", p])
            bl.append({"t": t, "png": p if os.path.isfile(p) else None})
        out["blind_probes"] = {
            "seed": seed, "count": len(bl), "items": bl,
            "rule": "时刻由 seed 随机决定 ⇒ 产出方无法预知；**必须逐帧人眼看，脚本不判内容**",
        }
    else:
        out["blind_probes"] = {"count": 0, "rule": "未启用（建议 --blind 6 --seed <当天日期>）"}

    # ④ AI 标识双取证
    mark = ai_mark(FF, video, r.stderr)
    mark["expected"] = expect_mark
    out["ai_mark"] = mark

    # ⑤ --script：帧数对账 / 旁白占比 / 逐窗 RMS
    plan = None
    if script_path:
        try:
            plan = json.load(io.open(script_path, encoding="utf-8"))
        except Exception as e:
            out["script"] = {"error": "读不了 %s: %s" % (script_path, e)}
            plan = None
    if plan is not None:
        blk = {"path": script_path}

        segs = plan.get("segments")
        if segs:
            ssum = sum(int(s["frames"]) for s in segs)
            tgt = plan.get("film_frames") or frames
            blk["segments"] = {"count": len(segs), "sum_frames": ssum,
                               "film_frames": tgt, "pass": (ssum == tgt)}
        else:
            blk["segments"] = {"note": "未给 segments，跳过帧数对账"}

        ntot = plan.get("narration_total_s")
        if ntot and dur:
            ratio = float(ntot) / dur
            blk["narration"] = {"total_s": float(ntot), "film_s": round(dur, 3),
                                "ratio": round(ratio, 4),
                                "ratio_max": ratio_max,
                                "pass": ratio <= ratio_max}
        else:
            blk["narration"] = {"note": "未给 narration_total_s，跳过占比"}

        wins = plan.get("windows") or []
        if wins:
            rows, bad = [], 0
            for w in wins:
                t0 = float(w["t0"]); t1 = float(w["t1"])
                exp = w.get("expect", "sound")
                v = rms_db(FF, video, t0, t1 - t0)
                if exp == "sound":
                    ok = (v is not None) and (v > SOUND_DB)
                else:
                    ok = (v is None) or (v < SILENCE_DB)
                if not ok:
                    bad += 1
                rows.append({"label": w.get("label", ""), "t0": t0, "t1": t1,
                             "expect": exp, "rms_db": v, "pass": ok})
            blk["windows"] = {"count": len(rows), "failed": bad, "items": rows,
                              "rule": "该有声须 > %.0f dB；该静音须 -inf 或 < %.0f dB"
                                      % (SOUND_DB, SILENCE_DB)}
        else:
            blk["windows"] = {"note": "未给 windows，跳过逐窗 RMS"}
        out["script"] = blk

    # ⑥ 汇总
    failed = []
    if exp_frames and frames != exp_frames:
        failed.append("frames: %s != %s" % (frames, exp_frames))
    if exp_duration and dur and abs(dur - exp_duration) > 0.05:
        failed.append("duration: %.3f != %.3f" % (dur, exp_duration))
    if loud.get("clipped"):
        failed.append("audio clipped (peak %.2f dBFS)" % loud.get("peak_dbfs", 0))
    if spec["w"] and spec["h"] and spec["sar"] and spec["sar"] != "1:1":
        failed.append("SAR not 1:1 (%s) → 会变形" % spec["sar"])
    if probe_k > 0 and len([p for p in probes if p["ok"]]) != probe_k:
        failed.append("probe frames missing")
    if expect_mark and not mark["pass"]:
        failed.append("ai_mark 缺失（头=%s 字节=%s）" % (mark["in_header"], mark["in_bytes"]))
    if plan is not None:
        b = out.get("script", {})
        if isinstance(b.get("segments"), dict) and b["segments"].get("pass") is False:
            failed.append("segments: Σ帧 %s != 总帧 %s"
                          % (b["segments"]["sum_frames"], b["segments"]["film_frames"]))
        if isinstance(b.get("narration"), dict) and b["narration"].get("pass") is False:
            failed.append("narration ratio %.1f%% > %.0f%%"
                          % (b["narration"]["ratio"] * 100, ratio_max * 100))
        if isinstance(b.get("windows"), dict) and b["windows"].get("failed"):
            failed.append("rms windows failed: %d" % b["windows"]["failed"])
    out["failed"] = failed
    out["verdict"] = "PASS" if not failed else "FAIL"

    s = json.dumps(out, ensure_ascii=False, indent=1)
    print(s)
    try:
        open(video + ".selfcheck.json", "w", encoding="utf-8").write(s)
    except Exception:
        pass
    return 0 if not failed else 1


if __name__ == "__main__":
    # --- 统一 --help：打印本文件用法说明后退出（陌生环境下第一条命令往往就是它）---
    import sys as _helpsys
    if any(_a in ("-h", "--help", "help") for _a in _helpsys.argv[1:]):
        print((__doc__ or "").strip() or "（本工具无文档字符串）")
        raise SystemExit(0)

    sys.exit(main())
