---
name: tts-model-offline-setup
description: 在「受限网络 + 无 GPU + 沙箱受限」的 Windows 机器上，把一个开源 AI 模型（尤其声音复刻/TTS 类：CosyVoice 2、GPT-SoVITS 等）从零装到跑通、实测性能，并包成「双击即用」的窗口交付。覆盖：镜像可用性探测、git-lfs batch API 绕开模型仓 403/401、依赖闭包的穷举差集法、pip 被沙箱 SIGTERM 掐死的绕行、venv 被并发 pip 掏空后的判定与重建、CPU-only 的 RTF 实测与产出音频真伪核验、用 tkinter 包 GUI（含 pythonw 下 sys.stdout 为 None 的坑）。触发词：下载安装 CosyVoice、部署开源 TTS、模型权重下载失败、ModelScope 403、model repo 403、Authentication token does not exist、git-lfs smudge failed、pip 装到一半退出、pip 无声消失、dist-info 是空的、batch_wheel 报错、invalid command 'bdist_wheel'、from versions: none、RTF 实测、无显卡跑 TTS、声音复刻环境搭建、装在哪怎么打开、双击即用、给模型做个界面、GUI 启动器、pythonw 无控制台、tkinter 壳。
agent_created: true
---

# 受限环境下装配开源 AI 模型（TTS / 声音复刻为主）

**核心心法**：这类任务 90% 的失败不是"模型不兼容"，而是**环境层三件事**——
① 镜像/渠道选错 ② 依赖闭包漏包 ③ 沙箱把长任务掐死。所以流程必须是
**先探测、再取件、后装、最后验证**，每一步都留可复现的日志与独立判据。

> 本技能来自一次真实交付：无 NVIDIA GPU 的 Win11 机器上装 CosyVoice2-0.5B
> （Gitee 镜像代码 + ModelScope 3.79 GB 权重 + 26 个依赖），最终跑通，**CPU RTF 6.18**。

---

## 〇、先量三件事（别急着 pip）

```bash
# 1) GPU / CPU
python -c "import torch" 2>/dev/null; nvidia-smi 2>/dev/null || echo "无 NVIDIA GPU"
# 2) 磁盘
# 3) 已装/残留进程 —— ★ 最关键，见 §四
tasklist //FI "IMAGENAME eq python.exe" //FO CSV
```

**无 GPU 不等于跑不了**：主流 TTS 框架都有 CPU 降级（CosyVoice2 在
`cosyvoice/cli/cosyvoice.py` 里有显式的 `no cuda device, set load_jit/load_trt/load_vllm/fp16 to False`）。
无 GPU 只**变慢**，`RTF` 会落在 3–15（CosyVoice2 实测 6.18）。**先装，再测 RTF，再决定要不要云 GPU。**

---

## 一、镜像可用性：必须实测，不要猜

`from versions: none` **不代表包不存在**——它经常等于"索引被拒（403）"。

```python
# 探测模板（urllib 避免引依赖）：对每个源的 /simple/<pkg>/ 发 GET
ssl._create_default_https_context = ssl._create_unverified_context
for base in ["https://mirrors.aliyun.com/pypi/simple", "https://pypi.tuna.tsinghua.edu.cn/simple",
             "https://mirrors.cloud.tencent.com/pypi/simple", "https://mirrors.ustc.edu.cn/pypi/simple",
             "https://pypi.org/simple"]:
    # 看 status + body 里有没有目标版本号
```

实测结论（2026-09，某受限企业网）：

| 源 | 结果 |
|---|---|
| **阿里云** | ✅ **首选主源** |
| 腾讯云 / 中科大 / pypi.org | ✅ 都通 |
| **清华** | ❌ **HTTP 403 Forbidden** → pip 报 `from versions: none` |

> ⭐ **换源前先想 pip 缓存**：pip 的 HTTP 缓存是**按 URL** 建的。若 torch 的 217 MB 轮子
> 已从阿里云下过，改主源＝全部重下。**优先保住能命中缓存的那个源。**

