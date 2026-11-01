# -*- coding: utf-8 -*-
"""
ledger.py —— 制片账本 v1.7-c（每单一账 · 四账闭环 · 防篡改）

四账（v1.7-c 范围，用户拍板）：
  cost    成本：即梦/大模型/API/TTS/本地合成的消耗（估算区间 + billed 待账单回填）
  license 许可：素材来源（客户/AI生成/库存/字体）、许可文本、作者
  claims  宣称：成片中出现的功效/数值/绝对化宣称及其处置（refused/pending_client/approved…）
  assets  资产：全部产出物 md5 索引（deliverable / intermediate / reference）

红线（写死）：
  1. 账本 append-only：条目只增不改不删，防篡改靠哈希链（每条 chain=sha256(上条chain+本条规范JSON)）。
  2. close 后账本封口：任何写操作拒绝；重开=新建修订账本，不改旧账。
  3. role=deliverable 的资产必须有对应 license 条目，否则 check 不过、close 拒绝。
  4. claims 有 pending_client 时拒绝 close（客户未拍板不许结账）。
  5. cost 条目必须带 evidence（事件 id / 派发单号 / 台账行号），无证据不计账。

自动生成：
  task_queue run/queue --ledger <dir> 收工即同步（幂等，键 tq:<task>:<node>）：
  从 state+events 自动产出 cost（按 provider 规则估算）与 assets（node_done 的 md5 表）。
  同步失败只警告不阻断队列——events.jsonl 是证据源，可随时重放补记（cost-sync 幂等）。

用法：
  python ledger.py init --project <dir> --name "某防水品牌A30s"
  python ledger.py cost-sync --project <dir> --task-dir <workdir>      # 从队列自动对账
  python ledger.py cost-add / license-add / claim-add / asset-register ...
  python ledger.py check --project        # 完整性校验（rc!=0 列缺陷）
  python ledger.py close --project        # 封账
  python ledger.py verify --project       # 重算哈希链 + 重哈希资产
  python ledger.py md --project [--out LEDGER.md]
"""
import argparse
import hashlib
import json
import os
import sys
import time

# 注意：本模块会被 task_queue 导入——禁止重包 sys.stdout（会把队列已包装的流关闭，
# 触发 ValueError: I/O operation on closed file）；只 reconfigure 编码。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SCHEMA = "zhiben-ledger/1.0"
CLOSED_MSG = "账本已封账（close），拒绝写入；如需修订请新建修订账本"

# 成本估算规则（口径与打包器/台账同源；billed 一律待平台账单回填）
COST_RULES = {
    ("jimeng", "image"): {"unit": "credit", "est": (5, 10), "note": "图像 5–10 积分/张（平台区间）"},
    ("jimeng", "video_happyhorse"): {"unit": "credit", "est": (14, 14), "per_s": True, "note": "happyhorse 720P 14 积分/秒"},
    ("jimeng", "video_seedance"): {"unit": "credit", "est": (18, 18), "per_s": True, "note": "seedance 2.5 18 积分/秒"},
    ("edge-tts", "tts"): {"unit": "credit", "est": (0, 0), "note": "edge-tts 本地 0 积分"},
    ("local", "ffmpeg"): {"unit": "credit", "est": (0, 0), "note": "本地 ffmpeg 0 积分"},
    ("llm", "call"): {"unit": "call", "est": None, "note": "LLM 调用，费用待平台账单回填"},
}


def _pdir(args):
    return os.path.join(args.project, "_ledger")


def lp(args):
    return os.path.join(_pdir(args), "ledger.json")


def load(args):
    with open(lp(args), encoding="utf-8") as f:
        return json.load(f)


