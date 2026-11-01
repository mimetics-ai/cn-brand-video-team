# -*- coding: utf-8 -*-
"""batch_replicate.py —— 批量拆解参考片（W7 扩展 · v1.5.7）

客户一次给 3~5 条参考片 ⇒ 一次拆完 ⇒ 出**对比表**（哪个结构适合他）。

用法:
    python batch_replicate.py <视频1> <视频2> ... [--scene 0.3] [--out 对比表.md]

说明: 逐条调用同目录的 replicate.py，汇总镜头数/平均镜长/时长，输出对比表。
      **不做爬虫**（平台反爬 + 数据合规风险）—— 参考片由客户提供。
"""

# --- 控制台兼容：中文 Windows 默认 GBK，打印 ✓/✗/⇒/⚠ 会抛 UnicodeEncodeError ---
try:
    import sys as _sys
    _sys.stdout.reconfigure(errors="replace")
    _sys.stderr.reconfigure(errors="replace")
except Exception:
    pass
import io, os, sys, json, subprocess

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    vids, thr, out = [], "0.3", None
    i = 1
    while i < len(sys.argv):
        a = sys.argv[i]
        if a == "--scene":
            thr = sys.argv[i + 1]; i += 2
        elif a == "--out":
            out = sys.argv[i + 1]; i += 2
        else:
            vids.append(a); i += 1
    if not vids:
        print("usage: batch_replicate.py <v1> <v2> ... [--scene 0.3] [--out x.md]")
        return 2

    rows = []
    for v in vids:
        if not os.path.isfile(v):
            rows.append({"file": os.path.basename(v), "error": "not found"}); continue
        r = subprocess.run([sys.executable, os.path.join(HERE, "replicate.py"), v, "--scene", thr],
                           capture_output=True, text=True, errors="replace")
        try:
            d = json.loads(r.stdout)
            rows.append({"file": os.path.basename(v), "spec": d["spec"],
                         "shots": d["shot_count"], "avg": d["avg_shot_len_s"],
                         "dur": d["spec"]["duration_s"]})
        except Exception:
            rows.append({"file": os.path.basename(v), "error": "parse failed"})

    print(json.dumps(rows, ensure_ascii=False, indent=1))

    if out:
        md = ["# 批量拆解 · 结构对比（W7 扩展）", "",
              "> 阈值 --scene %s ｜ 参考片由客户提供（**不做爬虫**）" % thr, "",
              "| # | 参考片 | 时长(s) | **镜头数** | **平均镜长(s)** | 分辨率 |",
              "|---|---|---|---|---|---|"]
        ok = [r for r in rows if "error" not in r]
        for k, r in enumerate(ok, 1):
            md.append("| %d | `%s` | %.2f | **%d** | **%s** | %sx%s |"
                      % (k, r["file"], r["dur"], r["shots"], r["avg"],
                         r["spec"]["w"], r["spec"]["h"]))
        md += ["", "## 怎么用这张表", "",
               "1. **平均镜长最短的那条 = 节奏最快** ⇒ 适合钩子强的产品（快消/美妆）",
               "2. **镜头数少 = 单镜信息量大** ⇒ 适合讲原理/参数（工业/技术）",
               "3. **选 1 条做骨架**（不建议揉 3 条，会结构混乱）",
               "", "## ★ 仍需人补", "",
               "- 钩子逐字 ｜ 段落语义 ｜ 字幕密度 ｜ BGM 情绪（脚本不判内容）", ""]
        open(out, "w", encoding="utf-8").write("\n".join(md))
        print("\n  对比表已写：%s" % out, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
