# 交付证据卡 · 结构化缺陷与追溯链判据（v1.12.0）

> 来源：2026-11-13 两条只读考察（见 `docs/benchmark_canvas_gates_20261113.md`）。
> 一句话：**「做完了」和「验得住」是两件事**。产物齐备、时间线拼好、计数报 0 errors，
> 仍可能因为追溯链断开而不可交付。这张卡把「验得住」写成可勾选、可复算的对象。
>
> 与 v1.9.0 的关系：资产台账（`tools/asset_ledger.md`）管「素材有没有身份」，
> 本卡管「结论有没有证据、能不能复算、返工后作没作废」。

---

## 一、什么时候用

**强制**：检查点 B 之后、Phase 4 宣称「已交付」之前；凡是**生成档 / 叙事片 / 短剧档**都要过。
纯文字交付（结构卡、初稿）可省。
**触发重跑**：分镜表、脚本、素材、提示词、时间线、成本台账任一处改动 ⇒ 本卡结论立即作废，重跑后才恢复。

---

## 二、缺陷必须写成对象，不许只报总数

每一条不通过项写成一条 `issue`，七个字段缺一不可：

```json
{
  "code": "SHOT_MEDIA_MISSING",
  "severity": "error",
  "scope": "shot",
  "message": "镜头 s04 尚无可追溯的图片或视频节点。",
  "evidence": { "mediaNodeIds": [], "shotId": "s04" },
  "suggestedAction": "生成或绑定代表性分镜/视频，并保留 shotId 关系。",
  "requiresVisualReview": true
}
```

| 字段 | 要求 |
|---|---|
| `code` | 稳定枚举名，不写自由文本；同一类缺陷跨轮次用同一个 code |
| `severity` | `error`（阻断）／`warning`（可放行但须记录）／`info`（提示） |
| `scope` | `shot`／`media`／`timeline`／`audio`／`copy`／`cost` |
| `message` | 指名道姓到镜号或节点 ID，不写「有些镜头」 |
| `evidence` | **放判据输入**（空数组、实际帧数、命中原文、抽样窗口），让第三方能复算；不放结论 |
| `suggestedAction` | 可执行的下一步，不写「请检查」 |
| `requiresVisualReview` | true ⇒ 必须人眼复核并由人在回执里签字；机器不得代为 PASS |

**三条硬规矩**

1. 禁止只报「发现 66 条问题」——**必须逐条给 code / 语境 / 判定 / 来源**。
2. `evidence` 里照录原文或原始数值；复算不出结论的报告不算报告。
3. `requiresVisualReview: true` 的条目未签字 ⇒ 本卡不得标 PASS。

---

## 三、severity 分级：追溯链断裂一律 error

| 缺陷类型 | 级别 | 说明 |
|---|---|---|
| 镜头无媒体绑定（`mediaNodeIds` 为空） | **error** | 逐镜验收与取证链断开 |
| 提示词过期（`fresh → stale` 未重算） | **error** | 旧提示词对应的产物，不能代表新脚本 |
| 孤儿素材（既未声明候选、又未绑定镜头／时间线） | **error** | 黑户素材点名处置：入账绑定或标废弃原因 |
| 成片节点无可用输出文件／URL | **error** | 「剪辑完成」不等于「可导出」 |
| 待人工复核未清 | **error** | 不得当 PASS 放行 |
| 缺陷报告输入指纹与当前项目不符 | **error** | 结论已过期，须重跑 |
| 音轨未登记 `a_` ID、混音后未逐镜核声画起点 | **error** | 音轨错位但「听起来对」，只靠听查不出 |
| 非对外文案的技术注释命中词表 | warning | 记录即可，不阻断 |
| 候选素材未标 `candidate` | warning | 提醒声明身份，不是产物缺陷 |

> **0 errors ≠ 可交付**：只要上表任一 error 存在，即便其余计数全绿、生成任务全部成功，
> 也不得进入 Phase 4。实证参照：某商业画布项目 52 件媒体、86 秒时间线、13 段 clip 齐备，
> 却因 13 镜全无绑定、成片无输出而停在终交付段，平台仍报 `errors: 0`。

---

## 四、三向绑定与关系证据

| 关系 | 必须有 | 证据字段写法 |
|---|---|---|
| 镜头 → 媒体 | `shotId.mediaNodeIds[]` | 列出每个媒体节点 ID |
| 媒体 → 镜头／时间线 | `media.shotIds[]` / `media.timelineNodeIds[]` | 两侧都要写，**单向关系不算绑定** |
| 时间线片段 → 源节点 | `clip.sourceNodeId` ＋ `clip.shotId` | 关系项附 `evidence`，注明「这条关系从哪个字段推出」 |

```json
{
  "type": "timeline-source",
  "sourceId": "tl_ep01",
  "targetId": "v_s04",
  "clipId": "clip_04",
  "evidence": "clipTimelineData.clips[].sourceNodeId"
}
```

**命名不算绑定**：节点名或文件名里带 `s04`、`EP01_s04` 只是文字，
`shotIds` 为空就仍是孤儿。绑定必须落在结构字段上——与本包「指纹以 md5 为准、轮次名不作指纹」同源。

**资产三态**：`candidate`（候选，允许未绑定但须声明）／`approved`（已过目）／`bound`（已进镜头或时间线）。
样片、备用首帧、链路验证片属于 `candidate`，不按缺陷处理。

