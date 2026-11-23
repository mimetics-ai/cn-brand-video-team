# 生成式模型选型矩阵（v1.15.0 · AgentEarth 实测）

> 数据来源：AgentEarth MCP `ListTools` 实测返回（total=2467 工具），2026-11-23。
> 用途：Phase 1.5a 模型选型横评闸的**生成档决策表**——按镜头需求选模型，花积分前报预计总额。
> 纪律：定价会变，用前以平台当日读数为准；本表给的是量级，用于估算和比选，不作报价承诺。

---

## 一、视频生成

| 工具名 | 输入 | 关键能力 | 定价（credits） |
|---|---|---|---|
| `ae_kling_video_o3_pro_reference_to_video` | 文字/多镜头提示词＋可选首尾帧＋参考图＋具名角色/物件 | **多镜头一致性**、首尾帧、参考元素、可选原生音频 | 135/秒（无音频）· 168/秒（有音频） |
| `ae_kling_video_o3_pro_image_to_video` | 首帧图＋可选尾帧＋提示词 | 3–15s，多镜头，原生音频 | 135/秒 · 168/秒（音频） |
| `ae_kuaishou_kling_4_0_video_generate` | 文字 | Kling 4.0 文生视频 | 720p 188.4/秒 · 1080p 282/秒 |
| `ae_alibaba_wan_3_0_prime_video_generate` | 文字 | Wan 3.0 Prime 文生视频 | 480p 81.6/秒 · 720p 168/秒 · 1080p 336/秒 |
| `ae_alibaba_wan_3_0_video_generate` | 文字 | Wan 3.0 文生视频 | 480p 60/秒 · 720p 120/秒 · 1080p 240/秒 |
| `ae_vidu_q3_text_to_video` | 文字 | Vidu Q3，1–16s，可选音频/分辨率/seed | 360/540p 84/秒 · 720/1080p 185/秒 |
| `ae_minimax_h3_video_generate` | 文字 或 首帧图(＋可选尾帧) | **音画同生成**、5–15s、**21:9/16:9/9:16 等六画幅**、seed | 480p 8.41/秒起 · 1080p/2K 18.47/秒 · 4K 92.31/秒 |
| `ae_pixverse_v6_extend` | 已有视频 URL＋提示词 | 视频续写/延长，可选音频 | 360p 30/秒 · 720p 54/秒 · 1080p 108/秒 |
| `ae_davinci_magihuman` | 参考图(必填)＋音频(可选) | 参考图驱动的说话人/口型视频 | 256p 24/秒 · 720p 48/秒 · 1080p 72/秒 |

**省略时长默认按 5 秒计费**——估算时不要用"我大概用 3 秒"，按 5 秒起算。

## 二、图像生成与参考锚定

| 工具名 | 输入 | 关键能力 | 定价（credits/张） |
|---|---|---|---|
| `ae_nano_banana_2_1` | 提示词＋最多 **14 张参考图** | 多参考角色锚定，1K/2K/4K，aspectRatio 控制 | 16.81（含参考图，不分分辨率） |
| `ae_minimax_h3_image_edit` | 提示词＋最多 **16 张参考图**（`<Picture N>` 按序引用） | 多参考合成，1K/2K/4K | 10.8(1K/2K 底)＋3×参考图数；4K 底 33 |
| `ae_pulid` / `ae_ip_adapter_face_id` | 提示词＋1 张人脸参考 | FLUX-PuLID 人脸相似度引导（精确一致不作承诺） | 24 |
| `ae_alibaba_qwen_image_3_0_pro_generate` | 提示词 | Qwen Image 3.0 Pro | 1K 48 · 2K 90 |
| `ae_openai_gpt_image_2_6_sunburst` | 提示词＋可选参考图 | GPT Image 2.6，精细构图/编辑 | 13.92（固定，不随张数/参考图） |
| `ae_bytedance_seedream_5_0_pro_image_generate` | 提示词 | Seedream 5.0 Pro | 1K/1.5K 54 · 2K 108 |
| `ae_blackforestlabs_flux_3_image_generate` | 提示词 | FLUX 3 Klein Distilled | 1K 12 · 1.5K 24 · 2K 48 |
| `ae_ideogramai_post_generate_image_v_3_transparent` | 提示词 | **透明背景图**（logo/图标/字卡素材） | 48–312（按渲染模式/放大） |

## 三、音频与音乐

| 工具名 | 输入 | 关键能力 | 定价（credits） |
|---|---|---|---|
| `ae_elevenlabs_music` | 提示词／结构化 composition plan（段落＋时长＋歌词） | 分段结构音乐，无版权 | 指定时长 720/分钟起；自动时长 3600/次 |
| `ae_lyria3` | 提示词＋可选引导图 | 30s 原创音乐，图片引导情绪 | 48/次 |
| `ae_ace_step` | 提示词＋genre tags | 文本生成音频，seed 可复现 | 0.24/秒 |
| `ae_mmaudio_v2` | 视频＋提示词 | **视频→同步音效/环境声**（音画同步） | 1.2/秒 |
| `ae_deepgram_post_speak_generate` | 文本 | 多声线 TTS，speed 0.7–1.5 | Aura-1 0.018/字 · Aura-2 0.036/字 |

---

## 四、按镜头需求选型的决策树

```
要生成的这一镜，需要什么？
├─ 要跨镜同一人物 / 首尾帧 / 参考元素 → Kling O3 Pro reference_to_video
├─ 只有一张首帧图，要驱动它动 → Kling O3 Pro image_to_video（要尾帧也用它）
├─ 无参考图，纯文字描述 → Kling4 / Wan3 Prime（要便宜用 Wan3 480p）
├─ 要"音画一体"/21:9 宽幅 → MiniMax H3（本包的 21:9 交付靠它）
├─ 已有视频要延长 → PixVerse V6 extend
├─ 要参考图把人物锁住（生图阶段）→ Nano Banana 2.1（≤14 张）/ PuLID（人脸）
├─ 要透明 logo/字卡素材 → Ideogram transparent
└─ 要配乐/音效 → ElevenLabs Music（分段）/ Lyria3（图片引导）/ MMAudio（视频配音效）
```

## 五、成本预估模板（Phase 1.5a 输出）

```
镜头 01  6s  Kling O3 Pro(无音频)   6×135 = 810 credits
镜头 02  6s  Kling O3 Pro(无音频)   6×135 = 810 credits
...
配乐    30s Lyria3               48 credits
音效    45s MMAudio              54 credits
────────────────────────────────────────
预计合计：____ credits   （余额：____，是否确认？）
```

**花积分前的硬闸**：报出预计总额＋当前余额，等用户确认。余额以平台当日读数为准（曾出现"148 credits 耗尽"误报，实为 30663——读数须走账户总览端点，不采信单方桥接自报，见证据卡 9.3）。

---

*Copyright 2026 董植深 (Jason Dong) · [PolyForm Noncommercial 1.0.0](../LICENSE)*