def save(args, m):
    os.makedirs(_pdir(args), exist_ok=True)
    with open(lp(args), "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def append(m, section, entry):
    """append-only + 哈希链。closed 后抛错。"""
    if m.get("integrity", {}).get("closed"):
        raise SystemExit(CLOSED_MSG)
    prev = m["entries"][-1]["chain"] if m["entries"] else "GENESIS"
    entry = dict(entry)
    entry["section"] = section
    entry["seq"] = len(m["entries"]) + 1
    entry["chain"] = hashlib.sha256((prev + canon(entry)).encode("utf-8")).hexdigest()
    m["entries"].append(entry)
    m["updated_at"] = now()
    return entry


_SECTION_OF = {"C": "cost", "L": "license", "Q": "claim", "A": "asset"}


def _next_id(m, prefix):
    sec = _SECTION_OF[prefix]                      # 按节名精确计数（前缀字母≠节名，不能 startswith）
    n = sum(1 for e in m["entries"] if e["section"] == sec) + 1
    return "%s%03d" % (prefix, n)


# ---------- 子命令 ----------

def cmd_init(args):
    path = lp(args)
    if os.path.exists(path) and not args.force:
        raise SystemExit("账本已存在：%s（--force 重置会毁账，禁止；如需重开请换目录）" % path)
    os.makedirs(_pdir(args), exist_ok=True)
    m = {"schema": SCHEMA, "name": args.name, "project": os.path.abspath(args.project),
         "opened_at": now(), "updated_at": now(),
         "entries": [], "integrity": {"closed": False, "closed_at": None, "final_hash": None}}
    save(args, m)
    print("账本已建立：%s（%s）" % (path, args.name))
    return 0


def _est_for(provider, kind, seconds=None):
    rule = COST_RULES.get((provider, kind))
    if not rule:
        return None, None, None, "无计费规则，待人工登记"
    lo, hi = rule["est"]
    if rule.get("per_s") and seconds:
        lo, hi = lo * seconds, hi * seconds
    return (None if lo is None else round(lo, 1)), (None if hi is None else round(hi, 1)), rule["unit"], rule["note"]


def cmd_cost_add(args):
    m = load(args)
    e = append(m, "cost", {
        "id": _next_id(m, "C"), "ts": now(), "kind": args.kind, "provider": args.provider,
        "item": args.item, "qty": args.qty, "unit": args.unit,
        "est": [args.est_lo, args.est_hi], "billed": None,
        "evidence": args.evidence, "note": args.note or ""})
    save(args, m)
    print("cost +%s  %s/%s %s est=[%s,%s] %s" % (e["id"], args.provider, args.kind, args.item,
                                                 args.est_lo, args.est_hi, args.evidence))
    return 0


def cmd_license_add(args):
    m = load(args)
    # 路径归一化：asset_ref 若指向真实文件则转绝对路径（与 asset 登记同口径），否则原样保留（可指目录/批量描述）
    ref = args.asset_ref
    if os.path.exists(ref):
        ref = os.path.abspath(ref)
    e = append(m, "license", {
        "id": _next_id(m, "L"), "ts": now(), "asset_ref": ref,
        "origin": args.origin, "provider": args.provider or "", "source_url": args.source_url or "",
        "license": args.license, "author": args.author or "", "verified": bool(args.verified),
        "note": args.note or ""})
    save(args, m)
    print("license +%s  %s origin=%s license=%s" % (e["id"], args.asset_ref, args.origin, args.license[:40]))
    return 0


def cmd_claim_add(args):
    m = load(args)
    e = append(m, "claim", {
        "id": _next_id(m, "Q"), "ts": now(), "claim": args.claim, "status": args.status,
        "ref": args.ref, "film_window": args.window or "", "note": args.note or ""})
    save(args, m)
    print("claim +%s  「%s」 status=%s ref=%s" % (e["id"], args.claim, args.status, args.ref))
    return 0


def cmd_claim_set(args):
    m = load(args)
    hit = [e for e in m["entries"] if e["id"] == args.id and e["section"] == "claim"]
    if not hit:
        raise SystemExit("没有宣称条目 %s" % args.id)
    # append-only：处置变更=追加一条 supersede，不改旧条
    old = hit[0]
    e = append(m, "claim", {
        "id": _next_id(m, "Q"), "ts": now(), "claim": old["claim"], "status": args.status,
        "ref": args.ref or old["ref"], "film_window": old.get("film_window", ""),
        "note": "supersede %s：%s" % (old["id"], args.note or ""), "supersedes": old["id"]})
    save(args, m)
    print("claim +%s  supersede %s → status=%s" % (e["id"], old["id"], args.status))
    return 0


def _md5f(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def cmd_asset_register(args):
    m = load(args)
    p = os.path.abspath(args.path)
    if not os.path.exists(p):
        raise SystemExit("文件不存在：%s" % p)
    dup = [e for e in m["entries"] if e["section"] == "asset" and e["md5"] == _md5f(p)
           and e["path"] == p]
    if dup:
        print("asset 跳过：%s 已登记（%s）" % (os.path.basename(p), dup[0]["id"]))
        return 0
    e = append(m, "asset", {
        "id": _next_id(m, "A"), "ts": now(), "path": p, "md5": _md5f(p),
        "bytes": os.path.getsize(p), "role": args.role,
        "evidence": args.evidence or "asset-register", "note": args.note or ""})
    save(args, m)
    print("asset +%s  %s md5=%s role=%s" % (e["id"], os.path.basename(p), e["md5"][:12], args.role))
    return 0


def cmd_cost_sync(args):
    """从 task_queue workdir 自动对账（幂等）：cost 按 provider 规则、assets 按 node_done md5。"""
    m = load(args)
    workdir = args.task_dir
    with open(os.path.join(workdir, "state.json"), encoding="utf-8") as f:
        st = json.load(f)
    task_id = st.get("task_id") or os.path.basename(workdir)
    spec_nodes = {}
    specp = st.get("spec")                       # 队列不拷贝 spec，state 里存的是原 spec 路径
    if specp and os.path.exists(specp):
        with open(specp, encoding="utf-8") as f:
            spec_nodes = {n["id"]: n for n in json.load(f).get("nodes", [])}
    have = {(e.get("evidence") or "") for e in m["entries"] if e["section"] == "cost"}
    have_a = {(e["md5"], e["path"]) for e in m["entries"] if e["section"] == "asset"}
    n_cost = n_asset = 0
    for nid, rec in (st.get("nodes") or {}).items():
        node = spec_nodes.get(nid, {})
        # provider 三级来源：显式字段 > resource "provider:jimeng"（LEGACY_RESOURCE 遗留映射）> job/local 推断
        res = str(node.get("resource") or "")
        provider = (node.get("provider")
                    or (res.split(":", 1)[1] if res.startswith("provider:") else None)
                    or ("local" if not rec.get("provider_job_id") else "unknown"))
        outputs = rec.get("outputs") or {}
        done = rec.get("status") == "done"
        reused = bool(rec.get("reused"))
        if done and not reused and (rec.get("provider_job_id") or provider == "local"):
            key = "tq:%s:%s:%s" % (task_id, nid, rec.get("attempts", 0))
            if key not in have:
                kind = "ffmpeg" if provider == "local" else "call"
                secs = None
                if provider == "jimeng":
                    kind = "image" if any(k.endswith((".png", ".jpg", ".jpeg")) for k in outputs) else "video_happyhorse"
                    dur = (node.get("params") or {}).get("dur") or (node.get("params") or {}).get("duration")
                    if isinstance(dur, (int, float)):
                        secs = float(dur)
                est_lo, est_hi, unit, note = _est_for(provider, kind, secs)
                e = append(m, "cost", {
                    "id": _next_id(m, "C"), "ts": now(), "kind": kind, "provider": provider,
                    "item": nid, "qty": 1, "unit": unit, "est": [est_lo, est_hi], "billed": None,
                    "evidence": key, "note": note + "（attempts=%s job=%s）"
                            % (rec.get("attempts", 0), rec.get("provider_job_id") or "-")})
                have.add(key)
                n_cost += 1
        if done and reused:
            key = "tq:%s:%s:reuse" % (task_id, nid)
            if key not in have:
                append(m, "cost", {
                    "id": _next_id(m, "C"), "ts": now(), "kind": "reuse", "provider": provider,
                    "item": nid, "qty": 1, "unit": "credit", "est": [0, 0], "billed": 0,
                    "evidence": key, "note": "幂等复用，未重复下单（job=%s）" % rec.get("provider_job_id")})
                have.add(key)
                n_cost += 1
        for rel, dig in outputs.items():
            sig = (dig["md5"], os.path.abspath(os.path.join(workdir, rel)))
            if sig in have_a:
                continue
            p = os.path.abspath(os.path.join(workdir, rel))
            append(m, "asset", {
                "id": _next_id(m, "A"), "ts": now(), "path": p, "md5": dig["md5"],
                "bytes": dig["bytes"], "role": node.get("role") or "intermediate",
                "evidence": "tq:%s:%s:node_done" % (task_id, nid),
                "note": "队列产物自动登记"})
            have_a.add(sig)
            n_asset += 1
    save(args, m)
    print("cost-sync：%s → cost +%d / asset +%d（幂等键 tq:<task>:<node>）" % (task_id, n_cost, n_asset))
    return 0


def cmd_check(args):
    m = load(args)
    problems, warnings = [], []
    entries = m["entries"]
    sec = lambda s: [e for e in entries if e["section"] == s]
    # R1 cost 必须有证据
    for e in sec("cost"):
        if not (e.get("evidence") or "").strip():
            problems.append("R1 cost %s 无 evidence" % e["id"])
    # R2 deliverable 资产必须有 license（asset_ref 兼容相对/绝对写法）
    lic_refs = {(os.path.abspath(e["asset_ref"]) if os.path.exists(e["asset_ref"]) else e["asset_ref"])
                for e in sec("license")}
    for e in sec("asset"):
        if e["role"] == "deliverable" and e["path"] not in lic_refs:
            problems.append("R2 deliverable %s（%s）缺 license 条目" % (e["id"], os.path.basename(e["path"])))
    # R3 stock 素材必须 source_url+license；字体必须 license
    for e in sec("license"):
        if e["origin"] == "stock" and not (e.get("source_url") and e.get("license")):
            problems.append("R3 license %s origin=stock 缺 source_url/license" % e["id"])
        if e["origin"] == "font" and not e.get("license"):
            problems.append("R3 license %s origin=font 缺 license" % e["id"])
    # R4 claims pending_client → 警告（close 时升级为拒绝）
    pend = [e for e in sec("claim") if e["status"] == "pending_client"]
    sup = {e.get("supersedes") for e in sec("claim")}
    active_pend = [e for e in pend if e["id"] not in sup]
    if active_pend:
        warnings.append("R4 %d 条宣称 pending_client：%s" % (len(active_pend), ",".join(e["id"] for e in active_pend)))
    # R5 资产 md5 复核（存在性+哈希）
    for e in sec("asset"):
        if not os.path.exists(e["path"]):
            problems.append("R5 asset %s 文件缺失：%s" % (e["id"], e["path"]))
        elif _md5f(e["path"]) != e["md5"]:
            problems.append("R5 asset %s md5 不符（文件已变）：%s" % (e["id"], os.path.basename(e["path"])))
    # R6 哈希链
    ok, bad_seq = _verify_chain(entries)
    if not ok:
        problems.append("R6 哈希链断裂于 seq=%s（账本被篡改或手改）" % bad_seq)
    for w in warnings:
        print("WARN " + w)
    for p in problems:
        print("FAIL " + p)
    print("check：%d 项缺陷 / %d 项警告 / 条目 %d" % (len(problems), len(warnings), len(entries)))
    return 1 if problems else 0


def _verify_chain(entries):
    prev = "GENESIS"
    for e in entries:
        body = {k: v for k, v in e.items() if k != "chain"}
        want = hashlib.sha256((prev + canon(body)).encode("utf-8")).hexdigest()
        if e.get("chain") != want:
            return False, e.get("seq")
        prev = e["chain"]
    return True, None


def cmd_close(args):
    m = load(args)
    if m["integrity"]["closed"]:
        print("已封账于 %s，忽略重复 close" % m["integrity"]["closed_at"])
        return 0
    rc = cmd_check(args)
    if rc != 0:
        raise SystemExit("close 拒绝：check 有缺陷（先修账再封）")
    pend = [e for e in m["entries"] if e["section"] == "claim" and e["status"] == "pending_client"]
    sup = {e.get("supersedes") for e in m["entries"] if e["section"] == "claim"}
    if [e for e in pend if e["id"] not in sup]:
        raise SystemExit("close 拒绝：宣称账仍有 pending_client（客户未拍板不许结账）")
    m["integrity"] = {"closed": True, "closed_at": now(),
                      "final_hash": m["entries"][-1]["chain"] if m["entries"] else "GENESIS"}
    save(args, m)
    print("账本已封账：final_hash=%s" % m["integrity"]["final_hash"][:16])
    return 0


def cmd_verify(args):
    m = load(args)
    ok, bad = _verify_chain(m["entries"])
    print("哈希链：%s" % ("完整（%d 条）" % len(m["entries"]) if ok else "断裂 @seq=%s" % bad))
    n_ok = n_bad = 0
    for e in m["entries"]:
        if e["section"] != "asset":
            continue
        if not os.path.exists(e["path"]):
            print("  asset %s 缺失：%s" % (e["id"], e["path"]))
            n_bad += 1
        elif _md5f(e["path"]) != e["md5"]:
            print("  asset %s md5 不符：%s" % (e["id"], e["path"]))
            n_bad += 1
        else:
            n_ok += 1
    print("资产复核：%d 一致 / %d 异常" % (n_ok, n_bad))
    if m["integrity"]["closed"]:
        tail_ok = (m["integrity"]["final_hash"] == (m["entries"][-1]["chain"] if m["entries"] else "GENESIS"))
        print("封账 hash：%s" % ("一致" if tail_ok else "不一致（封账后又有写入！）"))
        ok = ok and tail_ok
    return 0 if ok and n_bad == 0 else 1


def cmd_md(args):
    m = load(args)
    sec = lambda s: [e for e in m["entries"] if e["section"] == s]
    lines = ["# 制片账本 · %s" % m["name"], "",
             "- schema：%s ｜ 开账：%s ｜ 更新：%s ｜ 状态：%s" % (
                 m["schema"], m["opened_at"], m["updated_at"],
                 "已封账 " + m["integrity"]["closed_at"] if m["integrity"]["closed"] else "在账（未封）"), ""]
    cost = sec("cost")
    lo = sum(e["est"][0] for e in cost if e["est"] and e["est"][0] is not None)
    hi = sum(e["est"][1] for e in cost if e["est"] and e["est"][1] is not None)
    lines += ["## 成本（%d 条，估算合计 %s–%s %s；billed 待平台账单回填）" % (
        len(cost), lo, hi, cost[0]["unit"] if cost else "credit"), "",
              "| id | provider/kind | item | est | evidence | note |", "|---|---|---|---|---|---|"]
    for e in cost:
        lines.append("| %s | %s/%s | %s | %s | %s | %s |" % (
            e["id"], e["provider"], e["kind"], e["item"], e["est"], e["evidence"], e["note"][:60]))
    lines += ["", "## 许可（%d 条）" % len(sec("license")), "",
              "| id | asset | origin | license | author | verified |", "|---|---|---|---|---|---|"]
    for e in sec("license"):
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            e["id"], os.path.basename(e["asset_ref"]), e["origin"], e["license"][:50], e["author"], e["verified"]))
    lines += ["", "## 宣称（%d 条）" % len(sec("claim")), "",
              "| id | 宣称 | status | ref |", "|---|---|---|---|"]
    for e in sec("claim"):
        lines.append("| %s | %s | %s | %s |" % (e["id"], e["claim"], e["status"], e["ref"]))
    lines += ["", "## 资产（%d 条）" % len(sec("asset")), "",
              "| id | 文件 | md5 | role |", "|---|---|---|---|"]
    for e in sec("asset"):
        lines.append("| %s | %s | %s | %s |" % (e["id"], e["path"], e["md5"][:12], e["role"]))
    out = args.out or os.path.join(_pdir(args), "LEDGER.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("LEDGER.md → %s" % out)
    return 0


def sync_task(workdir, ledger_dir):
    """供 task_queue --ledger 调用：账本落在 ledger_dir/_ledger/（项目级），workdir 只作对账数据源。
    init(若无) + cost-sync，幂等。返回新增条数。"""
    a = _Args(project=ledger_dir)
    if not os.path.exists(lp(a)):
        a.name = os.path.basename(os.path.normpath(ledger_dir))
        cmd_init(a)
    before = _count(a)
    a2 = _Args(project=ledger_dir, task_dir=workdir)
    cmd_cost_sync(a2)
    return _count(a2) - before


class _Args(object):
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _count(a):
    m = load(a)
    return len(m["entries"])


def main():
    ap = argparse.ArgumentParser(description="制片账本 v1.7-c（四账闭环 · 防篡改）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(sp, with_project=True):
        if with_project:
            sp.add_argument("--project", required=True, help="项目目录（账本在其 _ledger/ 下）")
        sp.set_defaults(func=None)
        return sp

    p = add(sub.add_parser("init")); p.add_argument("--name", required=True); p.add_argument("--force", action="store_true"); p.set_defaults(func=cmd_init)
    p = add(sub.add_parser("cost-add"))
    p.add_argument("--kind", required=True); p.add_argument("--provider", required=True); p.add_argument("--item", required=True)
    p.add_argument("--qty", type=int, default=1); p.add_argument("--unit", default="credit")
    p.add_argument("--est-lo", type=float, default=None); p.add_argument("--est-hi", type=float, default=None)
    p.add_argument("--evidence", required=True); p.add_argument("--note", default=""); p.set_defaults(func=cmd_cost_add)
    p = add(sub.add_parser("cost-sync")); p.add_argument("--task-dir", required=True); p.set_defaults(func=cmd_cost_sync)
    p = add(sub.add_parser("license-add"))
    p.add_argument("--asset-ref", required=True); p.add_argument("--origin", required=True,
              choices=["customer", "ai_generated", "stock", "font", "third_party"])
    p.add_argument("--license", required=True); p.add_argument("--author", default="")
    p.add_argument("--provider", default=""); p.add_argument("--source-url", default="")
    p.add_argument("--verified", action="store_true"); p.add_argument("--note", default=""); p.set_defaults(func=cmd_license_add)
    p = add(sub.add_parser("claim-add"))
    p.add_argument("--claim", required=True); p.add_argument("--status", required=True,
              choices=["refused", "pending_client", "approved", "approved_rewritten", "removed"])
    p.add_argument("--ref", required=True); p.add_argument("--window", default=""); p.add_argument("--note", default="")
    p.set_defaults(func=cmd_claim_add)
    p = add(sub.add_parser("claim-set"))
    p.add_argument("--id", required=True); p.add_argument("--status", required=True)
    p.add_argument("--ref", default=""); p.add_argument("--note", default=""); p.set_defaults(func=cmd_claim_set)
    p = add(sub.add_parser("asset-register"))
    p.add_argument("--path", required=True); p.add_argument("--role", default="intermediate",
              choices=["deliverable", "intermediate", "reference"])
    p.add_argument("--evidence", default=""); p.add_argument("--note", default=""); p.set_defaults(func=cmd_asset_register)
    p = add(sub.add_parser("check")); p.set_defaults(func=cmd_check)
    p = add(sub.add_parser("close")); p.set_defaults(func=cmd_close)
    p = add(sub.add_parser("verify")); p.set_defaults(func=cmd_verify)
    p = add(sub.add_parser("md")); p.add_argument("--out", default=None); p.set_defaults(func=cmd_md)

    args = ap.parse_args()
    sys.exit(args.func(args) or 0)


if __name__ == "__main__":
    main()
