#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""env_probe.py —— 依赖探测：python / ffmpeg / ffprobe 在哪、缺什么、怎么装。

本包所有文档与脚本都**不写死路径**，统一走这里。解决了「别人 clone 下来第一步就报错」的问题。

用法
----
    python tools/env_probe.py                  # 人类可读报告
    python tools/env_probe.py --json           # 机器可读（CI / 脚本用）
    python tools/env_probe.py --print ffmpeg   # 只打印一个路径（供 shell 取值）
    python tools/env_probe.py --print env      # 打印可直接 eval 的环境变量
    python tools/env_probe.py --check          # 关键依赖缺失时退出码 1

取值顺序（逐级回落，任何一级命中即返回）
----------------------------------------
    1. 环境变量：FFMPEG / FFPROBE / PYTHON_BIN
    2. 系统 PATH（shutil.which）
    3. imageio-ffmpeg 自带的可执行文件（`pip install imageio-ffmpeg` 后即可用）
    4. 常见安装位置（Windows 程序目录 / Homebrew / /usr/local/bin）
    5. 都找不到 → 打印修复命令 + 退出码 1，**不抛 traceback**

为什么 ffprobe 常缺失却不要紧：imageio-ffmpeg 只带 ffmpeg，而本包全部脚本都用
`ffmpeg -hide_banner -i <文件>` 解析 "Duration / Stream"，不依赖独立 ffprobe。
"""
from __future__ import annotations

# --- 控制台兼容：中文 Windows 默认 GBK，打印 ✓/✗/⇒/⚠ 会抛 UnicodeEncodeError ---
try:
    import sys as _sys
    _sys.stdout.reconfigure(errors="replace")
    _sys.stderr.reconfigure(errors="replace")
except Exception:
    pass

import json
import os
import platform
import shutil
import subprocess
import sys

IS_WIN = os.name == "nt"
EXE = ".exe" if IS_WIN else ""


def _unicode_console():
    """中文 Windows 控制台默认 GBK，打印 ✓/✗ 会直接抛 UnicodeEncodeError。
    这里只判断能否安全输出，不强行改编码（改 UTF-8 反而会让中文变乱码）。"""
    enc = (getattr(sys.stdout, "encoding", None) or "").lower().replace("-", "")
    return enc in ("utf8", "utf8mb4", "cp65001", "65001", "utf_8")


UOK = _unicode_console()
OK = "✓" if UOK else "[OK]"
NG = "✗" if UOK else "[X]"
DASH = "─" if UOK else "-"

# 常见安装位置（只在 PATH 与 imageio 都没有时才用）
COMMON = {
    "win32": [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        os.path.expanduser(r"~\scoop\shims\ffmpeg.exe"),
        os.path.expanduser(r"~\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe"),
    ],
    "darwin": ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"],
    "linux": ["/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/snap/bin/ffmpeg"],
}


def _ok(path):
    return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def _from_imageio():
    """imageio-ffmpeg 自带的可执行文件（最稳的兜底：pip 装过就在）。"""
    try:
        import imageio_ffmpeg  # noqa: WPS433
        p = imageio_ffmpeg.get_ffmpeg_exe()
        return p if _ok(p) else None
    except Exception:
        return None


def find_python():
    return os.environ.get("PYTHON_BIN") or sys.executable or shutil.which("python3") or shutil.which("python")


def find_ffmpeg():
    """返回 (path, source)；找不到返回 (None, None)。"""
    for env in ("FFMPEG", "FFMPEG_BIN"):
        p = os.environ.get(env)
        if _ok(p):
            return p, "env:%s" % env
    p = shutil.which("ffmpeg")
    if _ok(p):
        return p, "PATH"
    p = _from_imageio()
    if p:
        return p, "imageio-ffmpeg"
    for p in COMMON.get(sys.platform, []):
        if _ok(p):
            return p, "common-dir"
    return None, None


def find_ffprobe():
    p = os.environ.get("FFPROBE")
    if _ok(p):
        return p, "env:FFPROBE"
    p = shutil.which("ffprobe")
    if _ok(p):
        return p, "PATH"
    for p in COMMON.get(sys.platform, []):
        cand = os.path.join(os.path.dirname(p), "ffprobe" + EXE)
        if _ok(cand):
            return cand, "sibling"
    return None, None


def probe_all():
    ff, ff_src = find_ffmpeg()
    fp, fp_src = find_ffprobe()
    return {
        "os": "%s %s" % (platform.system(), platform.release()),
        "python": {
            "path": find_python(),
            "version": platform.python_version(),
            "executable_ok": _ok(find_python()),
        },
        "ffmpeg": {"path": ff, "source": ff_src, "ok": ff is not None},
        "ffprobe": {
            "path": fp,
            "source": fp_src,
            "ok": fp is not None,
            "note": None if fp else "缺失不影响：本包用 `ffmpeg -i` 解析时长与流信息",
        },
        "optional_modules": _modules(["numpy", "PIL", "cv2", "imageio_ffmpeg", "yaml"]),
    }


def _modules(names):
    out = {}
    for n in names:
        try:
            out[n] = bool(__import__(n))
        except Exception:
            out[n] = False
    return out


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #

HINT = """\
────────────────────────────────────────────────────────────
ffmpeg 没找到。三种办法，任选其一（推荐第 1 种，一条命令）：
  1) pip install imageio-ffmpeg        # 装完自动带上 ffmpeg 可执行文件，本包直接可用
  2) Windows: winget install Gyan.FFmpeg
     macOS:   brew install ffmpeg
     Linux:   sudo apt install ffmpeg   （或 dnf / pacman 对应包）
  3) 已经有 ffmpeg 但不在 PATH：设置环境变量 FFMPEG=<ffmpeg 可执行文件完整路径>
