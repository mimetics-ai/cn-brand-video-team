# AI 短视频制片团队 · ShotCrew

[![GitHub stars](https://img.shields.io/github/stars/mimetics-ai/cn-brand-video-team?style=social&label=Star)](https://github.com/mimetics-ai/cn-brand-video-team/stargazers)
[![License: PolyForm Noncommercial 1.0](https://img.shields.io/badge/License-PolyForm_NC_1.0-blue)](LICENSE)
[![平台](https://img.shields.io/badge/WorkBuddy-专家包-orange)](#安装)

> 把手上现成的素材（实拍视频 / 产品原图 / 界面截图），做成**能过审**的中文品牌短视频，横竖双画幅一次交付。
> 核心不是"生成得多像"，而是**流程管得住**：每个结论都有判据，每轮返工都留痕。

一个**外行**（市场营销出身，不是程序员也不是导演）用 3 个月攒出来的五人制片团队，跑过真实客户交付。
现在开源，是想让更多人少踩我们踩过的坑 —— 顺便检验这套方法在别人手里到底成不成立。

---

## 它到底是什么

不是一键生成器，是一支**有分工、有验收、有签字**的虚拟剧组：

| 角色 | 干什么 | 凭什么可信 |
|---|---|---|
| **制片厂长**（主理人） | 立项、派活、验收、汇编，对"能不能对外发"签字 | 自己不能当裁判 → 强制另起独立盲评 |
| **编剧** | 五要素分镜、时长与语速断言、广告法前置 | 断言是数字，不是"感觉差不多" |
| **剪辑** | 素材路线判定、逐帧标定、双画幅分别重构图 | 帧数是实测的，不信容器时长 |
| **音频** | TTS 三通道、无版权配乐、增益分级与侧链闪避 | 逐窗 RMS 对位，气口必须真静音 |
| **合规审查** | 逐帧面孔筛查、字幕错字像素级修补、AI 标识自检 | 三态结论（PASS/FAIL/待人工），每项带帧号 |

**六条开工前就会被拦下的坑**（都是真踩过的，不是说明书上的注意事项）：

1. **素材里有真实文字 → 禁用生成式视频**。品牌名、型号、净重被 AI 一改就糊，对外说"正品"时假字是硬伤。
2. **静态姿态位图做不出真实操作动作**。用吉祥物演示"施工"只能停在纸片人层面。
3. **改文案不等于压时长**。TTS 时长≈完全反比于语速，精简文案完全无效，想缩短只能提语速。
4. **绝不能信用户给的时间点与文字**。一律自己抽帧认定——实测中用户说的"印度洋"原片其实是"印隔洋"。
5. **配乐按峰值配平会让人声消失**。配乐波峰因数 ≈28 dB、旁白 ≈14 dB，按峰值配平音乐低人声 30 dB。
6. **能不能抠图要先判断**。背景有纹理、有手入镜、产品与背景同色系——命中 1~2 项就不该抠（必脏边）。

---

## 三分钟上手

```bash
git clone https://github.com/mimetics-ai/cn-brand-video-team.git && cd cn-brand-video-team
python tools/env_probe.py                      # ① 探测依赖（缺什么一条命令补）
python tools/structure_card.py analyze --text samples/demo_script.txt --out card.json --name "示例30s"   # ② 拆结构卡
python tools/banword_scan_local.py samples/demo_script.txt                                              # ③ 扫违禁词
python tools/ledger.py init --project my_proj --name "我的第一条片"                                      # ④ 开台账
```

完整 10 分钟流程（含预期输出、故障排查表）见 **[`QUICKSTART.md`](QUICKSTART.md)**。

> 命令行只用到 `tools/` 里的**校验类**工具。真正会"拍片"的是那五个角色，
> 需要在 WorkBuddy 专家运行时里被调度——安装方法见 QUICKSTART 第 5 节。

---

## 目录结构

```
agents/          五个角色的完整定义（提示词＋判据＋红线），这是本包的核心
skills/          7 个可复用技能（分镜 / 实拍 / IP 动画 / 截图讲解 / 面孔筛查 / 字幕修补 / TTS）
tools/           纯 Python 校验工具，可脱离平台单独用
  env_probe.py           依赖探测（跨平台，找 python/ffmpeg，缺什么提示什么）
  structure_card.py      七层结构卡拆解（有参考片就先拆卡再写稿）
  banword_scan_local.py  广告法违禁词本地扫描（先判，再看语境）
  ledger.py              制片账本（成本/许可/宣称/资产四账，哈希链防篡改）
  video_selfcheck.py     成片自检（帧数/时长/AI 标识/逐窗音量）
  task_queue.py          长任务断点续跑
  stock_footage.py       零素材时的参考构图包（强制水印，不得入片）
_assets/         违禁词表、角色定妆图模板
samples/         可直接跑的示例文案（不含任何客户素材）
```

---

## 实测数据（一条 30 秒双画幅品牌片的全流程）

| 指标 | 数字 |
|---|---|
| 分镜 | 13 镜，Σ = 720 帧 / 30.00 s / 24 fps |
| 独立盲评 | **5 轮**（2 次 FAIL → 3 次 PASS），终验 35/40、硬性 9 项全过 |
| 返工轮次 | **25 轮**（含 3 次作废重渲、2 次合规复核） |
| 生成式积分消耗 | **0** |
| 交付件 | 16:9 与 9:16 各自 720 帧，压缩件 38–41 MB |

盲评具体拦下过什么：锚链对不上、成本台账缺失、字幕越界把"扛"裁成"打"、半透明底衬在亮背景上对比度漂移。
**这套流程的价值不在"一次做对"，而在"能自己发现没做对"。**

---

## 许可与商用

本仓库采用 **[PolyForm Noncommercial 1.0.0](LICENSE)**：

- ✅ 个人学习、研究、教学、公益、给自己家产品拍片 → **免费，随便用**
- 💰 **拿它接单赚钱 → 需要商用授权**，见 **[`COMMERCIAL.md`](COMMERCIAL.md)**
- 拿了钱就算商用，不分单子大小（699 元的单也一样）

### 公开版 vs 专家中心版（v1.8.1）

同一套方法论、同一套流程、同一支团队，公开版在上架版基础上做了三类改动：

| 类别 | 数量 | 说明 |
|---|---|---|
| **逐字节相同** | 19 个文件 | 核心提示词与判据未动 |
| **经改写** | 26 个文件 | ①客户信息脱敏（客户名→代号）②依赖路径可移植化 ③中文 Windows 控制台兼容修复 |
| **公开版新增** | 9 个文件 | LICENSE、COMMERCIAL.md、QUICKSTART.md、KNOWN_LIMITS.md、示例素材、`env_probe.py`、2 个 Issue 模板、.gitignore |

清单字段差异仅两处：**英文名（ShotCrew）**与**联系方式（不公开邮箱，一律走 Issue）**。
功能、流程、验收判据与专家中心版一致；需要平台适配的完整包请走 WorkBuddy 专家中心获取。

---

## 先把丑话说在前面

**[`KNOWN_LIMITS.md`](KNOWN_LIMITS.md)** 列了 7 条做不到的事，包括：
不含任何生成式画面能力、AI 真人的手指与跨集同脸是硬伤、不承诺院线质感与爆款流量、
中文字体只许 OFL 授权。**建议先看这一页再看代码。**

> 口径说明：本包 `plugin.json` 的市场描述文案里写的"117 个极限词"是 v1.6.x 期口径，
> 词表后来扩过；**以 `_assets/ad_law_banwords.json` 的实际内容为准**
> （当前硬性违禁 133 个词形 + 待复核 35 个词形）。

---

## 内置技能（7 个，随包携带）

| 技能 | 用途 |
|---|---|
| brand-video-script-cn | 中文品牌短片分镜脚本 |
| real-footage-product-video | 实拍素材 → 产品视频（双画幅） |
| ip-animation-video | IP 形象程序化动画短片 |
| screenshot-explainer-video | 截图讲解 / 使用说明视频 |
| ai-video-face-screening | 视频「无面孔」双判据筛查（含 `scripts/frames_facecheck.py`） |
| video-burned-subtitle-patch | 烧录字幕像素级修补 |
| tts-model-offline-setup | 受限环境装配开源 TTS / 声音复刻 |

---

## 联系

- 问题 / bug / 想加功能：开 Issue，**把 `python tools/env_probe.py --json` 的输出贴进来**
- 商用授权：开 Issue，标题写 `商用授权`
- 作者：董植深（Jason Dong）· 市场营销出身，非科班，做这个是因为自己被 AI 剪片坑过太多次

---

## 免责声明

> 本团队提供爆款结构拆解与成片辅助流程，**不承诺任何视频必定过审、成为爆款或带来具体流量**。
> 你用它产出的内容，合规责任在发布方（广告法、AI 生成内容标识、素材版权、肖像权）。

> This project provides production workflow and tooling. We do not guarantee that any video will pass
> review, become a hit, or generate traffic. Compliance responsibility for published content rests with the publisher.
