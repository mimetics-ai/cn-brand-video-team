# 对标考察：LibTV「电影制作」工作流（2026-11-09）

> 考察对象：LibTV 画布项目「最后一个笑点 · 竖屏短剧」（32 节点 / 1 份 script-v2 分镜表 / 13 镜 / 86 秒 / 9:16）。
> 性质：**只学流程，不抄内容**——本项目不含生成能力，吸收的仅是对方的**工程化制片 schema**。
> 结论：吸收 6 条机制，落为本包 v1.9.0（见文末「落地清单」）。

## 一、对方做了什么（实测快照）

| 层 | 事实 | 证据（snapshot section） |
|---|---|---|
| 资产体系 | 19 个资产 ID：角色 5（`c_zhou`/`c_ma`/`c_ai`/`c_shen`/`c_xiaoman`）、场景 9（`s_city`/`s_rooftop`/…）、道具 5（`p_duck`/`p_chair`/…） | scripts.assets |
| 分镜表 | 13 镜逐镜结构化：`shotId`(ep01_s01)/`durationSeconds`/`shotSize`(景别)/`emotion`/`lightingAndAtmosphere`/`audioEffects`/`characters[]`/`sceneAssetIds`/`propAssetIds` | shots |
| 视觉锁 | 角色外观完整描述**直接写进镜头剧情文本**（"42 岁东亚男性，深藏青三件套，圆框眼镜，橡皮鸭徽章"）＋另有独立定妆图节点 | shots.plotDescription |
| 媒体流水线 | 2 张定妆图 → 13 张首帧图（每镜 1 张）→ 13 段图生视频（5–8s，1080P） | media 节点命名 EP01_sNN |
| 模型横评 | 正式生成前 3 个模型各出 8s 样片（样片A H3-Highspeed / 样片B HH1.0 / 样片C HH1.1） | media |
| 验证镜 | 双人同框镜头显式标「双人同框验证①②」单列先行 | media 命名 |
| 状态机 | `scriptVersion=2`；每镜 `imagePromptState`/`videoPromptState`（fresh/stale） | shots |
| 自动质检 | 57 条 issues：`STALE_SHOT_PROMPT`×13（提示词过期→"重算后再生成"）、`SHOT_MEDIA_MISSING`×13（镜头无媒体）、`ORPHAN_MEDIA`（媒体未绑镜头/时间线，逐节点点名） | issues |

## 二、六条可吸收机制（含与本包现有规矩的映射）

| # | 机制 | 对方做法 | 本包现状 | 吸收方式 |
|---|---|---|---|---|
| 1 | 资产 ID 台账 | 角色/场景/道具全部 ID 化，分镜逐镜引用 | 定妆图有规范（check_character_sheet.py）但无 ID 引用体系 | 新增 `tools/asset_ledger.md`：立项建 `c_/s_/p_` 台账，分镜逐镜引用 |
| 2 | 分镜八要素 | 景别/情绪/光感是独立结构化字段 | 五要素（时间/画面/旁白/字幕/音效），景别情绪混在画面描述里 | script-writer 分镜表升级：叙事/短剧档加 3 列 |
| 3 | prompt 漂移状态机 | scriptVersion + 逐镜 promptState，脚本一改全镜 stale，平台拦"重算后再生成" | 口头闸「脚本未定稿不得进 Phase 2」，改脚本后靠人记重算 | 状态位落进分镜表；检查点 B 新增"无 stale"项 |
| 4 | 镜头-媒体追溯 | 每镜 mediaNodeIds；孤儿媒体点名（生成未挂镜头=黑户） | 台账记逐镜积分但不追"媒体↔镜头"归属 | 检查点 B 新增"无孤儿媒体"项 |
| 5 | 模型选型横评 | 3 候选模型 × 同一 8s 样片，横评后定主力 | 有 model_selection.md 但无"样片横评闸" | Phase 1.5 预览闸升级：正式批量前先横评 |
| 6 | 双人同框验证镜 | 最易翻车的双人交互显式标"验证"单列先行 | 红线 2 知道硬伤，但没有"验证镜"动作 | 分镜含双人同框 ⇒ 标「验证镜」并前置 |

## 三、对方没有、我们有的（不自卑清单）

- **合规层对方为零**：无广告法扫描、无 AI 标识双取证、无面孔筛查——我们的 Phase 3/3.5 整层是对方没有的。
- **交付可追溯**：对方有 shot↔media 追溯，但无署名头/外部锚/content_at_render-frozen 成对登记。
- **成本纪律**：对方 issues 里无成本维度；我们一镜一行积分＋重试。
- **预期管理**：对方直接接 60 集×90 秒短剧（跨集同脸死结只字未提）；我们的三红线＋三条绕法仍是差异化护城河。

## 四、v1.9.0 落地清单

| # | 落点 | 改动 |
|---|---|---|
| 1 | `tools/asset_ledger.md`（新增） | c_/s_/p_ 资产台账规范＋视觉锁文字块模板 |
| 2 | `agents/script-writer.md` | 叙事/短剧档分镜表加「景别/情绪/光感」3 列＋资产 ID 列＋prompt 状态位；双人同框标「验证镜」 |
| 3 | `agents/brand-video-team-lead.md` | Phase 1.5 加模型横评闸；检查点 B 加「无 stale」「无孤儿媒体」两项 |
| 4 | `plugin.json` | version → 1.9.0 |

> 考察方法自证：本文全部数字来自 `get_project_snapshot` 各 section 的 API 实读（2026-11-09 08:39–08:41），
> 非记忆或推测；项目 revision `6f70595e…`。
