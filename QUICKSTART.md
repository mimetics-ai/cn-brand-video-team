# QUICKSTART · 10 分钟跑通

> 目标：**不装显卡、不要 API Key、不花一分钱**，十分钟内看到三个真实结果。
> 全流程在 Windows 11 / Python 3.13 上实测通过；macOS / Linux 把命令里的 `python` 换成 `python3` 即可。

## 你会得到什么

| # | 结果 | 证明什么 |
|---|---|---|
| 1 | 一份环境探测报告 | 你的机器缺什么、一条命令怎么补 |
| 2 | 一份七层结构卡（`card.json` + `card.md`） | 拆解逻辑真的能跑，不是 PPT |
| 3 | 一次禁词扫描 + 一个空白台账 | 合规与成本这两道闸是能落地的 |

---

## 0 · 前提（2 分钟）

- **Python 3.9+**（推荐 3.10 以上）。Windows 安装时**务必勾选 Add Python to PATH**。
- **git**（可选，也可以直接下载 zip 解压）。
- 不需要：独立显卡、ffmpeg（装了更好，没装会自动回落到 pip 版）、任何生成式账号。

## 1 · 拿到代码（30 秒）

```bash
git clone https://github.com/mimetics-ai/cn-brand-video-team.git
cd cn-brand-video-team
```

## 2 · 探测依赖（1 分钟）

```bash
python tools/env_probe.py
```

**预期输出**（Windows 实测，你的路径会不同）：

```
环境探测报告
====================================================
系统      : Windows 11
Python    : 3.13.14 (C:\...\python.exe)
ffmpeg    : C:\...\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe  [来源 imageio-ffmpeg]
ffprobe   : - 缺失（缺失不影响：本包用 `ffmpeg -i` 解析时长与流信息）
----------------------------------------------------
可选模块  :
  numpy          ✓
  PIL            ✓
  imageio_ffmpeg ✓
----------------------------------------------------
结论：✓ 全部就绪，可以开工。
```

**如果 ffmpeg 显示 ✗ 未找到** —— 一条命令解决，不用配 PATH：

```bash
pip install imageio-ffmpeg
```

装完再跑一次 `python tools/env_probe.py`，`ffmpeg` 那行会变成 `[来源 imageio-ffmpeg]`。

## 3 · 装可选模块（1 分钟）

```bash
pip install imageio-ffmpeg pillow numpy
```

- 要做抠图 / 人脸筛查 → `pip install opencv-python`
- 要读 yaml 配置 → `pip install pyyaml`

## 4 · 跑通四件事（4 分钟）

### 4.1 结构卡：把一段文案拆成七层

```bash
python tools/structure_card.py analyze --text samples/demo_script.txt --out card.json --name "示例30s"
```

预期：

```
结构卡 → card.json（hash=<每次不同，内容指纹>，text）
七层：/hook/beats/visual_grammar/subtitle_style/broll_rules/fx_sound/pacing/ ｜ 节拍 19 拍 ｜ 时长 93.8s
```

再转成人读版：

```bash
python tools/structure_card.py md --card card.json --out card.md
```

> ⚠️ **那个 93.8s 是整段文本的粗估**，只用来对齐节拍结构，**不是交付时长**。
> 真实时长必须按分镜的逐镜帧数相加来断言——这正是本包和"一键生成"的区别之一。

### 4.2 禁词扫描：先判，再改

```bash
python tools/banword_scan_local.py samples/demo_script.txt
```

预期：

```
词典 v1.6.1 ｜ 扫描 1 个文件 ｜ 硬违规 0 处 ｜ 待复核 0 处
【硬违规】0 处 ✅
```

> 试试故意加一句"全网第一、100% 见效"，再跑一次，看它怎么标红。

### 4.3 台账：开工前先开账

```bash
mkdir my_proj
python tools/ledger.py init --project my_proj --name "我的第一条片"
```

预期：`账本已建立：my_proj/_ledger/ledger.json（我的第一条片）`

想多看一步：记一笔成本，再看账本自检

```bash
python tools/ledger.py cost-add --project my_proj --kind generate --provider none \
       --item "实拍素材（客户提供）" --evidence "客户邮件附件" --note "零生成，无积分消耗"
python tools/ledger.py check --project my_proj
```

预期：`cost +C001  none/generate 实拍素材（客户提供）…` → `check：0 项缺陷 / 0 项警告 / 条目 1`

### 4.4 看一眼还有哪些工具

```bash
python tools/task_queue.py --help
python tools/stock_footage.py --help
```

---

## 5 · 装成 WorkBuddy 专家包（3 分钟，想要「五个角色真派人」才做）

> 命令行只用到 `tools/` 里的**校验类**工具；**真正会"拍片"的是那五个角色**，
> 它们需要在 WorkBuddy 专家运行时里被调度。

把本仓库整个目录放到专家目录下：

| 系统 | 路径 |
|---|---|
| Windows | `%USERPROFILE%\.workbuddy\plugins\marketplaces\my-experts\plugins\cn-brand-video-team` |
| macOS / Linux | `~/.workbuddy/plugins/marketplaces/my-experts/plugins/cn-brand-video-team` |

重启客户端 → 专家中心 → 看到「AI短视频制片团队」即安装成功。

## 6 · 第一次开工，照着说这三句里的任意一句

- 「我有一批产品实拍素材在 `<目录>`，帮我剪一条 30 秒能过审的品牌片，横版竖版都要。」
- 「帮我逐帧检查这条片子：AI 生成面孔、广告法极限词、烧录字幕错字，出一份可复核的取证报告。」
- 「给这款产品写一条 45 秒品牌短视频的分镜脚本，含时长与语速断言。」

---

## 故障排查

| 现象 | 原因 | 怎么办 |
|---|---|---|
| `python: command not found` | 未安装或没进 PATH | 重装并勾选 Add to PATH，或改用 `py -3` |
| `ModuleNotFoundError: imageio_ffmpeg` | 没装 | `pip install imageio-ffmpeg` |
| `ffmpeg: ✗ 未找到` | 系统没装且 pip 版也没装 | 同上；或设环境变量 `FFMPEG=<完整路径>` |
| 报错里出现乱码 / 路径不存在 | 项目目录含中文或空格 | 把项目放到纯英文路径，如 `D:\work\video` |
| 结构卡时长离谱 | 文本模式按整段粗估 | 用 `--video` 走真实视频，或按分镜断言算 |
| 专家中心看不到团队 | 目录层级放错 / 没重启 | 确认路径结尾是 `plugins\cn-brand-video-team`，然后重启客户端 |
| `pip` 装得慢 | 默认源在境外 | `pip install -i https://pypi.tuna.tsinghua.edu.cn/simple imageio-ffmpeg` |

## 10 分钟时间表

> 实测：**第 3 节之后的那四步，在一台装好 Python 的机器上总共 1 秒**。
> 十分钟里 9 分钟花在装 Python 和 pip 下载上，命令本身很快。

| 时间 | 做什么 |
|---|---|
| 0–2 min | 确认 Python、拉代码 |
| 2–3 min | `env_probe.py` 探测，缺 ffmpeg 就装 |
| 3–4 min | 装可选模块 |
| 4–8 min | 跑结构卡 / 禁词 / 台账（实测 1 秒，其余是看结果的时间） |
| 8–10 min | 装成专家包（可选）、照着第 6 节开工 |

---

跑不通就在本仓库开 Issue，**把 `python tools/env_probe.py --json` 的输出贴进来**——有这份报告，八成问题一眼就能定位。
