# -*- coding: utf-8 -*-
"""
stock_footage.py —— 外部素材检索（备用 · 仅作「参考构图」）

★★ 红线（写死，不可配置 · 违反即退出码 3）★★
  1. 外部检索来的素材，**真人面孔默认进黑名单**：未经面孔筛查的条目一律 `face_status=unscanned`，
     筛查出人脸的条目一律 `blacklisted`，两者都不得作为拍摄依据以外的任何用途。
  2. **不得直接进成片**。本工具产出的一切条目 `role = "reference_composition_only"`、
     `deliverable_eligible = false`，只可作为「参考构图」发给客户看构图/光线/景别。
     交付成片必须由客户自己的实拍、或我们生成/拍摄的素材构成 —— 本模块不提供任何"入片"通道。
  3. 每条素材必须登记来源与许可（provider / url / license / fetched_at / sha256），
     无来源记录者不得进入参考包。
  4. 参考包必须随附 `RED_LINE.md`（本文件头两段原文），发给客户时一并给。

为什么这么严：
  库存素材"可商用"≠"可替客户背书"。真人脸出现在品牌片里，等于让陌生人替客户做产品证言，
  肖像权与广告法双重风险；且观众会误认其为品牌方人员。宁可只当构图参考，也不进片。

v1.7-b 新增（2026-10-30）：
  1. provider 扩到 archive.org / wikimedia（免 key；许可由 API 元数据登记）。
  2. **强制物理水印**：凡产出参考图（视频抽帧或原图），必须叠加半透明窄边水印
     「REFERENCE ONLY ｜ 参考构图·禁止直接使用」——参考包里**只允许出现带水印版**，
     原始下载件标 raw_internal_only=true，仅供内部构图研究，不得外发。
  3. **参考构图说明卡**：每条素材随附 md 卡片（来源/许可/作者/规格/构图观察留白），随参考包发放。

用法：
  python stock_footage.py search --query "雪夜 古装" --provider offline \
        --offline-dir "D:\\素材库" --orientation portrait --min-duration 2 --out manifest.json
  python stock_footage.py search --query "city timelapse" --provider archive --limit 3 --out m.json
  python stock_footage.py search --query "harbor sunset" --provider wikimedia --limit 3 --out m.json
  python stock_footage.py download --manifest m.json --ids 1,2 --out-dir refdl     # 下载→抽帧→水印→说明卡
  python stock_footage.py scan-faces --manifest manifest.json --report faces.json   # 人工/脚本回填
  python stock_footage.py promote --manifest manifest.json --id 2 --face-status no_faces \
        --approver "客户A" --note "客户确认仅作参考"
  python stock_footage.py export --manifest manifest.json --out-dir refpack --ids 1,2
  python stock_footage.py policy --assert          # 供 SOP/CI 校验红线仍在

依赖：仅标准库 + imageio_ffmpeg（探测/抽帧）+ Pillow（水印）；联网 provider 免 key。
"""
import argparse
import hashlib
import io
import json
import os
import sys
import time
import urllib.parse
import urllib.request

# v1.8.0 修复：禁止重包 sys.stdout（旧 TextIOWrapper 被 GC 时会关闭共享 buffer，
# 导致同进程后续 import 者的 stdout 整体死亡）；改为仅当编码非 utf-8 时 reconfigure。
try:
    if (sys.stdout.encoding or "").lower().replace("-", "") != "utf8":
        sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROLE = "reference_composition_only"
DELIVERABLE_ELIGIBLE = False          # 硬常量：任何路径都不得改成 True
RED_LINE = (
    "外部检索素材：真人面孔默认黑名单；不得直接进成片；"
    "只可作为「参考构图」发给客户；每条须登记来源与许可。"
)
WM_TEXT_L = "REFERENCE ONLY"
WM_TEXT_R = "参考构图·禁止直接使用"
WM_ALPHA = 150                        # 半透明窄边水印（0 透明 – 255 不透明）


def sha256f(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def probe(path):
    """返回 (duration_s, w, h, fps)；失败返回 None"""
    try:
        import imageio_ffmpeg
        import re
        import subprocess
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        r = subprocess.run([ff, "-hide_banner", "-i", path], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        s = r.stderr
        d = re.search(r"Duration: (\d+):(\d+):([\d.]+)", s)
        v = re.search(r"Video: .*?(\d{2,5})x(\d{2,5})", s)
        fps = re.search(r"([\d.]+) fps", s)
        if not d:
            return None
        dur = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3))
        w, h = (int(v.group(1)), int(v.group(2))) if v else (0, 0)
        return round(dur, 2), w, h, float(fps.group(1)) if fps else None
    except Exception:
        return None