────────────────────────────────────────────────────────────"""


def render_text(d):
    L = []
    L.append("环境探测报告")
    L.append("=" * 52)
    L.append("系统      : %s" % d["os"])
    py = d["python"]
    L.append("Python    : %s (%s)" % (py["version"], py["path"]))
    ff = d["ffmpeg"]
    if ff["ok"]:
        L.append("ffmpeg    : %s  [来源 %s]" % (ff["path"], ff["source"]))
    else:
        L.append("ffmpeg    : %s 未找到" % NG)
    fp = d["ffprobe"]
    if fp["ok"]:
        L.append("ffprobe   : %s  [来源 %s]" % (fp["path"], fp["source"]))
    else:
        L.append("ffprobe   : - 缺失（%s）" % (fp["note"] or "不影响"))
    L.append(DASH * 52)
    L.append("可选模块  :")
    for k, v in d["optional_modules"].items():
        L.append("  %-14s %s" % (k, OK if v else "- 未装"))
    L.append(DASH * 52)
    if not ff["ok"]:
        L.append(HINT.replace("─", DASH))
        L.append("结论：%s 关键依赖缺失，先按上面任一办法装 ffmpeg 再回来。" % NG)
    else:
        missing = [k for k, v in d["optional_modules"].items() if not v]
        if missing:
            L.append("结论：%s 关键依赖齐备；可选模块缺 %s。" % (OK, "、".join(missing)))
            L.append("      需要图像处理/编码相关脚本时：pip install %s"
                     % " ".join({"PIL": "Pillow", "cv2": "opencv-python",
                                 "yaml": "pyyaml", "imageio_ffmpeg": "imageio-ffmpeg"}.get(m, m)
                                for m in missing))
        else:
            L.append("结论：%s 全部就绪，可以开工。" % OK)
    return "\n".join(L)


def main(argv):
    args = argv[1:]
    if "--json" in args:
        print(json.dumps(probe_all(), ensure_ascii=False, indent=1))
        return 0
    if "--check" in args:
        d = probe_all()
        rc = 0 if d["ffmpeg"]["ok"] else 1
        print(render_text(d))
        return rc
    if "--print" in args:
        i = args.index("--print")
        what = args[i + 1] if i + 1 < len(args) else ""
        if what == "python":
            print(find_python())
            return 0
        if what == "ffmpeg":
            p, _ = find_ffmpeg()
            if not p:
                sys.stderr.write(HINT + "\n")
                return 1
            print(p)
            return 0
        if what == "ffprobe":
            p, _ = find_ffprobe()
            if not p:
                sys.stderr.write("无独立 ffprobe，请改用 `env_probe.py --print ffmpeg` 配合 `-i` 解析。\n")
                return 1
            print(p)
            return 0
        if what == "env":
            ff, _ = find_ffmpeg()
            print('export PYTHON_BIN="%s"' % find_python())
            if ff:
                print('export FFMPEG="%s"' % ff)
            return 0
        sys.stderr.write("未知参数：--print %s（可选 python|ffmpeg|ffprobe|env）\n" % what)
        return 2
    d = probe_all()
    print(render_text(d))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:  # 兜底：绝不把 traceback 甩给用户
        sys.stderr.write("探测过程出错：%s\n请把上面这行连同系统信息反馈给我们。\n" % exc)
        sys.exit(1)
