# -*- coding: utf-8 -*-
"""_env_check.py —— 运行环境自检（v1.6.0 云端兼容；v1.8.0: ffmpeg/Pillow/numpy 三项即四工具 task_queue/stock_footage/ledger/structure_card 共同依赖检查）

**开工前跑一次**：缺依赖 ⇒ 给"保底方案"，不是崩。

用法:
    python _env_check.py

退出码：0 全绿 ／ 3 缺关键依赖（可降级运行）
"""

# --- 控制台兼容：中文 Windows 默认 GBK，打印 ✓/✗/⇒/⚠ 会抛 UnicodeEncodeError ---
try:
    import sys as _sys
    _sys.stdout.reconfigure(errors="replace")
    _sys.stderr.reconfigure(errors="replace")
except Exception:
    pass
import io, os, sys, json, shutil, subprocess

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")


def find_ffmpeg():
    """三级查找：imageio_ffmpeg 捆绑 → PATH → 常见路径"""
    # ① imageio_ffmpeg（最可能：本机隔离环境装了）
    try:
        import imageio_ffmpeg
        p = imageio_ffmpeg.get_ffmpeg_exe()
        if p and os.path.isfile(p):
            return p, "imageio_ffmpeg"
    except Exception:
        pass
    # ② PATH
    p = shutil.which("ffmpeg")
    if p:
        return p, "PATH"
    # ③ 常见路径（Windows / Linux 各一份）
    for c in (r"C:\ffmpeg\bin\ffmpeg.exe", "/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg",
              "/opt/homebrew/bin/ffmpeg"):
        if os.path.isfile(c):
            return c, "common_path"
    return None, None


def main():
    rep = {"checked_at": None, "python": sys.version.split()[0], "items": {}, "verdict": None}

    import datetime
    rep["checked_at"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")

    # ffmpeg
    ff, src = find_ffmpeg()
    rep["items"]["ffmpeg"] = {"found": bool(ff), "path": ff, "source": src}
    if ff:
        r = subprocess.run([ff, "-hide_banner", "-version"], capture_output=True, text=True)
        rep["items"]["ffmpeg"]["version"] = (r.stdout.splitlines() or ["?"])[0][:80]

    # Pillow（接触表/接触图用）
    try:
        import PIL
        rep["items"]["Pillow"] = {"found": True, "version": getattr(PIL, "__version__", "?")}
    except Exception:
        rep["items"]["Pillow"] = {"found": False}

    # numpy（media_check 判黑边用）
    try:
        import numpy
        rep["items"]["numpy"] = {"found": True, "version": numpy.__version__}
    except Exception:
        rep["items"]["numpy"] = {"found": False}

    critical_ok = rep["items"]["ffmpeg"]["found"]
    rep["verdict"] = "OK" if critical_ok else "DEGRADED"

    # ★ 降级方案（缺 ffmpeg 时给客户/AI 的话术）
    rep["fallback"] = {
        "when_ffmpeg_missing": [
            "**当前环境未找到 ffmpeg**，无法自动抽帧/测规格。",
            "**替代方案（三选一，都是能交付的）**：",
            "① **请手动上传分镜图/关键帧截图**（每段 1 张即可），我按图写结构；",
            "② **你口述参考片**（说了什么/拍了什么/大概几秒一镜），我按描述写结构卡；",
            "③ **你自己用手机截 3–5 张图**发我，我照样能拆。",
            "**不影响出片** —— 只影响「自动抽帧」这一步。",
        ],
        "when_pillow_missing": ["接触表无法生成 ⇒ 改为逐张抽帧给你看（更慢但不影响判断）"],
        "when_numpy_missing": ["黑边自动判失效 ⇒ 请目检四边（我给出判断方法）"],
        "rule": "**降级不报错，给下一步动作。** 环境问题不是客户的错。",
    }

    print(json.dumps(rep, ensure_ascii=False, indent=1))

    if not critical_ok:
        print()
        print("=== 降级提示（请原样转述给客户）===")
        for line in rep["fallback"]["when_ffmpeg_missing"]:
            print("  " + line)

    return 0 if critical_ok else 3


if __name__ == "__main__":
    sys.exit(main())