**同一条纪律适用于模型仓**：ModelScope 的**网页/SDK API 失败 ≠ 拿不到文件**，
见 §三。

---

## 二、依赖闭包：用「穷举差集」，不要一个个撞

### 为什么静态分析会漏包

| 漏包类型 | 例子 | 原因 |
|---|---|---|
| **配置运行时实例化** | `lightning`、`pyarrow`、`pyworld` | HyperPyYAML 的 `!new:` / `!name:` 是**运行时** `pydoc.locate` 加载，从入口做 AST 看不见 |
| **深层传递导入** | `gdown`、`wget`、`matplotlib` | A→B→C，而 C 有顶层 `import gdown`；缺了在**加载模型时**才崩 |
| **构建期工具** | `wheel` | `--no-build-isolation` 装 sdist 时复用 venv 自带 `bdist_wheel`，没有就报 `error: invalid command 'bdist_wheel'` |

### 正确做法：扫全仓顶层 import，做差集

```python
# 源码里所有顶层 import  −  标准库  −  本地模块  −  site-packages 里已有  =  缺口
import ast, glob, os, sys
stdlib = set(sys.stdlib_module_names)
installed = {d.lower() for d in os.listdir(SP)
             if os.path.isdir(os.path.join(SP, d)) and not d.endswith((".dist-info", ".egg-info"))}
# 再扫 *.py：ast.Import / ast.ImportFrom(level==0)
```

拿到缺口后**按"是否在推理路径上"筛**：训练/服务端用的（`deepspeed`/`gradio`/`rootutils`/
`vllm`/`tensorrt`/`phonemizer`）直接跳过。**判据是 grep 谁 import 了它**，不是"名字像不像训练用"。

> ⚠️ 别用"跑一次冒烟测试看崩在哪"来迭代——加载 3.8 GB 权重一次要 1 分钟起。
> 一次列全，别来回试。

---

## 三、模型仓 403 / 401：走 **git + LFS batch API**

### 症状与真因

```
modelscope - ERROR - Authentication token does not exist,   → HTTP 403
hf.co 侧 → HTTP 401（受限仓）
```
`wetext`、`WTN` 这类小模型仓常被这样卡住；`sentencepiece`/`BPE` 类仓也常见。

### ⭐ 绕行四步（`_fetch_wetext_lfs.py` 是完整实现）

1. **先试 git 通道**（它和网页 API 是两套鉴权）：
   ```bash
   git clone https://www.modelscope.cn/<owner>/<repo>.git
   ```
   实测**通**，即使网页/SDK 都 403。
2. 仓库文件若走 **git-lfs**，本机没装 `git-lfs` 会报
   `git-lfs filter-process: command not found ... Clone succeeded, but checkout failed`
   —— **这是好消息**：`.git` 对象已到手，只差内容。
3. 从 git 里读**指针**（指针里有 `oid sha256:` + `size`）：
   ```bash
   git -C <repo> ls-tree -r --name-only HEAD        # 文件清单
   git -C <repo> cat-file -p HEAD:<path>            # 是 LFS 指针就取 oid/size
   ```
4. **打 LFS batch API 换下载链接**：
   ```
   POST https://<host>/<owner>/<repo>.git/info/lfs/objects/batch
   Headers: Accept/Content-Type: application/vnd.git-lfs+json
   Body: {"operation":"download","transfers":["basic"],
          "objects":[{"oid":"<sha256>","size":<n>}, ...]}
   → resp.objects[i].actions.download.href  然后 GET
   ```
   按 oid 去重（`prefix.fst` 与 `prefix_matcher.fst` 常同 oid）。
5. **非 LFS 的普通文件**用 `git cat-file -p HEAD:<path>` 直接写出（checkout 整体失败时它们也没落地）。

### 让库从本地读（不改源码、不改 site-packages）

很多库是 `from modelscope import snapshot_download`，**名字在它自己模块被 import 时绑定**。
所以在目标库**被 import 之前**打补丁即可：

