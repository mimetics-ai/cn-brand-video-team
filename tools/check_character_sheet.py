# -*- coding: utf-8 -*-
"""check_character_sheet.py —— 角色卡完整性检查（v1.6.0 工程二配套）

多集/多角色任务开工前跑一次：卡不完整 ⇒ 不许开工。

用法:
    python check_character_sheet.py <角色卡.md> [--strict]

判据设计（**宽容，避免误报**）：
  - 字段名出现在任意位置即可（允许「性别/年龄」合并写、允许标题形式）
  - 冒号后必须**有实际值**（非空、非模板占位）
  - 授权状态只认三值；模板里的说明文字（含"禁用"括注）不算值
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

# (字段名, 归属组, 是否必填)
FIELDS = [
    ("性别", "长相", True), ("年龄", "长相", True), ("脸型", "长相", True),
    ("发型", "长相", True), ("肤色", "长相", True), ("眉眼", "长相", True),
    ("上衣", "服装", True), ("下装", "服装", True), ("鞋", "服装", True),
    ("语速", "说话", True), ("口音", "说话", True), ("语气", "说话", True),
    ("固定 Prompt 前缀", "前缀", True),
    ("定妆图", "首帧", True), ("授权状态", "首帧", True),
]
AUTH_OK = ("自有", "客户提供", "来源不明")


def line_value(t, field):
    """返回该字段所在行冒号后的值（取第一个非空匹配）"""
    for line in t.splitlines():
        if field in line:
            m = re.search(r"[:：]\s*(.+)$", line)
            if m:
                v = m.group(1).strip().strip("　 。，,、-`")
                if v:
                    return v
            # 无冒号（如标题）⇒ 视为无值，靠前缀块单独判
    return ""


def main():
    if len(sys.argv) < 2:
        print("usage: check_character_sheet.py <sheet.md> [--strict]")
        return 2
    p = sys.argv[1]
    if not os.path.isfile(p):
        print("找不到文件：%s" % p); return 2
    t = open(p, encoding="utf-8").read()
    strict = "--strict" in sys.argv
    friendly = "--friendly" in sys.argv

    print("角色卡检查：%s" % os.path.basename(p))
    print()
    missing, empty = [], []

    for field, group, req in FIELDS:
        if field not in t:
            if req:
                missing.append("%s / %s（缺字段）" % (group, field))
            continue
        if field in ("固定 Prompt 前缀", "授权状态"):
            continue  # 单独判
        v = line_value(t, field)
        if not v:
            empty.append("%s / %s（空值）" % (group, field))

    # 固定前缀：找 ``` 块且内容 ≥30 字
    pref_m = re.search(r"固定 Prompt 前缀[\s\S]{0,120}?```([\s\S]*?)```", t)
    pref_txt = pref_m.group(1).strip() if pref_m else ""
    pref_ok = len(pref_txt) >= 30

    # 授权状态：只取"授权状态"行的值；排除含"禁用"的说明行
    auth_val = ""
    for line in t.splitlines():
        if "授权状态" in line and not line.strip().startswith(">") and "禁用" not in line:
            m = re.search(r"[:：]\s*(.+)$", line)
            if m:
                auth_val = m.group(1).strip().strip("　 。，,")
                break
    auth_ok = any(a == auth_val or auth_val.startswith(a) for a in AUTH_OK)
    banned = auth_val.startswith("来源不明")

    print("  ── 字段 ──")
    if missing:
        for x in missing: print("    ❌ " + x)
    if empty:
        for x in empty: print("    ⚠ " + x)
    if not missing and not empty:
        print("    ✅ 全部填了就位")

    print()
    print("  ── 关键 ──")
    print("    %s 固定前缀 %d 字（需 ≥30）" % ("✅" if pref_ok else "❌", len(pref_txt)))
    mark = "❌" if banned else ("✅" if auth_ok else "❌")
    print("    %s 授权状态 = %s" % (mark, auth_val or "(未填)"))
    if banned:
        print("       ↑ **来源不明 ⇒ 禁用（肖像权风险），本条即视为不合格**")

    ok = (not missing) and (not empty) and pref_ok and auth_ok and not banned
    print()
    if ok:
        print("  ⇒ 判定：**PASS** —— 可以开工")
        print("     （记得每次生成把固定前缀**原样贴在最前面**，人物在外、动作在后）")
        return 0
    if friendly:
        # ★ 温柔拦截：给客户看的是「下一步做什么」，不是技术错误
        lacks = []
        for x in (missing + empty):
            lacks.append(x.split("（")[0].split(" / ")[-1])
        if not pref_ok:
            lacks.append("固定 Prompt 前缀（一段 ≥30 字的人物描述）")
        if not auth_ok or banned:
            lacks.append("首帧授权状态（自有／客户提供／来源不明）")
        print()
        print("━" * 52)
        print("【需要你先做一件事，不是报错】")
        print()
        print("由于本次任务涉及人物生成，为了确保**跨镜头长相一致**，")
        print("请先填写标准角色卡模板（我已为您生成）：")
        print()
        print("    %s" % os.path.abspath(p))
        print()
        if lacks:
            print("**需要补 %d 项**：%s" % (len(lacks), "、".join(lacks[:6])))
            print()
        print("填好后回我一句「**卡填好了**」，我立刻开工。")
        print()
        print("（为什么需要：AI 每次生成都会「忘记」这个人长什么样。")
        print("  我们把长相写死，每次生成前念一遍 —— 这样脸才不飘。）")
        print()
        print("**不想填也可以**：如果这条片子**只出一个镜头/一个人**，")
        print("回我「单人单镜，跳过卡」，我就直接开工（风险：后续加镜可能对不上）。")
        print("━" * 52)
        return 1 if strict else 0

    print("  ⇒ 判定：**不可开工** —— 补全后重跑")
    print("     纪律：多集/多角色任务，卡不完整不许动手（v1.6.0 工程二 铁律 1）")
    return 1 if strict else 0


if __name__ == "__main__":
    # --- 统一 --help：打印本文件用法说明后退出（陌生环境下第一条命令往往就是它）---
    import sys as _helpsys
    if any(_a in ("-h", "--help", "help") for _a in _helpsys.argv[1:]):
        print((__doc__ or "").strip() or "（本工具无文档字符串）")
        raise SystemExit(0)

    sys.exit(main())