---

## 五、报告指纹与结论过期

每次跑完本卡，报告头部必须带：

| 字段 | 含义 |
|---|---|
| `rulesVersion` | 判据版本，**冻结后不得临时放宽** |
| `dictVersion` | 词表／判据字典版本（与共享扫描器同源） |
| `inputHash` ＋ `inputBytes` | 本次输入快照的内容指纹与字节数 |
| `scannedAt` | 扫描时间 |
| `issues[]` | 按第二节 schema 逐条列出 |
| `summary` | pass / fail / total / passAll |

**过期判据**：当前项目内容指纹 ≠ 报告 `inputHash` ⇒ 报告自动标「**结论过期（待重跑）**」，
汇总数字从时间线／交付说明撤下，**重跑才恢复**。旧报告留档不删，但不得当作有效结论引用。

**人工不可覆盖**：主理人、成员、客户都不能把 FAIL 改成 PASS；
要改只能改输入（补绑定、重算提示词、补产物），再重跑。
这条与「主理人自己不能当裁判 ⇒ 强制独立盲评」互为双保险。

---

## 六、读取纪律：revision 钉版

多次／分页读取同一项目的 manifest、分镜、缺陷、时间线时，
**必须复用同一个 `expectedRevision`（或等价的内容指纹）**；
任一次返回的 revision 与基准不一致 ⇒ 停止拼接、重新取全量快照。

> 理由：把两个版本的分页结果拼成一份报告，会得出「看起来自洽、其实不存在」的结论。

---

## 七、投影 ≠ 持久化；字段 ≠ 有内容

- **有可打开的 URL 不等于文件已保存**。记录里 `bindingStatus: present` 仍可能
  `persistedResourceIdCount: 0`。交付件一律绑**内容 md5＋字节数**，并检查文件确实存在。
- **结构化字段不等于字段有值**。分镜表里预留了 `cinematics`（机位／运镜／焦段）却全为空对象，
  不能据此宣称「有镜头语言」。空字段要显式登记为「未填」，不能留白当作已填。
  能力边界见 `KNOWN_LIMITS.md` 第 4、9 条。

---

## 八、音频 evidence 契约

音频验收输出以下结构化指标（逐窗／逐镜），不只写「听起来对」：

`rmsDbfs`、`peakDbfs`、`clippedSampleRatio`、`silenceRanges`、`waveform`

- 环境声底「听得见」判据沿用既有 RMS ≥ −50 dBFS，并报静音占比；
- 「该静音」的窗口必须在 `silenceRanges` 里能被指出来；
- 混音后逐镜核声画起点（off-by-one 时音轨整体错位但每处都有声音）。

---

## 九、可勾选清单

- [ ] 每条缺陷都是七字段 `issue` 对象，`evidence` 放判据输入，可第三方复算
- [ ] 未出现「只报总数」；逐条给 code／语境／判定／来源
- [ ] `requiresVisualReview: true` 的条目已由人眼复核并签字（机器未代判）
- [ ] 追溯链类缺陷全部判 `error` 且已清零；**0 errors 但仍有孤儿／stale 时不得 PASS**
- [ ] 镜头 → 媒体、媒体 → 镜头／时间线、时间线 → 源节点三向绑定齐备，关系带 `evidence`
- [ ] **命名带镜号不算绑定**；`shotIds`／`mediaNodeIds` 结构字段已实际写入
- [ ] 资产已标 `candidate / approved / bound`；样片与备用片按候选声明
- [ ] 报告带 `rulesVersion`／`dictVersion`／`inputHash`／`inputBytes`／`scannedAt`
- [ ] 当前项目指纹 == 报告 `inputHash`；否则已标过期并重跑
- [ ] 多次读取复用同一 revision；不一致已重取全量
- [ ] 交付件绑内容 md5 ＋ 字节数，文件实际存在；未把可打开 URL 当作已保存
- [ ] 结构化字段的空值已显式登记，未把空字段当作已填
- [ ] 音频五项 metrics 已出，静音窗可指认，混音后逐镜核过声画起点
- [ ] 结论未被人工覆盖；要改只改输入再重跑

> **不打勾的后果**：不允许宣称「已交付」。
> 一句话：**这套流程的价值不在「一次做对」，而在「能自己发现没做对，并且发现之后旧结论会自动作废」。**

---

## 十、与既有机制的关系

| 既有 | 本卡补的那一层 |
|---|---|
| `tools/asset_ledger.md` 四类 ID 台账 | 台账管身份；本卡管**关系双向**、命名不算绑定、候选三态 |
| `tools/budget_ledger.md` 一镜一行成本 | 本卡补「失败任务不虚报成本」「结论绑指纹」 |
| `tools/video_selfcheck.py` 帧数／时长／AI 标识／逐窗 RMS | 本卡补音频 evidence 的**结构化输出契约**与缺陷对象化 |
| 检查点 B「无 stale / 无孤儿媒体」 | 本卡把它从人工检查项升级为**带 evidence 的阻断级 error** |
| 独立盲评（Phase 3.5） | 本卡不替代盲评；盲评判作品层，本卡判可追溯性 |

---

*Copyright 2026 董植深 (Jason Dong) · [PolyForm Noncommercial 1.0.0](../LICENSE)*