def orientation_of(w, h):
    if not w or not h:
        return "unknown"
    if h > w * 1.05:
        return "portrait"
    if w > h * 1.05:
        return "landscape"
    return "square"


def item(path, provider, license_note, url=None, author="", media_type="video"):
    p = probe(path)
    dur, w, h, fps = p if p else (None, 0, 0, None)
    return {
        "id": None,
        "path": os.path.abspath(path),
        "provider": provider,
        "url": url,
        "author": author,
        "media_type": media_type,            # video | image
        "license": license_note,
        "duration_s": dur,
        "width": w,
        "height": h,
        "fps": fps,
        "orientation": orientation_of(w, h),
        "role": ROLE,
        "deliverable_eligible": DELIVERABLE_ELIGIBLE,
        "face_status": "unscanned",          # unscanned | no_faces | has_faces(blacklisted)
        "blacklisted": False,
        "sha256": sha256f(path),
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "notes": "",
    }


def search_offline(args):
    exts = (".mp4", ".mov", ".m4v", ".webm")
    out = []
    for root, _, files in os.walk(args.offline_dir):
        for fn in files:
            if fn.lower().endswith(exts):
                out.append(os.path.join(root, fn))
    items = [item(p, "offline", "本地素材：来源与许可由提供方负责", None) for p in out]
    return items


def search_pexels(args):
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        raise SystemExit("缺少 PEXELS_API_KEY（或改用 --provider offline）")
    q = urllib.parse.urlencode({"query": args.query, "per_page": min(args.limit * 2, 40),
                                "orientation": args.orientation if args.orientation != "any" else ""})
    req = urllib.request.Request("https://api.pexels.com/videos/search?" + q,
                                 headers={"Authorization": key})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    items = []
    for v in data.get("videos", []):
        if (v.get("duration") or 0) < args.min_duration:
            continue
        files = sorted(v.get("video_files", []), key=lambda f: -(f.get("height") or 0))
        if not files:
            continue
        f = files[0]
        items.append({
            "id": None, "path": None, "provider": "pexels", "url": f.get("link"),
            "license": "Pexels License（免费商用，署名非必需；不得转售原素材）",
            "duration_s": v.get("duration"), "width": f.get("width"), "height": f.get("height"),
            "fps": None, "orientation": orientation_of(f.get("width") or 0, f.get("height") or 0),
            "role": ROLE, "deliverable_eligible": DELIVERABLE_ELIGIBLE,
            "face_status": "unscanned", "blacklisted": False, "sha256": None,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "notes": "未下载：参考包须先经人脸筛查与许可登记",
        })
        if len(items) >= args.limit:
            break
    return items


def _http_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "stock_footage/1.7b (reference-composition research)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _http_download(url, dst, max_bytes):
    req = urllib.request.Request(url, headers={"User-Agent": "stock_footage/1.7b (reference-composition research)"})
    n = 0
    with urllib.request.urlopen(req, timeout=120) as r, open(dst, "wb") as f:
        while True:
            b = r.read(1 << 18)
            if not b:
                break
            n += len(b)
            if n > max_bytes:
                f.close()
                os.remove(dst)
                raise SystemExit("下载超过上限 %d MB：%s" % (max_bytes >> 20, url))
            f.write(b)
    return n


def _strip_html(s):
    import re as _re
    return _re.sub(r"<[^>]+>", "", s or "").strip()


