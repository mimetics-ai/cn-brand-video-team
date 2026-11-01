# -*- coding: utf-8 -*-
"""
task_queue.py —— 单节点可重跑的制片任务队列（v1.7-a1 · 2026-10-29）

v1.7-a 三件套（相对 v0.9）：
  1) 资源分通道：锁名从 gpu/cpu 扩为 provider:jimeng / provider:seedance / provider:tts / cpu
     （旧 "gpu" 自动映射为 provider:jimeng，兼容既有 spec）
  2) 额度退避：节点因额度耗尽退出（默认 rc=75 或 stderr 命中 quota 关键词）⇒ 记 suspended(quota)，
     按 1/2/4/8/16/30 分钟指数退避（spec 可覆盖），到点自动从断点续跑；已完成节点保留（产物 md5 复核）
  3) 幂等键：idem_key = md5(task_id + node_id + cmd + 上游产物 md5)。
     命中且已有 provider_job_id ⇒ 不再下单，改走"复用/查询"通道（node 收到 TQ_REUSE_JOB）

v1.7-a1（仅一处收紧）：幂等键补入「节点声明的输入文件 md5」与 params。
  病因：只改提示词/参考图而不改 cmd，旧版会判为"同一次任务"并复用旧 job，
        把上一版提示词生成的画面当新结果交付（致命逻辑雷）。
  改法：node 可声明 prompt / prompt_file / first_frame / refs / ref_images / input_files，
        逐个算 md5 进 payload["files"]；params 进 payload["params"]。
        文件缺失 ⇒ 节点直接 failed（不猜、不带病下单）。
        变更时打 idem_changed 事件，写明是哪个文件的 md5 变了。
  兼容：没声明任何输入文件的节点，payload 结构与 v1.7-a 完全一致（不额外加空键），
        既有 state 里的 idem_key 不会因升级而集体失效。

节点模型：script → video ∥ audio → subtitle → check
用法：
  python task_queue.py init  --spec task.json
  python task_queue.py run   --task <workdir> [--rerun subtitle] [--only check] [--no-auto-resume]
  python task_queue.py queue --spec a.json --spec b.json
  python task_queue.py status|verify|fix|resume --task <workdir>

节点可选字段：
  resource            锁名，默认 cpu；provider 类节点写 provider:jimeng 等
  provider            供应商名（有值才启用幂等复用）
  prompt / prompt_file  提示词文件（相对 workdir 或绝对路径），md5 进幂等键
  first_frame         首帧图，同上
  refs / ref_images   参考图列表，同上
  input_files         任意其他输入文件列表，同上
  params              影响出片的参数（时长/种子/运镜…），整体进幂等键
  quota_exit_codes    额度耗尽退出码列表，默认 [75]
  quota_pattern       额度耗尽 stderr 正则，默认见 QUOTA_PATTERN
  lock_wait           等锁上限秒，默认 1800

Task 级可选字段：
  backoff_s           退避秒序列，默认 [60,120,240,480,960,1800]
  max_quota_rounds    单节点最多退避轮数，默认 6
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
import io
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta

# v1.8.0 修复：禁止重包 sys.stdout（旧 TextIOWrapper 被 GC 时会关闭共享 buffer，
# 导致同进程后续 import 者的 stdout 整体死亡）；改为仅当编码非 utf-8 时 reconfigure。
try:
    if (sys.stdout.encoding or "").lower().replace("-", "") != "utf8":
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

STATE_VERSION = 2
DEFAULT_TIMEOUT = 900
SUSPEND_EXIT = 2          # check 节点：自检不过，挂起等人
QUOTA_EXIT = 75           # 供应商额度耗尽（EX_TEMPFAIL 约定）
QUOTA_PATTERN = r"quota|insufficient|rate.?limit|too many requests|429|额度|余额不足|限流"
TAIL = 1500
LEGACY_RESOURCE = {"gpu": "provider:jimeng", "cpu": "cpu"}


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def md5f(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def pid_alive(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        PROCESS_QUERY_LIMITED = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
        if not h:
            return False
        code = wintypes.DWORD()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return bool(ok) and code.value == 259
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def atomic_write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def norm_resource(r):
    return LEGACY_RESOURCE.get(r or "cpu", r or "cpu")


class ResourceLock:
    """跨进程文件锁：同一 resource 同时只允许一个持有者（供应商分通道）"""

    def __init__(self, lock_dir, resource, who, ttl=1800):
        self.resource = norm_resource(resource)
        safe = self.resource.replace(":", "_")
        self.path = os.path.join(lock_dir, "%s.lock" % safe)
        self.who = who
        self.ttl = ttl
        self.held = False

    def acquire(self, wait=1800, poll=0.2):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        t_start = time.time()
        deadline = t_start + wait
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, ("%d\t%s\n" % (os.getpid(), self.who)).encode("utf-8"))
                os.close(fd)
                self.held = True
                return True, round(time.time() - t_start, 2)
            except FileExistsError:
                stale, age = self._is_stale()
                if stale:
                    try:
                        os.remove(self.path)
                    except OSError:
                        pass
                    continue
                if time.time() > deadline:
                    return False, age
                time.sleep(poll)

    def _is_stale(self):
        try:
            with open(self.path, "r", encoding="utf-8", errors="ignore") as f:
                first = f.readline().strip().split("\t")
            pid = int(first[0]) if first and first[0].isdigit() else -1
            age = time.time() - os.path.getmtime(self.path)
            return (not pid_alive(pid)) or age > self.ttl, age
        except OSError:
            return True, 0.0

    def release(self):
        if self.held:
            try:
                os.remove(self.path)
            except OSError:
                pass
            self.held = False


def state_path(workdir):
    return os.path.join(workdir, "state.json")


def load_state(workdir):
    p = state_path(workdir)
    if not os.path.exists(p):
        raise SystemExit("找不到状态文件：%s" % p)
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(workdir, st):
    st["updated"] = now()
    atomic_write_json(state_path(workdir), st)


def event(workdir, task, name, node=None, detail=None):
    rec = {"ts": now(), "task": task, "event": name, "node": node, "detail": detail}
    with open(os.path.join(workdir, "events.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def downstream(nodes, node_id):
    out, stack = set(), [node_id]
    while stack:
        cur = stack.pop()
        for n in nodes:
            if cur in n.get("deps", []) and n["id"] not in out:
                out.add(n["id"])
                stack.append(n["id"])
    return out


def topo(nodes):
    done, order = set(), []
    while len(order) < len(nodes):
        progressed = False
        for n in nodes:
            if n["id"] in done:
                continue
            if all(d in done for d in n.get("deps", [])):
                order.append(n)
                done.add(n["id"])
                progressed = True
        if not progressed:
            raise SystemExit("节点依赖存在环或缺失：%s" % [n["id"] for n in nodes if n["id"] not in done])
    return order


def verify_outputs(workdir, node, rec):
    outs = rec.get("outputs") or {}
    if not node.get("outputs"):
        return True, "无声明产物"
    bad = []
    for rel in node["outputs"]:
        p = os.path.join(workdir, rel)
        if not os.path.exists(p) or os.path.getsize(p) == 0:
            bad.append("%s 缺失/为空" % rel)
            continue
        if rel in outs and outs[rel].get("md5") and outs[rel]["md5"] != md5f(p):
            bad.append("%s md5 漂移" % rel)
    return (not bad), ("; ".join(bad) if bad else "产物核验一致")


def collect_input_files(node):
    """把节点上声明的输入文件字段收成一个有序去重列表（保留声明路径写法）"""
    decls = []
    for k in ("prompt", "prompt_file", "first_frame"):
        v = node.get(k)
        if v:
            decls.append(v)
    for k in ("refs", "ref_images", "input_files"):
        v = node.get(k)
        if not v:
            continue
        if isinstance(v, str):
            v = [v]
        decls.extend(v)
    seen, out = set(), []
    for d in decls:
        key = os.path.normcase(os.path.abspath(d))
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def input_digests(workdir, node):
    """返回 (files, missing)：files=[相对声明路径:md5]，missing=[缺失或空文件的声明]"""
    files, missing = [], []
    for decl in collect_input_files(node):
        p = decl if os.path.isabs(decl) else os.path.join(workdir, decl)
        if not os.path.exists(p) or os.path.getsize(p) == 0:
            missing.append(decl)
            continue
        files.append("%s:%s" % (decl.replace("\\", "/"), md5f(p)))
    return files, missing


def diff_inputs(old_files, new_files, old_params, new_params):
    """解释这次幂等键为什么变了（审计用，不参与判定）"""
    def split(xs):
        d = {}
        for x in xs or []:
            path, _, dig = x.rpartition(":")
            d[path] = dig
        return d

    od, nd = split(old_files), split(new_files)
    changed = [k for k in nd if k in od and od[k] != nd[k]]
    added = [k for k in nd if k not in od]
    removed = [k for k in od if k not in nd]
    parts = []
    if changed:
        parts.append("文件内容变更: " + ", ".join(changed))
    if added:
        parts.append("新增文件: " + ", ".join(added))
    if removed:
        parts.append("移除文件: " + ", ".join(removed))
    if (old_params or {}) != (new_params or {}):
        parts.append("params 变更")
    if not parts:
        parts.append("上游产物或 cmd 变更")
    return "；".join(parts)


def idem_payload(task_id, node, st, files):
    """幂等键的原料：任务 + 节点 + cmd + 上游产物 md5 + 输入文件 md5 + params"""
    inputs = []
    for d in sorted(node.get("deps", [])):
        for rel, meta in sorted((st["nodes"][d].get("outputs") or {}).items()):
            inputs.append("%s:%s" % (rel, meta.get("md5")))
    payload = {"task": task_id, "node": node["id"], "cmd": node["cmd"], "inputs": inputs}
    # 只在真有输入文件/参数时才加键，保证「没声明的节点」键与 v1.7-a 完全一致
    if files:
        payload["files"] = files
    if node.get("params"):
        payload["params"] = node["params"]
    return payload


def idem_key(payload):
    return hashlib.md5(json.dumps(payload, ensure_ascii=False,
                                  sort_keys=True).encode("utf-8")).hexdigest()


def classify_failure(node, rc, tail):
    """返回 (kind, why)：kind ∈ quota / suspend / fail"""
    codes = node.get("quota_exit_codes") or [QUOTA_EXIT]
    pat = re.compile(node.get("quota_pattern") or QUOTA_PATTERN, re.I)
    if rc in codes or pat.search(tail or ""):
        return "quota", "额度耗尽信号（rc=%s）" % rc
    if rc == SUSPEND_EXIT or rc in (node.get("suspend_codes") or []):
        return "suspend", "自检不过（rc=%s）" % rc
    return "fail", "rc=%s" % rc


def run_node(workdir, node, st, lock_dir):
    """执行单个节点。返回 done / quota / suspend / fail"""
    nid = node["id"]
    rec = st["nodes"][nid]
    resource = norm_resource(node.get("resource", "cpu"))

    # v1.7-a1：先验输入文件，缺了就当场判死，不带病下单（也不白占资源锁）
    files, missing = input_digests(workdir, node)
    if missing:
        rec.update(status="failed", finish=now(),
                   error="声明的输入文件缺失/为空：%s" % ", ".join(missing))
        event(workdir, st["task_id"], "input_missing", nid, {"files": missing})
        save_state(workdir, st)
        return "fail"

    lock = ResourceLock(lock_dir, resource, "%s/%s" % (st["task_id"], nid))
    ok, waited = lock.acquire(wait=node.get("lock_wait", 1800))
    if not ok:
        rec.update(status="failed", error="资源锁等待超时（%.0fs）: %s" % (waited, resource))
        event(workdir, st["task_id"], "lock_timeout", nid, {"resource": resource})
        return "fail"

    key = idem_key(idem_payload(st["task_id"], node, st, files))
    prev_key = rec.get("idem_key")
    reuse_job = None
    if node.get("provider") and rec.get("provider_job_id"):
        if prev_key == key:
            reuse_job = rec["provider_job_id"]
            event(workdir, st["task_id"], "reuse", nid, {"job_id": reuse_job, "idem_key": key})
        else:
            why = diff_inputs(rec.get("input_files"), files, rec.get("params"), node.get("params"))
            event(workdir, st["task_id"], "idem_changed", nid,
                  {"old": (prev_key or "-")[:12], "new": key[:12], "why": why})

    rec.update(status="running", start=now(), attempts=rec.get("attempts", 0) + 1,
               lock_wait_round=round(waited, 2), idem_key=key,
               input_files=files, params=node.get("params") or {},
               reused=bool(reuse_job))
    save_state(workdir, st)
    event(workdir, st["task_id"], "node_start", nid,
          {"attempt": rec["attempts"], "resource": resource, "lock_wait": round(waited, 2),
           "reuse_job": reuse_job, "idem_key": key[:12], "files": len(files)})

    env = os.environ.copy()
    env.update({k: str(v) for k, v in (node.get("env") or {}).items()})
    env.update({"TQ_TASK_ID": st["task_id"], "TQ_NODE_ID": nid, "TQ_IDEM_KEY": key,
                "TQ_WORKDIR": workdir})
    if reuse_job:
        env["TQ_REUSE_JOB"] = reuse_job

    t0 = time.time()
    try:
        pr = subprocess.run(node["cmd"], cwd=workdir, env=env,
                            timeout=node.get("timeout", DEFAULT_TIMEOUT),
                            capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
        rc, out, err = pr.returncode, pr.stdout or "", pr.stderr or ""
    except subprocess.TimeoutExpired as e:
        rc, out, err = -9, (e.stdout or ""), "TIMEOUT after %ss" % node.get("timeout", DEFAULT_TIMEOUT)
    dur = round(time.time() - t0, 2)
    lock.release()

    tail = ((out or "") + (("\n[stderr]\n" + err) if err else ""))[-TAIL:]
    rec.update(rc=rc, duration_s=dur, tail=tail)

    # v1.7-a2：job 号只认「本节点」的，避免同目录节点互相串号（成本台账会算错）
    if node.get("provider"):
        cand = [os.path.join(workdir, "out", ".job.%s.json" % nid),
                os.path.join(workdir, "out", ".job.json")]
        for job_file in cand:
            if not os.path.exists(job_file):
                continue
            try:
                with open(job_file, encoding="utf-8") as f:
                    jid = json.load(f).get("job_id")
            except Exception:
                continue
            if jid:
                rec["provider_job_id"] = jid
                break

    if rc == 0:
        vok, why = verify_outputs(workdir, node, {"outputs": {}})
        if not vok:
            rec.update(status="failed", finish=now(), error="rc=0 但产物未生效：%s" % why)
            event(workdir, st["task_id"], "node_failed", nid, {"why": "rc=0_output_missing"})
            save_state(workdir, st)
            return "fail"
        digests = {}
        for rel in node.get("outputs") or []:
            p = os.path.join(workdir, rel)
            digests[rel] = {"md5": md5f(p), "bytes": os.path.getsize(p)}
        rec.update(status="done", finish=now(), outputs=digests, error=None,
                   suspend_reason=None, resume_at=None)
        event(workdir, st["task_id"], "node_done", nid,
              {"duration_s": dur, "outputs": digests, "reused": bool(rec.get("reused"))})
        save_state(workdir, st)
        return "done"

    kind, why = classify_failure(node, rc, tail)
    if kind == "quota":
        rec.update(status="suspended", finish=now(), suspend_reason="quota",
                   error=(tail or "")[-400:] or why)
        event(workdir, st["task_id"], "quota_suspended", nid, {"rc": rc, "why": why})
        save_state(workdir, st)
        return "quota"
    if kind == "suspend":
        rec.update(status="suspended", finish=now(), suspend_reason="review",
                   error=(tail or "")[-400:] or why)
        event(workdir, st["task_id"], "node_suspended", nid, {"rc": rc})
        save_state(workdir, st)
        return "suspend"

    rec.update(status="failed", finish=now(), error="rc=%d" % rc)
    event(workdir, st["task_id"], "node_failed", nid, {"rc": rc})
    save_state(workdir, st)
    return "fail"


def run_task(workdir, spec_nodes, only=None, rerun=None, resume=False, lock_dir=None,
             auto_resume=True):
    st = load_state(workdir)
    with open(st["spec"], "r", encoding="utf-8") as f:
        spec = json.load(f)
    backoff = spec.get("backoff_s") or [60, 120, 240, 480, 960, 1800]
    max_rounds = int(spec.get("max_quota_rounds", 6))
    lock_dir = lock_dir or os.path.join(os.path.dirname(workdir.rstrip("\\/")), "_locks")
    nodes = {n["id"]: n for n in spec_nodes}
    order = topo(spec_nodes)

    if rerun:
        hit = set()
        for rid in rerun:
            if rid not in nodes:
                raise SystemExit("未知节点：%s（可选 %s）" % (rid, list(nodes)))
            hit.add(rid)
            hit |= downstream(spec_nodes, rid)
        for nid in hit:
            if nid != only:
                st["nodes"][nid].update(status="pending", outputs={}, error=None,
                                        suspend_reason=None, resume_at=None)
        event(workdir, st["task_id"], "invalidate", None, {"nodes": sorted(hit)})
        if st["status"] in ("done", "failed", "suspended"):
            st["status"] = "running"

    for n in spec_nodes:
        rec = st["nodes"][n["id"]]
        if rec["status"] == "done":
            vok, why = verify_outputs(workdir, n, rec)
            if not vok:
                rec.update(status="pending", error="续跑复核未过：" + why)
                for d in downstream(spec_nodes, n["id"]):
                    st["nodes"][d].update(status="pending", error="上游产物漂移")
                event(workdir, st["task_id"], "stale", n["id"], {"why": why})

    if resume:
        for n in spec_nodes:
            if st["nodes"][n["id"]]["status"] == "suspended":
                st["nodes"][n["id"]].update(status="pending", error=None, suspend_reason=None)
        event(workdir, st["task_id"], "resume", None, {})

    st["status"] = "running"
    save_state(workdir, st)

    for n in order:
        nid = n["id"]
        if only and nid != only:
            continue
        rec = st["nodes"][nid]
        if rec["status"] == "done":
            continue
        if rec["status"] == "suspended" and rec.get("suspend_reason") != "quota" and not only:
            st["status"] = "suspended"
            save_state(workdir, st)
            event(workdir, st["task_id"], "task_suspended", nid, {"reason": "review"})
            return "suspended"
        bad = [d for d in n.get("deps", []) if st["nodes"][d]["status"] != "done"]
        if bad:
            rec.update(status="pending", error="上游未完成：%s" % bad)
            st["status"] = "failed"
            save_state(workdir, st)
            event(workdir, st["task_id"], "blocked", nid, {"deps": bad})
            return "failed"

        while True:
            res = run_node(workdir, n, st, lock_dir)
            if res == "quota":
                rnd = int(rec.get("quota_round", 0))
                if not auto_resume or rnd >= max_rounds:
                    rec.update(resume_at=None, quota_round=rnd)
                    st["status"] = "suspended"
                    save_state(workdir, st)
                    event(workdir, st["task_id"], "task_suspended", nid,
                          {"reason": "quota", "rounds": rnd, "auto_resume": auto_resume})
                    return "suspended"
                delay = float(backoff[min(rnd, len(backoff) - 1)])
                resume_at = (datetime.now().astimezone()
                             + timedelta(seconds=delay)).isoformat(timespec="seconds")
                rec.update(status="pending", quota_round=rnd + 1, resume_at=resume_at,
                           error=None)
                st["quota_waited_s"] = round(float(st.get("quota_waited_s", 0)) + delay, 2)
                save_state(workdir, st)
                event(workdir, st["task_id"], "quota_backoff", nid,
                      {"round": rnd + 1, "delay_s": delay, "resume_at": resume_at})
                time.sleep(delay)
                continue
            break

        if res == "suspend" and not only:
            st["status"] = "suspended"
            save_state(workdir, st)
            return "suspended"
        if res != "done":
            st["status"] = "failed"
            save_state(workdir, st)
            return "failed"

    all_done = all(st["nodes"][n["id"]]["status"] == "done" for n in spec_nodes)
    st["status"] = "done" if all_done else ("suspended" if any(
        st["nodes"][n["id"]]["status"] == "suspended" for n in spec_nodes) else "pending")
    save_state(workdir, st)
    event(workdir, st["task_id"], "task_" + st["status"], None, {})
    return st["status"]


def cmd_init(args):
    with open(args.spec, "r", encoding="utf-8") as f:
        spec = json.load(f)
    workdir = os.path.abspath(spec.get("workdir") or os.path.join(
        os.path.dirname(os.path.abspath(args.spec)), spec["task_id"]))
    os.makedirs(workdir, exist_ok=True)
    sp = state_path(workdir)
    if os.path.exists(sp) and not args.force:
        raise SystemExit("状态已存在：%s（要重来加 --force）" % sp)
    nodes = spec["nodes"]
    topo(nodes)
    st = {
        "state_version": STATE_VERSION,
        "task_id": spec["task_id"],
        "spec": os.path.abspath(args.spec),
        "spec_md5": md5f(args.spec),
        "created": now(),
        "updated": now(),
        "status": "pending",
        "workdir": workdir,
        "quota_waited_s": 0,
        "nodes": {n["id"]: {"status": "pending", "attempts": 0, "outputs": {},
                            "start": None, "finish": None, "rc": None,
                            "duration_s": None, "error": None, "tail": None,
                            "idem_key": None, "provider_job_id": None,
                            "input_files": [], "params": {},
                            "reused": False, "quota_round": 0,
                            "suspend_reason": None, "resume_at": None}
                  for n in nodes},
    }
    save_state(workdir, st)
    event(workdir, st["task_id"], "init", None,
          {"nodes": [n["id"] for n in nodes],
           "resources": {n["id"]: norm_resource(n.get("resource", "cpu")) for n in nodes}})
    print("已初始化 %s -> %s" % (st["task_id"], workdir))
    print("节点顺序：", " -> ".join(n["id"] for n in topo(nodes)))
    print("资源通道：", {n["id"]: norm_resource(n.get("resource", "cpu")) for n in nodes})


def load_spec_for(workdir):
    st = load_state(workdir)
    with open(st["spec"], "r", encoding="utf-8") as f:
        return json.load(f)


def cmd_run(args):
    st = load_state(args.workdir)
    spec = load_spec_for(args.workdir)
    rerun = [x.strip() for x in (args.rerun or "").split(",") if x.strip()]
    status = run_task(args.workdir, spec["nodes"], only=args.only, rerun=rerun,
                      resume=args.resume, lock_dir=args.lock_dir,
                      auto_resume=not args.no_auto_resume)
    print("任务 %s 结束状态：%s" % (st["task_id"], status))
    # v1.7-c 账本自动同步（幂等；失败只警告不阻断——events.jsonl 是证据源，可重放补记）
    ledger_dir = getattr(args, "ledger", None)
    if ledger_dir:
        try:
            import ledger
            os.environ.setdefault("TQ_LEDGER_DIR", ledger_dir)
            n = ledger.sync_task(args.workdir, ledger_dir)
            print("账本已同步：%d 条 → %s/_ledger/ledger.json" % (n, args.workdir))
        except SystemExit as e:
            print("!! 账本同步被拒（队列结果不受影响）：%s" % e)
        except Exception as e:
            print("!! 账本同步失败（队列结果不受影响，可 cost-sync 重放）：%r" % (e,))
    return 0 if status == "done" else (2 if status == "suspended" else 1)


def cmd_status(args):
    st = load_state(args.workdir)
    if args.json:
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return 0
    print("任务 %s ｜ 状态 %s ｜ 更新 %s ｜ 额度等待 %.1fs"
          % (st["task_id"], st["status"], st["updated"], float(st.get("quota_waited_s", 0))))
    for nid, rec in st["nodes"].items():
        outs = ",".join(rec.get("outputs") or {}) or "-"
        flags = []
        if rec.get("provider_job_id"):
            flags.append("job=%s" % rec["provider_job_id"])
        if rec.get("reused"):
            flags.append("reused")
        if rec.get("quota_round"):
            flags.append("quota_r=%d" % rec["quota_round"])
        if rec.get("input_files"):
            flags.append("files=%d" % len(rec["input_files"]))
        print("  %-9s %-9s tries=%d %s  rc=%s  %s %s" % (
            nid, rec["status"], rec.get("attempts", 0),
            ("%ss" % rec["duration_s"]) if rec.get("duration_s") is not None else "-",
            rec.get("rc"), outs, " ".join(flags)))
        if rec.get("error"):
            print("            ! %s" % str(rec["error"])[:200].replace("\n", " "))
    return 0


def cmd_fix(args):
    st = load_state(args.workdir)
    rec = st["nodes"][args.node]
    rec.update(status="pending", error=None, suspend_reason=None, resume_at=None,
               fix_note={"at": now(), "note": args.note or "人工修正"})
    st["status"] = "running"
    save_state(args.workdir, st)
    event(args.workdir, st["task_id"], "human_fix", args.node, {"note": args.note})
    print("节点 %s 已置为 pending（人工修正记录：%s）；接着跑 resume" % (args.node, args.note))
    return 0


def cmd_verify(args):
    st = load_state(args.workdir)
    spec = load_spec_for(args.workdir)
    bad = 0
    for n in spec["nodes"]:
        rec = st["nodes"][n["id"]]
        if rec["status"] != "done":
            continue
        ok, why = verify_outputs(args.workdir, n, rec)
        print("  %-9s %s" % (n["id"], "OK" if ok else "FAIL: " + why))
        bad += 0 if ok else 1
    print("结论：%s" % ("全部产物 md5 一致" if not bad else "%d 个节点产物漂移" % bad))
    return 0 if not bad else 1


def cmd_queue(args):
    results = []
    for spec_path in args.spec:
        with open(spec_path, "r", encoding="utf-8") as f:
            spec = json.load(f)
        workdir = os.path.abspath(spec.get("workdir") or os.path.join(
            os.path.dirname(os.path.abspath(spec_path)), spec["task_id"]))
        if not os.path.exists(state_path(workdir)):
            cmd_init(argparse.Namespace(spec=spec_path, force=False))
        t0 = time.time()
        try:
            status = run_task(workdir, spec["nodes"], lock_dir=args.lock_dir,
                              auto_resume=not args.no_auto_resume)
        except SystemExit as e:
            status = "failed(%s)" % e
        results.append({"task": spec["task_id"], "status": status,
                        "duration_s": round(time.time() - t0, 2)})
        print("---- %s : %s" % (spec["task_id"], status))
        # v1.7-c 账本自动同步（同 cmd_run 口径：失败只警告不阻断）
        ledger_dir = getattr(args, "ledger", None)
        if ledger_dir:
            try:
                import ledger
                n = ledger.sync_task(workdir, ledger_dir)
                print("账本已同步：%d 条 → %s/_ledger/ledger.json" % (n, workdir))
            except SystemExit as e:
                print("!! 账本同步被拒（队列结果不受影响）：%s" % e)
            except Exception as e:
                print("!! 账本同步失败（队列结果不受影响，可 cost-sync 重放）：%r" % (e,))
    print(json.dumps({"summary": results}, ensure_ascii=False, indent=2))
    return 0 if all(r["status"] == "done" for r in results) else 1


def main():
    ap = argparse.ArgumentParser(description="单节点可重跑的制片任务队列 v1.7-a1")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init")
    p.add_argument("--spec", required=True)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("run")
    p.add_argument("--task", dest="workdir", required=True)
    p.add_argument("--only")
    p.add_argument("--rerun")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--lock-dir")
    p.add_argument("--no-auto-resume", action="store_true", help="额度耗尽不自动等，直接挂起收工")
    p.add_argument("--ledger", help="项目目录：收工自动同步 _ledger/ledger.json（v1.7-c）")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("status")
    p.add_argument("--task", dest="workdir", required=True)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("fix")
    p.add_argument("--task", dest="workdir", required=True)
    p.add_argument("--node", required=True)
    p.add_argument("--note")
    p.set_defaults(func=cmd_fix)

    p = sub.add_parser("resume")
    p.add_argument("--task", dest="workdir", required=True)
    p.add_argument("--lock-dir")
    p.add_argument("--ledger")
    p.set_defaults(func=lambda a: cmd_run(argparse.Namespace(
        workdir=a.workdir, only=None, rerun=None, resume=True, lock_dir=a.lock_dir,
        no_auto_resume=False, ledger=getattr(a, "ledger", None))))

    p = sub.add_parser("verify")
    p.add_argument("--task", dest="workdir", required=True)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("queue")
    p.add_argument("--spec", action="append", required=True)
    p.add_argument("--lock-dir")
    p.add_argument("--no-auto-resume", action="store_true")
    p.add_argument("--ledger", help="项目目录：每单收工自动同步 _ledger/ledger.json（v1.7-c）")
    p.set_defaults(func=cmd_queue)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