```python
# wetext_local_fix.py —— 必须在 `import cosyvoice...` 之前 import
import modelscope
_LOCAL = r"...\_wetext_repo"
_orig = getattr(modelscope, "snapshot_download", None)
def _snapshot_download(repo_id, *a, **k):
    if "<repo-keyword>" in str(repo_id) and os.path.isdir(_LOCAL):
        return _LOCAL
    return _orig(repo_id, *a, **k)
modelscope.snapshot_download = _snapshot_download
```

⚠️ 顺序错了补丁不生效：**先 import 补丁，再 import 用它的库。**

---

## 四、⭐ 四个把 pip 弄死的环境级坑（都不是包的问题）

### 坑 A：多个 pip 并发操作同一个 venv → 互相掏空 `dist-info`

**症状**：`site-packages` 里出现**空目录**的 `*.dist-info`（连 `pip-23.0.1.dist-info` 都是空的）；
包目录还在但 `__init__.py`／`version.py` 被删 → `import x` 成功但 `x.__file__ is None`（命名空间空壳）；
pip 之后必崩：`OSError ... '<pkg>.dist-info\METADATA'`。

**根因**：上一轮的安装任务**没结束**（后台任务被遗忘），新任务又启动，两个 pip 互删。

**判据与处置**：
```bash
tasklist //FI "IMAGENAME eq python.exe" //FO CSV      # 先看有没有残留
# 找到残留的 `python.exe -m pip ...` 就杀掉，再动手
# 若 dist-info 已被掏空且涉及 pip 自身 → 修补不划算，改名归档 + 重建 venv
```

### 坑 B：长任务（含批量删除）被 **SIGTERM** —— 真因是"静默"，不是"删得多"

**⚠️ 这条极易误诊，务必记住判据**：

| 现象 | 真因 | 判据 |
|---|---|---|
| 删 torch（911 MB / 上千文件）的进程被 SIGTERM | **前台跑 + 输出被重定向** → 进程长时间不向 stdout 写东西 → 被判定挂死 | 同一份删除逻辑改成**后台跑 + 每次 flush 进度**后，**822 MB 的 venv 只用了 1.7 s 删完**，完全正常 |
| pip 解包 200 MB 轮子时被判失败 | 同上：pip 输出被 `capture_output` 收走 → 主进程静默 | 后台跑 + 日志落盘 |

**结论：不要因为怕被杀就不敢删。** 正确做法：
- 长任务一律 **`run_in_background` + 日志重定向到文件**；
- 在任务内部**每处理一项就 `print(..., flush=True)` 并把进度写进日志**（保持"活着"的信号）；
- 删除用 `shutil.rmtree(p, onerror=...)`，把被占用的文件**跳过并计数**，不要让它整批失败。

```python
def onerror(func, path, exc_info):
    errors.append((path, str(exc_info[1])[:90]))   # 杀软/残留句柄占用 → 记录后继续
shutil.rmtree(pkg_dir, onerror=onerror)
```

**仍然推荐"先改名、后删除"的两段式**：`os.rename` 是瞬时元数据操作，能立刻让
`site-packages` 变干净（pip 就可以当"全新安装"处理，不触发 uninstall 分支）；
真正的删除放到后台慢慢做。这样既不阻塞安装，也不用担心删除被打断。

### 坑 C：pip 绝不要走 uninstall 分支

`--force-reinstall` / 升级已有包都会触发 pip 的卸载（内部用 `os.rename` 做 `~<name>` stash），
在受限环境下极易被打断，留下 `~distinfo` 残骸。
**优先"先改名挪走再装"**，让每次安装都是**纯新增**：

```python
os.rename(pkg_dir, os.path.join(TRASH, os.path.basename(pkg_dir)))   # 同盘＝瞬时
# 然后 pip install，因为"看不到已安装"，就是纯新增，不触发任何卸载
```