def search_archive(args):
    """Internet Archive 视频检索（免 key）。许可来自元数据 licenseurl。"""
    q = urllib.parse.quote("(%s) AND mediatype:movies" % args.query)
    fl = "&fl%5B%5D=identifier&fl%5B%5D=title&fl%5B%5D=creator&fl%5B%5D=licenseurl"
    api = ("https://archive.org/advancedsearch.php?q=%s%s&rows=%d&page=1&output=json"
           % (q, fl, min(args.limit * 3, 50)))
    data = _http_json(api)
    docs = (data.get("response") or {}).get("docs") or []
    items = []
    for doc in docs:
        ident = doc.get("identifier")
        if not ident:
            continue
        try:
            meta = _http_json("https://archive.org/metadata/" + ident)
        except Exception:
            continue
        files = [f for f in meta.get("files", [])
                 if str(f.get("name", "")).lower().endswith((".mp4", ".m4v"))]
        if not files:
            continue
        files.sort(key=lambda f: int(f.get("size") or 1 << 60))
        f0 = files[0]
        title = doc.get("title") or meta.get("metadata", {}).get("title") or ident
        creator = doc.get("creator") or meta.get("metadata", {}).get("creator") or ""
        lic = meta.get("metadata", {}).get("licenseurl") or ""
        lic_note = lic if lic else "Internet Archive：许可以条目页为准（登记待补）"
        url = "https://archive.org/download/%s/%s" % (ident, urllib.parse.quote(f0["name"]))
        items.append({
            "id": None, "path": None, "provider": "archive.org", "url": url,
            "author": _strip_html(creator if isinstance(creator, str) else "; ".join(creator)),
            "media_type": "video",
            "license": lic_note,
            "duration_s": None, "width": int(f0.get("width") or 0), "height": int(f0.get("height") or 0),
            "fps": None,
            "orientation": orientation_of(int(f0.get("width") or 0), int(f0.get("height") or 0)),
            "role": ROLE, "deliverable_eligible": DELIVERABLE_ELIGIBLE,
            "face_status": "unscanned", "blacklisted": False, "sha256": None,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "notes": "title=%s | file=%s (%s MB) | 未下载：参考包须先经人脸筛查与许可登记"
                     % (str(title)[:80], f0.get("name"), round(int(f0.get("size") or 0) / 1048576, 1)),
        })
        if len(items) >= args.limit:
            break
    return items


def search_wikimedia(args):
    """Wikimedia Commons 图片检索（免 key）。许可来自 extmetadata。"""
    q = urllib.parse.quote(args.query)
    api = ("https://commons.wikimedia.org/w/api.php?action=query&generator=search"
           "&gsrsearch=%s&gsrnamespace=6&gsrlimit=%d&prop=imageinfo"
           "&iiprop=url|size|extmetadata&iiurlwidth=1600&format=json"
           % (q, min(args.limit * 3, 30)))
    data = _http_json(api)
    pages = (data.get("query") or {}).get("pages") or {}
    items = []
    for pid, pg in pages.items():
        ii = (pg.get("imageinfo") or [{}])[0]
        if not ii.get("thumburl"):
            continue
        em = ii.get("extmetadata") or {}
        lic = (em.get("LicenseShortName") or {}).get("value") or "Commons：许可待补"
        artist = _strip_html((em.get("Artist") or {}).get("value"))
        items.append({
            "id": None, "path": None, "provider": "wikimedia", "url": ii["thumburl"],
            "author": artist, "media_type": "image",
            "license": lic,
            "duration_s": None,
            "width": ii.get("thumbwidth") or ii.get("width"), "height": ii.get("thumbheight") or ii.get("height"),
            "fps": None,
            "orientation": orientation_of(ii.get("thumbwidth") or 0, ii.get("thumbheight") or 0),
            "role": ROLE, "deliverable_eligible": DELIVERABLE_ELIGIBLE,
            "face_status": "unscanned", "blacklisted": False, "sha256": None,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "notes": "title=%s | page=%s | 未下载：参考包须先经人脸筛查与许可登记"
                     % (str(pg.get("title"))[:80], ii.get("descriptionurl") or "?"),
        })
        if len(items) >= args.limit:
            break
    return items


def _cjk_font(size):
    from PIL import ImageFont
    for fp in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\arial.ttf"):
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


