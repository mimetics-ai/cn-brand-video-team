# -*- coding: utf-8 -*-
"""check_consistency.py —— 四维一致性检查（v1.6.0 补）

配合 `character_sheet_template.md` 的第七节。
**只查"有没有真填"，不查"填得对不对"**（对错要人看）。

用法:
    python check_consistency.py <角色卡.md> [--friendly] [--require-props] [--require-set]

维度：
  ① 人物（由 check_character_sheet.py 负责）
  ② 道具：道具卡存在 + 有参考图
  ③ 场景：场景卡存在 + 有光源方向 + 时间设定
  ④ 色调：全局色调存在 + 有倾向 + 有色温/对比/饱和中至少两项
"""

# --- 控制台兼容：中文 Windows 默认 GBK，打印 ✓/✗/⇒/⚠ 会抛 UnicodeEncodeError ---
try:
    import sys as _sys
    _sys.stdout.reconfigure(errors="replace")
    _sys.stderr.reconfigure(errors="replace")
except Exception:
    pass
import io, os, sys, re

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def has_section(t, *keys):
    return all(k in t for k in keys)


def val_after(t, field):
    for line in t.splitlines():
        if field in line and not line.strip().startswith(("#", ">", "|")):
            m = re.search(r"[:：]\s*(.+)$", line)
            if m:
                v = m.group(1).strip().strip("　 。，,、-`")
                if v and not v.startswith("__") and not v.startswith("<"):
                    return v
    return ""


def main():
    if len(sys.argv) < 2:
        print("usage: check_consistency.py <sheet.md> [--friendly] [--require-props] [--require-set]")
        return 2
    p = sys.argv[1]
    if not os.path.isfile(p):
        print("找不到文件：%s" % p); return 2
    t = open(p, encoding="utf-8").read()
    friendly = "--friendly" in sys.argv
    req_props = "--require-props" in sys.argv
    req_set = "--require-set" in sys.argv

    print("四维一致性检查：%s" % os.path.basename(p))
    print()

    fails, warns = [], []

    # ② 道具
    if req_props or "道具卡" in t:
        if not has_section(t, "道具卡"):
            fails.append("道具 / 缺【道具卡】小节")
        else:
            ref = val_after(t, "参考图")
            if not ref:
                fails.append("道具 / 参考图未填（**文字锁不住材质，必须配图**）")
            if not val_after(t, "材质"):
                warns.append("道具 / 材质未填")

    # ③ 场景
    if req_set or "场景卡" in t:
        if not has_section(t, "场景卡"):
            fails.append("场景 / 缺【场景卡】小节")
        else:
            if not val_after(t, "光源方向"):
                fails.append("场景 / 光源方向未填（**同一空间换机位会露出光向矛盾**）")
            if not val_after(t, "时间设定"):
                fails.append("场景 / 时间设定未填（防窗外白天变黑夜）")
            if not val_after(t, "参考图"):
                warns.append("场景 / 参考图未填（建议补，多机位更稳）")

    # ④ 色调（**全片唯一决定，必填**）
    if not has_section(t, "全局色调"):
        fails.append("色调 / 缺【全局色调】小节（**全片只有一次决定权**）")
    else:
        tone = val_after(t, "倾向")
        if not tone:
            fails.append("色调 / 倾向未填（暖调 / 冷调 / 中性，三选一）")
        else:
            got = sum(1 for k in ("色温", "对比", "饱和度") if val_after(t, k))
            if got < 2:
                fails.append("色调 / 色温·对比·饱和度 至少填 2 项（现 %d 项）" % got)

    # 输出
    if fails:
        print("  ── 不通过 ──")
        for x in fails: print("    ❌ " + x)
    if warns:
        print("  ── 建议补 ──")
        for x in warns: print("    ⚠ " + x)
    if not fails and not warns:
        print("    ✅ 四维三项（道具/场景/色调）均已填写")
    elif not fails:
        print("    四维必填项已过（有 %d 条建议）" % len(warns))

    ok = not fails
    print()
    if ok:
        print("  ⇒ 判定：**PASS**")
        print("     开工前记得：人物→道具→场景→色调→动作，**四层前缀顺序不能倒**")
        return 0
    if friendly:
        print("━" * 52)
        print("【还差一点就能开工】")
        print()
        print("为了不出现「瓶子一会儿大一会儿小」「窗外一会儿白天一会儿黑夜」")
        print("「这一镜暖下一镜冷」，请把这份卡里这几项补上：")
        print()
        for i, x in enumerate(fails, 1):
            print("  %d. %s" % (i, x.split(" / ")[-1]))
        print()
        print("填好后回我一句「**卡补好了**」，我立刻开工。")
        print("（这几项填一次，整片都受益 —— 比返工便宜。）")
        print("━" * 52)
    else:
        print("  ⇒ 判定：**不通过** —— 补全后重跑")
    return 1


if __name__ == "__main__":
    # --- 统一 --help：打印本文件用法说明后退出（陌生环境下第一条命令往往就是它）---
    import sys as _helpsys
    if any(_a in ("-h", "--help", "help") for _a in _helpsys.argv[1:]):
        print((__doc__ or "").strip() or "（本工具无文档字符串）")
        raise SystemExit(0)

    sys.exit(main())