> 连带效应：一旦 venv 里出现 `~<name>` 残骸或空 `dist-info`，pip 之后**每次**解析依赖都会崩。
> 判据：`site-packages` 里有没有 `~*` 目录、有没有缺 `METADATA` 的 `*.dist-info`
> （⚠️ `.egg-info` 用的是 `PKG-INFO`，别误报）。

---

## 五、安装与验证的顺序（照抄即可）

```bash
# 1) 主源（保住缓存的那个）+ 失败重试
python -m pip install -r requirements.txt \
  -i https://mirrors.aliyun.com/pypi/simple/ \
  --extra-index-url https://mirrors.cloud.tencent.com/pypi/simple \
  --retries 8 --timeout 180

# 2) 先装 wheel 再装需要 --no-build-isolation 的 sdist（如 openai-whisper）
python -m pip install wheel -i <主源>
python -m pip install --no-build-isolation openai-whisper==20231117 -i <主源>

# 3) ★ 必须捕获 pip 输出。只看 exit code 会把
#    "残缺 METADATA / 权限错误 / 索引 403" 一律误判成"网络问题"。
subprocess.run(args, capture_output=True, text=True, errors="replace")
```

**验证三层，缺一层都可能是假成功：**

| 层 | 判据 |
|---|---|
| ① 元数据 | `*.dist-info` **无**缺 `METADATA` 的（`.egg-info` 看 `PKG-INFO`，别误报） |
| ② 导入 | 逐个 `import` 关键模块 + 核对**版本钉子**（如 `numpy==1.26.4`；被别的包悄悄升到 2.x 会让 `pyworld` 等 C 扩展 ABI 崩） |
| ③ 端到端 | 真跑一次推理，**并且核验输出不是空的** |

### 产出音频的真伪核验（防"跑通但输出静音"）

```python
import soundfile as sf, numpy as np
data, sr = sf.read(path)
rms  = float(np.sqrt(np.mean(data ** 2)))   # 静音 ≈ 0
peak = float(np.max(np.abs(data)))          # >0.01 才算有信号；≈0.9+ 可能削波
uniq = len(np.unique(np.round(data, 6)))    # 常量=1
# 判据：rms > 0.001 and peak > 0.01 and uniq > 1000
```

---

## 六、让交付物可用：把命令行包成「双击即用」的窗口

**装完就撒手 = 交付失败。** 非技术用户拿到的是一个没图标、没窗口的目录，
一句「怎么打开」就能让整套工作白做。补一个 `tkinter` 壳（Python 标准库自带，不必装包）：

```
D:\<proj>\
├─ START_voice.bat        双击入口（文件名与内容都用纯 ASCII）
├─ START_voice_debug.bat  同上但保留控制台 + pause（排错用）
├─ voice_gui.py           界面本体
└─ _out\                  产物
```

`.bat` 就三行（**文件名和内容都别放中文**，否则 cmd 解码容易翻车）：

```bat
@echo off
cd /d "%~dp0"
start "" "%~dp0venv\Scripts\pythonw.exe" "%~dp0voice_gui.py"
```

`pythonw.exe` = 无控制台、不留黑窗；排错版换成 `python.exe` 并在末尾 `pause`。

### ⚠️ 坑：`pythonw` 下 `sys.stdout` / `sys.stderr` 是 `None`

`print()` 直接 `AttributeError`，**第三方库内部的 `logging` 同样会炸**。
必须在**任何库被 import 之前**重定向（接到文件上，方便事后查）：

```python
os.makedirs(LOG_DIR, exist_ok=True)
_fh = open(os.path.join(LOG_DIR, "gui.log"), "a", encoding="utf-8", buffering=1)
if sys.stdout is None: sys.stdout = _fh
if sys.stderr is None: sys.stderr = _fh
```

### ⚠️ 坑：venv 的 `pythonw.exe` 是 stub，`tasklist` 里会出现**两个**同名进程

