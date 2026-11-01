# -*- coding: utf-8 -*-
"""banword_scan_local.py —— 本地广告法词典精确扫描（v1.6.0）

**先本地精确扫描，再让 AI 做语义补充。** 不靠 AI 幻觉判断。

用法:
    python banword_scan_local.py <文本文件或目录> [--project 某短剧项目C] [--json]

判定：
  hard   → 命中即须改（无"保留"选项）
  review → 命中后须人工判断（语境可能合法）
  guarded→ 带排除规则（最/第一/100%），仅文案路径启用 100%
"""

# --- 控制台兼容：中文 Windows 默认 GBK，打印 ✓/✗/⇒/⚠ 会抛 UnicodeEncodeError ---
try:
    import sys as _sys
    _sys.stdout.reconfigure(errors="replace")
    _sys.stderr.reconfigure(errors="replace")
except Exception:
    pass
import io, os, sys, re, json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
DICT = os.path.join(HERE, "..", "_assets", "ad_law_banwords.json")


def load_dict():
    with open(DICT, encoding="utf-8") as f:
        return json.load(f)


def build_patterns(d):
    """把词典编译成 (word, regex, severity, category) 列表"""
    items = []

    def add(words, sev, cat):
        for w in words:
            items.append((w, re.compile(re.escape(w)), sev, cat))

    for cat, spec in d.get("hard", {}).items():
        add(spec.get("words", []), "hard", cat)
    for cat, spec in d.get("review", {}).items():
        add(spec.get("words", []), "review", cat)
    for w, spec in d.get("guarded", {}).items():
        items.append((w, re.compile(spec["pattern"]), "hard", "guarded/极限词"))
    return items


def read_texts(path):
    """返回 [(文件路径, 文本)]；目录则递归 .md/.txt/.json"""
    out = []
    if os.path.isfile(path):
        try:
            out.append((path, open(path, encoding="utf-8", errors="replace").read()))
        except Exception:
            pass
        return out
    for dp, dn, fn in os.walk(path):
        dn[:] = [x for x in dn if x not in {"__pycache__", "node_modules", ".git"}]
        for f in fn:
            if not f.endswith((".md", ".txt", ".json", ".csv")):
                continue
            p = os.path.join(dp, f)
            try:
                out.append((p, open(p, encoding="utf-8", errors="replace").read()))
            except Exception:
                pass
    return out


def scan(text, items, proj_extra_words):
    hits = []
    lines = text.splitlines()
    for ln, line in enumerate(lines, 1):
        if not line.strip():
            continue
        for word, rx, sev, cat in items:
            if word == "100%":
                continue  # 100% 交给 guarded 的 pattern（已含技术语境排除）
            for m in rx.finditer(line):
                hits.append({"word": word, "severity": sev, "category": cat,
                             "line": ln, "col": m.start() + 1,
                             "context": line[max(0, m.start() - 20): m.end() + 20].strip()})
        for w in proj_extra_words:
            if w in line:
                i = line.find(w)
                hits.append({"word": w, "severity": "hard", "category": "project_extra",
                             "line": ln, "col": i + 1,
                             "context": line[max(0, i - 20): i + len(w) + 20].strip()})
    return hits


def main():
    if len(sys.argv) < 2:
        print("usage: banword_scan_local.py <file_or_dir> [--project NAME] [--json]")
        return 2
    target = sys.argv[1]
    project = None
    as_json = "--json" in sys.argv
    if "--project" in sys.argv:
        project = sys.argv[sys.argv.index("--project") + 1]

    d = load_dict()
    items = build_patterns(d)
    proj_words = []
    if project:
        pe = d.get("project_extra", {}).get(project, {})
        proj_words = pe.get("words", [])

    texts = read_texts(target)
    all_hits, files_with = [], []
    for p, t in texts:
        h = scan(t, items, proj_words)
        if h:
            files_with.append((p, len(h)))
            for x in h:
                x["file"] = os.path.basename(p)
                all_hits.append(x)

    hard = [h for h in all_hits if h["severity"] == "hard"]
    review = [h for h in all_hits if h["severity"] == "review"]

    if as_json:
        print(json.dumps({"target": target, "project": project,
                          "files_scanned": len(texts),
                          "hard": hard, "review": review,
                          "dict_version": d["_meta"]["version"]}, ensure_ascii=False, indent=1))
    else:
        print("词典 v%s ｜ 扫描 %d 个文件 ｜ 硬违规 %d 处 ｜ 待复核 %d 处"
              % (d["_meta"]["version"], len(texts), len(hard), len(review)))
        print()
        if hard:
            print("【硬违规（须改，无保留选项）】")
            for h in hard[:40]:
                print("  %-10s L%-4d %-6s %s" % (h["file"][:10], h["line"], h["word"], h["context"][:44]))
            if len(hard) > 40:
                print("  … 共 %d 处" % len(hard))
        else:
            print("【硬违规】0 处 ✅")
        print()
        if review:
            print("【待复核（语境相关，须人工判断）】")
            for h in review[:20]:
                print("  %-10s L%-4d %-6s %s" % (h["file"][:10], h["line"], h["word"], h["context"][:44]))
            if len(review) > 20:
                print("  … 共 %d 处" % len(review))
        else:
            print("【待复核】0 处")
        print()
        print("★ 纪律：本地词典先判，AI 只做语义补充 —— 不许用 AI 幻觉替代本表。")

    return 1 if hard else 0


if __name__ == "__main__":
    # --- 统一 --help：打印本文件用法说明后退出（陌生环境下第一条命令往往就是它）---
    import sys as _helpsys
    if any(_a in ("-h", "--help", "help") for _a in _helpsys.argv[1:]):
        print((__doc__ or "").strip() or "（本工具无文档字符串）")
        raise SystemExit(0)

    sys.exit(main())