def watermark_still(src, dst):
    """强制物理水印：顶部半透明窄边「REFERENCE ONLY ｜ 参考构图·禁止直接使用」。
    返回水印信息 dict。任何进参考包的图都必须过这里。"""
    from PIL import Image, ImageDraw
    im = Image.open(src).convert("RGBA")
    w, h = im.size
    band = max(36, w // 28)
    fs = max(14, int(band * 0.48))
    font = _cjk_font(fs)
    ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    d.rectangle([0, 0, w, band], fill=(0, 0, 0, WM_ALPHA))
    y = max(2, (band - fs) // 2)
    d.text((12, y), WM_TEXT_L, font=font, fill=(255, 255, 255, 200))
    tw = d.textlength(WM_TEXT_R, font=font)
    d.text((w - tw - 12, y), WM_TEXT_R, font=font, fill=(255, 255, 255, 200))
    Image.alpha_composite(im, ov).convert("RGB").save(dst, quality=92)
    return {"style": "top_band", "band_h": band, "alpha": WM_ALPHA,
            "text_left": WM_TEXT_L, "text_right": WM_TEXT_R}


def _still_from_video(video, dst_png):
    """视频中部抽一帧作构图参考静帧。"""
    import imageio_ffmpeg
    import subprocess
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    p = probe(video)
    dur = p[0] if p else None
    ss = ["-ss", str(max(0.0, (dur or 0) * 0.45))]
    r = subprocess.run([ff, "-y"] + ss + ["-i", video, "-frames:v", "1", dst_png],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not os.path.exists(dst_png):
        raise SystemExit("抽帧失败：%s\n%s" % (video, r.stderr[-400:]))
    return dur


def cmd_download(args):
    """下载 → （视频抽帧）→ 强制水印 → 构图说明卡；manifest 回填本地信息。
    参考包只允许带水印版；原始下载件 raw_internal_only=true，仅供内部构图研究。"""
    m = _load(args.manifest)
    ids = [int(x) for x in args.ids.split(",")] if args.ids else [i["id"] for i in m["items"]]
    raw_dir = os.path.join(args.out_dir, "raw")
    ref_dir = os.path.join(args.out_dir, "watermarked")
    card_dir = os.path.join(args.out_dir, "cards")
    for d in (raw_dir, ref_dir, card_dir):
        os.makedirs(d, exist_ok=True)
    done = 0
    for it in m["items"]:
        if it["id"] not in ids:
            continue
        if not it.get("url"):
            print("  跳过 #%d：无 url（offline 条目请直接用 export）" % it["id"])
            continue
        ext = ".mp4" if it.get("media_type") == "video" else ".jpg"
        raw = os.path.join(raw_dir, "item_%02d%s" % (it["id"], ext))
        print("  下载 #%d ← %s" % (it["id"], it["url"]))
        _http_download(it["url"], raw, args.max_mb << 20)
        it["raw_path"] = os.path.abspath(raw)
        it["raw_internal_only"] = True
        it["sha256"] = sha256f(raw)
        p = probe(raw)
        if p:
            it["duration_s"], it["width"], it["height"], it["fps"] = p[0], p[1], p[2], p[3]
            it["orientation"] = orientation_of(p[1], p[2])
        still = os.path.join(raw_dir, "item_%02d_still.png" % it["id"])
        if it.get("media_type") == "video":
            _still_from_video(raw, still)
        else:
            from PIL import Image
            Image.open(raw).convert("RGB").save(still)
        ref = os.path.join(ref_dir, "ref_%02d.jpg" % it["id"])
        it["watermark"] = watermark_still(still, ref)
        it["ref_path"] = os.path.abspath(ref)
        it["path"] = it["ref_path"]           # 导出走 ref_path（见 cmd_export）
        it["notes"] = (it.get("notes") or "") + " | 已下载+水印（%s）" % time.strftime("%m-%d %H:%M")
        _write_card(card_dir, it)
        print("  #%d 完成：水印版 %s ＋ 说明卡" % (it["id"], os.path.basename(ref)))
        done += 1
    _save(args.manifest, m)
    print("download 完成 %d 条；manifest 已回填（参考包只许带水印版，raw 仅供内部研究）" % done)
    return 0


def _write_card(card_dir, it):
    """参考构图说明卡：来源/许可/作者/规格/水印声明/红线/构图观察留白。"""
    fp = os.path.join(card_dir, "ref_%02d_构图说明卡.md" % it["id"])
    with open(fp, "w", encoding="utf-8") as f:
        f.write("""# 参考构图说明卡 · REF-%02d

| 项 | 值 |
|---|---|
| 标题/备注 | %s |
| 来源 | %s（%s） |
| 原始地址 | %s |
| 作者/上传者 | %s |
| 许可 | %s |
| 抓取时间 | %s |
| 媒体类型 | %s |
| 规格 | %sx%s · %.1fs · %s |
| 文件 | %s（sha256 %s） |
| 水印 | 顶部窄边半透明「%s ｜ %s」（band %spx, alpha %s） |
| role | %s（deliverable_eligible=%s） |
| 人脸状态 | %s%s |

## 红线（随卡生效）

%s
参考包内只允许出现带水印版；原始下载件仅供内部构图研究，不得外发、不得剪入成片。

## 构图观察（人工填写，外发前必须补齐）

- 景别/机位：
- 光线/时段：
- 可借鉴点（只借构图，不借内容）：
- 不可借鉴点（为什么不适合本项目）：
""" % (it["id"],
       (it.get("notes") or "").split(" | 未下载")[0][:80] or "（见原始地址）",
       it.get("provider"), it.get("media_type"), it.get("url"),
       it.get("author") or "（未登记）",
       it.get("license"), it.get("fetched_at"),
       it.get("media_type"),
       it.get("width"), it.get("height"), it.get("duration_s") or 0, it.get("orientation"),
       os.path.basename(it.get("path") or "?"), (it.get("sha256") or "?")[:12],
       WM_TEXT_L, WM_TEXT_R,
       (it.get("watermark") or {}).get("band_h", "?"), (it.get("watermark") or {}).get("alpha", "?"),
       ROLE, DELIVERABLE_ELIGIBLE,
       it.get("face_status"), "（已列黑名单）" if it.get("blacklisted") else "",
       RED_LINE))
    return fp


def cmd_search(args):
    if args.provider == "offline":
        items = search_offline(args)
    elif args.provider == "pexels":
        items = search_pexels(args)
    elif args.provider == "archive":
        items = search_archive(args)
    elif args.provider == "wikimedia":
        items = search_wikimedia(args)
    else:
        raise SystemExit("暂支持 offline / pexels / archive / wikimedia")

    if args.orientation != "any":
        items = [i for i in items if i["orientation"] == args.orientation]
    if args.min_duration:
        items = [i for i in items if (i["duration_s"] or 0) >= args.min_duration]
    items = items[:args.limit]
    for n, it in enumerate(items, 1):
        it["id"] = n

    manifest = {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "query": args.query,
        "provider": args.provider,
        "red_line": RED_LINE,
        "role_allowed": ROLE,
        "deliverable_eligible_any": False,
        "count": len(items),
        "items": items,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print("检索 %d 条 → %s" % (len(items), args.out))
    print("红线：%s" % RED_LINE)
    for it in items:
        print("  #%d %s  %.1fs %sx%s  face=%s  role=%s" % (
            it["id"], os.path.basename(it["path"] or it["url"] or "?"),
            it["duration_s"] or 0, it["width"], it["height"], it["face_status"], it["role"]))


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save(path, m):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=2)


def cmd_scan_faces(args):
    """回填人脸筛查结果：report = {"<item_id>": "no_faces"|"has_faces"}"""
    m = _load(args.manifest)
    rep = _load(args.report)
    n = 0
    for it in m["items"]:
        st = rep.get(str(it["id"]))
        if st == "no_faces":
            if it["face_status"] == "has_faces" or it["blacklisted"]:
                print("  #%d 保持黑名单：人脸判定不可逆（如需恢复请新建素材条目）" % it["id"])
                continue
            it["face_status"] = "no_faces"
        elif st == "has_faces":
            it["face_status"] = "has_faces"
            it["blacklisted"] = True
            it["notes"] = "检测到真人面孔：进黑名单，仅可作构图参考，不得入片"
        else:
            continue
        n += 1
    _save(args.manifest, m)
    print("回填 %d 条人脸筛查结果" % n)


def cmd_promote(args):
    """确认用途：只把 face_status 提到 no_faces 并记审批；role 永不改变"""
    m = _load(args.manifest)
    hit = [i for i in m["items"] if i["id"] == args.id]
    if not hit:
        raise SystemExit("manifest 里没有 id=%s" % args.id)
    it = hit[0]
    if args.face_status != "no_faces":
        raise SystemExit("拒绝：promote 只接受 --face-status no_faces（有脸即黑名单）")
    if it["face_status"] == "has_faces":
        raise SystemExit("拒绝：该条已判定有人脸，不可提升")
    it["face_status"] = "no_faces"
    it["approval"] = {"approver": args.approver, "note": args.note,
                      "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    it["role"] = ROLE                      # 写死，不允许改
    it["deliverable_eligible"] = False
    _save(args.manifest, m)
    print("已确认 #%d 为 no_faces（role 仍为 %s，deliverable_eligible=%s）"
          % (args.id, ROLE, DELIVERABLE_ELIGIBLE))


def cmd_export(args):
    m = _load(args.manifest)
    ids = [int(x) for x in args.ids.split(",")] if args.ids else [i["id"] for i in m["items"]]
    os.makedirs(args.out_dir, exist_ok=True)
    picked = [i for i in m["items"] if i["id"] in ids]
    for it in picked:
        if it["blacklisted"] or it["face_status"] == "has_faces":
            print("  跳过 #%d：人脸黑名单" % it["id"])
            continue
        if not it["path"] or not os.path.exists(it["path"]):
            print("  跳过 #%d：本地文件缺失（仅登记 URL）" % it["id"])
            continue
        dst = os.path.join(args.out_dir, "ref_%02d_%s" % (it["id"], os.path.basename(it["path"])))
        src = it.get("ref_path") or it["path"]   # v1.7-b：优先带水印版
        if it.get("ref_path") and not it.get("watermark"):
            print("  跳过 #%d：无水印记录（拒绝入包）" % it["id"])
            continue
        base = os.path.basename(src)
        name = base if base.startswith("ref_") else "ref_%02d_%s" % (it["id"], base)
        dst = os.path.join(args.out_dir, name)
        with open(src, "rb") as s, open(dst, "wb") as d:
            for b in iter(lambda: s.read(1 << 20), b""):
                d.write(b)
        print("  复制 #%d -> %s" % (it["id"], os.path.basename(dst)))
    with open(os.path.join(args.out_dir, "RED_LINE.md"), "w", encoding="utf-8") as f:
        f.write("# 参考构图素材包 · 红线\n\n" + RED_LINE + "\n\n"
                "本包仅用于与客户沟通构图/光线/景别，**不得作为成片素材**，\n"
                "不得剪入任何交付片；真人面孔条目已列入黑名单。\n")
    with open(os.path.join(args.out_dir, "manifest_ref.json"), "w", encoding="utf-8") as f:
        json.dump({"role_allowed": ROLE, "deliverable_eligible_any": False,
                   "items": picked}, f, ensure_ascii=False, indent=2)
    print("参考包已生成：%s（含 RED_LINE.md）" % args.out_dir)


def cmd_policy(args):
    print("role_allowed            :", ROLE)
    print("deliverable_eligible    :", DELIVERABLE_ELIGIBLE)
    print("red_line                :", RED_LINE)
    assert ROLE == "reference_composition_only" and DELIVERABLE_ELIGIBLE is False
    if args.assert_:
        print("ASSERT: OK（红线常量未被改动）")
    return 0


def main():
    ap = argparse.ArgumentParser(description="外部素材检索（仅作参考构图，红线写死）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("search")
    p.add_argument("--query", default="")
    p.add_argument("--provider", default="offline",
                   choices=["offline", "pexels", "archive", "wikimedia"])
    p.add_argument("--offline-dir")
    p.add_argument("--orientation", default="any", choices=["any", "portrait", "landscape", "square"])
    p.add_argument("--min-duration", type=float, default=0)
    p.add_argument("--limit", type=int, default=6)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("download")
    p.add_argument("--manifest", required=True)
    p.add_argument("--ids", default="")
    p.add_argument("--out-dir", required=True)
    p.add_argument("--max-mb", type=int, default=80, help="单文件下载上限（MB）")
    p.set_defaults(func=cmd_download)

    p = sub.add_parser("scan-faces")
    p.add_argument("--manifest", required=True)
    p.add_argument("--report", required=True)
    p.set_defaults(func=cmd_scan_faces)

    p = sub.add_parser("promote")
    p.add_argument("--manifest", required=True)
    p.add_argument("--id", type=int, required=True)
    p.add_argument("--face-status", default="no_faces")
    p.add_argument("--approver", required=True)
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_promote)

    p = sub.add_parser("export")
    p.add_argument("--manifest", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--ids", default="")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("policy")
    p.add_argument("--assert", dest="assert_", action="store_true")
    p.set_defaults(func=cmd_policy)

    args = ap.parse_args()
    sys.exit(args.func(args) or 0)


if __name__ == "__main__":
    main()