判据：**内存大的那个才是真正干活的**（内存 ≈ 权重体积，如 3.8 GB 权重 → 约 4.2 GB 常驻）。
关掉时两个都要杀，否则留孤儿进程占内存。按命令行过滤杀最稳：

```powershell
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
  Where-Object { $_.CommandLine -like '*voice_gui.py*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

### 界面设计要点（针对"加载慢"这个事实）

- **启动即后台预加载模型**，加载期间允许输入文字——别让用户对着灰界面干等；
- 耗时操作全放**后台线程**，日志经 `queue` 回主线程写 `Text`（tkinter 非线程安全）；
- 明确告诉用户「**模型只加载一次**，之后只付合成时间，窗口别关」——这句话能把 RTF 偏高的心理成本降一半；
- 按钮：合成 / 播放（`winsound.PlaySound(p, SND_FILENAME | SND_ASYNC)`，支持 wav）/ 打开输出目录（`os.startfile`）；
- 留一个 `--selftest` 开关：**不开窗口**走完「加载 → 合成 → 落盘」，便于无人值守回归。

### 桌面快捷方式：Windows 交付的"最后一公里"

用户说"能不能在桌面上放一个直接打开的"时，就是这一步。两条路容易撞墙：

**① PowerShell 建不了** —— `New-Object -ComObject WScript.Shell` 常被安全策略拦
（实测报 `COM object instantiation can run arbitrary code`）。
改用 **Python + pywin32**（`pip install pywin32`，6.9 MB 纯轮子）：

```python
import pythoncom
from win32com.shell import shell, shellcon

link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None,
                                  pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
link.SetPath(r"...\venv\Scripts\pythonw.exe")        # pythonw = 不留黑窗
link.SetArguments('"%s"' % gui_py)
link.SetWorkingDirectory(proj_dir)
link.SetIconLocation(icon_ico, 0)
link.QueryInterface(pythoncom.IID_IPersistFile).Save(lnk_path, 0)

desk = shell.SHGetFolderPath(0, shellcon.CSIDL_DESKTOPDIRECTORY, None, 0)  # 跟随 OneDrive 重定向
```

图标别用 `pythonw.exe` 自带的（多半是白图标）——用 Pillow 生成多尺寸 `.ico`：
`img.save(p, format="ICO", sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])`。

**② ⚠️ 校验时的两个假阴性 —— 会让你误判"写失败了"**

| 假阴性 | 真因 | 正确判据 |
|---|---|---|
| `GetIconLocation(0)` / `GetWorkingDirectory(0)` 返回**空串** | 这两个 getter 的 flag 语义与写入端不一致；**值其实已正确写入** | 只信 `GetPath()` / `GetArguments()` 回读 |
| 按 UTF-16LE 搜**完整目标路径**搜不到 | `.lnk` 里目标存于 `LinkTargetIDList`，**逐级分段**（目录名、EXE 名各一段）；`LinkInfo` 里那份完整路径是 **ANSI** 编码 | 完整路径用 `GetPath()` 回读；字节层只查**单个路径段** |

另：`GetPath` / `GetIconLocation` 返回 `(值, 附加信息)`，而 `GetArguments` / `GetWorkingDirectory`
**直接返回字符串**——一律按元组取 `[0]` 会 `IndexError: string index out of range`，写个 `_first()` 兼容。

**③ 最终判据仍是"真启动一次"**：`os.startfile(lnk)` 等同双击 → 查进程（内存大的那个才是干活的）
→ 按 `CommandLine` 过滤关掉，确认无残留。做完把测试进程清干净，别留在用户桌面上。

### 验证三步（缺一步都不算"能双击打开"）

1. `python -m py_compile <gui>.py` —— 语法；
2. `python <gui>.py --selftest` —— 核心链路（拿到 exit 0 + 产出文件）；
3. **真正无控制台启动一次**，用「进程内存 + 日志」确认窗口起来了，再干净关掉
   ——只有这一步验证了"双击"这个动作，前两步验证不了。

---

## 七、CPU 下要报什么指标

- **RTF = 合成耗时 ÷ 音频时长**（<1 比实时快）。这是"这台机器能不能用"的唯一硬指标。
- **首包延迟**（流式才有意义）、**模型加载时间**（常驻进程只付一次）、
  **产能 ≈ 60/RTF 秒音频每分钟**。
- 同时报 **CPU 核数 / torch 线程数**，并注明**无 CUDA**。

实测参照（CosyVoice2-0.5B，i7 级 14 核纯 CPU）：
模型加载 7–8 s（缓存热）／RTF **6.18**／产能 **约 9.7 秒音频/分钟**。

---

## 八、踩坑速查表

| 症状 | 真因 | 解法 |
|---|---|---|
| `from versions: none` | 索引 **403**，不是包不存在 | 换源（阿里云）；先探测再换 |
| `Authentication token does not exist` / 模型仓 403 | 网页/SDK API 需鉴权 | 走 **git clone + LFS batch API**（§三） |
| `git-lfs filter-process: command not found` | 没装 git-lfs | 用 `cat-file` 读指针 + batch API 拉内容 |
| `No module named 'gdown'`（加载模型时） | 深层传递导入，静态分析漏 | 穷举差集补包（§二） |
| `error: invalid command 'bdist_wheel'` | venv 里没 `wheel` | 先 `pip install wheel`，再 `--no-build-isolation` |
| pip 无声退出、`dist-info` 空 | 多 pip 并发 | 先杀残留 python，再动 venv（§四 A） |
| 长任务（删大目录 / pip 解包）被 SIGTERM | **前台静默**被判定挂死，**不是**"删得多" | 后台跑 + 每项 `flush=True` 写进度（§四 B）；实测删 822 MB 仅 1.7 s |
| 双击 `.bat` 后窗口闪一下就没 / 毫无反应 | `pythonw` 下 `sys.stdout is None` → `print` / `logging` 直接炸 | 在任何 import 之前把 stdout/stderr 接到日志文件（§六） |
| `tasklist` 里同一个 GUI 出现**两个**同名进程 | venv 的 `pythonw.exe` 是 stub，会派生真正的 python | **内存大的那个才是干活的**（内存 ≈ 权重体积）；两个都要杀（§六） |
| 用户问「装在哪 / 怎么打开」 | 装完只有代码+权重+venv，没有可双击的入口 | 一律补 `tkinter` 壳 + `START_*.bat`，并写进 README（§六） |
| `New-Object -ComObject WScript.Shell` 被安全策略拦 | PowerShell 禁 COM 实例化 | 改走 **Python + pywin32** 建快捷方式（§六） |
| 校验 .lnk 时图标 / 起始目录**读回空串** | getter 的 flag 语义与写入端不一致（**假阴性**，值其实写进去了） | 只信 `GetPath()` 回读；字节层只查路径段（§六） |
| `TypeError: Invalid file: tensor([...])` | 镜像版本 API 契约不同（传张量 vs 传路径） | **以下游源码为准**，对照仓库自带 `example.py` |
| `numpy.dtype size changed ... binary incompatibility` | numpy 被别的包升到 2.x，C 扩展是 1.x 编的 | 把 numpy 钉回 requirements 指定版本 |
| `import x` 成功但 `x.__file__ is None` | 目录被删剩空壳（命名空间包） | 该包实为**未装**，需重装 |

---

## 九、报告口径

交付时**必须**说明：
1. **能不能跑**（不是"装好了"）；
2. **性能数字**（RTF / 产能）与**硬件约束**（有无 GPU、核数）；
3. **产出物路径**与**真伪核验结论**；
4. **能力边界**——CPU RTF 6.2 意味着「能做 PoC，不能做批量交付」，
   并给出可选路径（云 GPU / 换机器 / 先只保留代码与权重就位）；
5. **未解决项**（如某个可选组件因渠道受限暂缺）与**已用的绕行方式**。

**不要**用"环境不满足"当拒绝执行的理由——先实测，再据实汇报。
