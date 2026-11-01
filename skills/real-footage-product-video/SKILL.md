---
name: real-footage-product-video
description: 用**已有实拍素材**（手机/相机拍的视频 + 产品原图）剪出一支可上平台的产品/开箱/演示视频，双画幅（横屏 16:9 + 竖屏 9:16），画质与文案都可核验。核心是五件事：① **先判定该不该用生成式视频**——只要包装/吊牌/屏幕上有真实文字（品牌名、型号、净重、编号、批次），生成式必然把字改糊，而这类物料对外宣称"正品"时假字是硬伤，正解是**真实素材剪辑 + 生成式只补音频（BGM/配音）**，且开工前先数素材够不够剪（几十秒实拍 + 十几张原图通常就够 90 秒片）；② **逐帧标定分镜点位**——字幕文案绝不能凭设想写，必须回原片读标签确认"这一秒画面里到底是哪个件"，本项目一次目检就抓到 3 处"字幕说的件和画面里的件不是一个东西"（把面漆白桶误标成 A 组分），那是靠逐帧放大读桶面标签才纠回来的；③ **ffmpeg filter_complex 分段合成 + concat 拼接**——每段单独编码成同参数中间片再 concat，字幕/水印/页眉分别预先渲染成"整帧 RGBA 叠加层 PNG"在段内 overlay（字幕天然跨整段，省掉几十条 enable 链），各段音频同步带入、无原声段用 anullsrc 补静音，concat 时视频音频自动对齐；④ **画面层一律 Pillow、但必须分层合成**——在 RGB 画布上画半透明色**不会混合**（水印会变成不透明白字压死正文），要全部画在独立 RGBA 图层再 alpha_composite；⑤ **离线可复现的验证链**——抽帧目检联络表、逐段测音量、按窗口测"BGM 是否全程可闻 / 原声是否静音"、断言总帧数 == Σ(段秒数×fps) == 输出时长；⑥ **字幕里凡出现数字/单位/型号/特性词，必须回原始高清素材放大到能逐字辨认再落笔**——本技能两次踩坑：把面漆桶标成 A 组分、把桶面「推荐用量 5~8 平方米」读成「可用 5~8 年」（后者是虚假宣传风险）；仅"抽帧目检成片"远远不够，成片里的小字根本读不清，必须裁原图放大。也覆盖 AgentEarth 生成免版税 BGM 的取用与下载（`ExecuteTool` 必须传 `tool_url` 而非 `tool_name`；代理可能已失效要直连；远端可能分块传输无 Content-Length，须以接口报的 file_size 做最终断言）。适用于：产品开箱视频、实物开箱、正品验证视频、电商主图视频、多平台投放的双画幅版本（抖音/视频号竖屏 + 官网/展会横屏）、给一批实拍素材做剪辑方案、用手上现有素材出一支宣传短片、给静音素材配乐并烧中文字幕。触发词：开箱视频、产品开箱、拆箱视频、unboxing、实物视频、把素材剪成视频、依据视频和图片做视频、横屏版和竖屏版都要、正品视频、主图视频、烧字幕、加字幕、配 BGM、AgentEarth 生成音乐、**多个视频按步骤整理成一个案例视频、每步取几秒拼接、步骤片、施工/工艺案例片、旁白配音 + 背景音乐、TTS 旁白驱动剪辑、drawtext 烧中文文字层（片头标题/步骤角标/片尾品牌条）**。
agent_created: true
---

# 实拍素材 → 产品视频（双画幅，可核验）

## 〇、先做这三件判断，再动手

1. **要不要用生成式视频？**
   只要画面里出现**真实文字**（品牌名、型号、净重、批号、吊牌、屏幕）——**不要**。生成式会把字改糊，
   而"正品/官方"类物料出现假字是硬伤。正解：**真实素材剪辑，生成式只补音频**。
2. **素材够不够剪？**
   经验值：**~70 秒实拍 + 10 余张高清原图 ≈ 90 秒成片**（实拍占 6 成、照片占 3 成、片头片尾卡占 1 成）。
   实拍负责"过程"（拆封/取出/操作），照片负责"细节与规格"（标签特写、全景陈列），卡负责首尾。
3. **成片时长定多少？**
   按 **段秒数 ×30fps 累加**，先把"总帧数"定死，再反推 BGM 时长与淡出点；不要先定音乐再凑画面。

## 一、素材侦察（不可跳过）

```bash
FF="<imageio_ffmpeg 自带二进制路径>"
for f in *.mp4; do "$FF" -i "$f" 2>&1 | grep -E "Duration|Stream|Side data|displaymatrix"; done   # 无 ffprobe 时靠 -i 的 stderr
```
- 记下每段的分辨率/fps/时长，以及**是否有音轨**（决定后面要不要补 anullsrc）。
- 抽帧看内容：按时点抽 `-ss T -i src -frames:v 1 -vf scale=W:H`，拼联络表目检。
- **照片全部编号 + 内容映射**（哪张是正面标签、哪张是辅件、哪张是全家福）。

### ⚠️⚠️ 头号排查项：手机竖拍视频的 `displaymatrix` 旋转

**`grep Stream` 只看到 1280x720 是不够的 —— 必须同时看 `Side data`：**

```
Stream #0:1: Video: h264 ..., 1280x720, 1600 kb/s, 30.01 fps     <-- 这是"侧躺"的存储尺寸
    Side data:
      displaymatrix: rotation of -90.00 degrees                  <-- 真实显示方向是 720x1280 竖！
```

- 手机竖拍会写一条旋转矩阵，**存储尺寸是横的、显示方向是竖的**。
  `ffmpeg -ss 5 -i src.mp4 -frames:v 1 f.png` 抽出来的 PNG 是 **720x1280**（ffmpeg 已自动应用旋转），
  与 `ffmpeg -i` 报的 `1280x720` **不一致** —— 这就是"元数据在骗你"的信号。
- **判据**：抽帧尺寸 ≠ `-i` 报的尺寸 ⇒ 有旋转矩阵 ⇒ 后面对解码帧做任何 `scale=W:H` 都建立在错误方向假设上。
- 想知道"到底哪个方向才对"，就看抽帧图里**文字是否可正读**（桶面/标签上的字正向即可读）。

**灾难写法（本项目实际翻车点，用户连投诉两次"变形"）：**
```bash
# ✗ 误以为源是 1280x720 横的，于是让它"铺满" 1920x1080 —— 但它其实是 720x1280 竖的！
#   结果：横向拉伸 2.67 倍、纵向压缩 0.84 倍
"[0:v]scale=1920:1080:flags=lanczos,setsar=1,fps=30[bg]"
```
- `SAR` 依然是 `1:1`、时长帧数全对、`ffmpeg -i` 一切正常 —— **这条路径上的所有常规自检都查不出问题**。
- 只有把**源抽帧**和**成片同帧**做像素比对才会暴露：实测 `central MAD = 83.48`、`P99 = 233`、
  边缘质心横移 `dx = 306 px` —— 这是几何变换级差异，不是重采样误差。

**正解**：先显式统一方向，再按统一后的真实宽高比设计画幅。
```bash
# 二选一，但必须显式做，不能"默默地让它自动转"
-noautorotate -i src.mp4 -vf "transpose=2" ...        # (a) 关掉自动旋转 + 自己转
"$FF" -ss 5 -i src.mp4 -frames:v 1 probe.png          # (b) 先抽帧量出真实尺寸，再按它算 filter
```
> 教训：**"素材侦察"这一步的完成判据不是"我知道分辨率了"，而是"我验证过元数据与抽帧一致"。**

## 二、逐帧标定分镜点位（本技能最值钱的一步）

**纪律：字幕文案不得凭分镜设想书写，必须回原片逐帧读标签。**

做法：对每个"物件登场"的时间窗，以 1 秒为步长抽帧拼表；对关键帧再**放大裁切读标签文字**。

> 实测教训：一次分镜把 42–45s 标成「A 组分」，放大读桶面发现写的是
> 「水性丙烯酸 防水涂料 **面漆**」——是面漆白桶，不是 A 组分蓝桶。若不复核，成片字幕会张冠李戴。
> 同轮还抓到 2 处同类错位。**字幕错位的代价远高于多抽 20 帧的成本。**

### ⚠️⚠️ 二次教训：「抽帧目检」不等于「读标签」

第二轮成片后**客户仍然抓出 2 处标签读错**，其中一处性质严重：
把桶面的「推荐用量　一套本产品可使用 **5~8 平方米**」写成了「耐久 · 可用 **5~8 年**」；
另一处把「**强效**防水」写成「强黏防水」。

根因：我确实做了"逐段抽帧目检"，但目检的是**成片里的图**——已经缩到 ~640px、
再叠上字幕条与压暗层，桶面的小字根本读不清，于是**凭上一轮的印象**填了文案。

**正确判据（升级版）：**
> 凡字幕里出现 **具体数字 / 单位 / 型号 / 特性词**，
> 必须**回原始高清素材（3000px 级）裁切放大到能逐字辨认**再落笔。
> **不得只看成片抽帧，不得沿用旧稿印象。**

高危字对（错一个性质就变）：

| 类别 | 易错例 | 后果 |
|---|---|---|
| **单位** | 年 ↔ 平方米、kg ↔ g、毫米 ↔ 厘米 | 把"用量"读成"耐久年限" = **虚假宣传风险** |
| **修饰字** | 强效 ↔ 强黏、耐候 ↔ 耐磨、高弹 ↔ 高强 | 特性描述失实 |
| **型号** | ZK-720 ↔ ZC-720 | 指向错误产品 |
| **配比 / 规格** | 5:1 ↔ 1:5、2.08 ↔ 2.8 | 施工指导错误 |

做法：把成片用到的**每一张**标签图逐张裁切放大重读一遍（本项目 6 张，约 10 分钟），
核对结果整理成"标签 → 字幕"对照表留档（见第九节的项目备忘）。

产出：一张 `| 段号 | 起止 | 源片段+入出点 | 时长 | 字幕主/副 |` 表，
外加一张 `| 位置 | 字幕文字 | 源图上的原文 | 判定 |` 核对表。

## 三、图形层：统一用 Pillow，且必须分层合成

### ⚠️ 头号坑：RGB 画布上画半透明色不混合

```python
# ✗ 无效：水印 alpha=10 仍渲染成近乎不透明白字，直接压死正文
img = Image.fromarray(arr, "RGB")            # 或 vgrad() 返回 RGB
d = ImageDraw.Draw(img, "RGBA")
d.text(..., fill=(255,255,255,10))           # 期望极淡，实际很实

# ✓ 正解：分层绘制 → alpha_composite
base  = vgrad(W, H, NAVY_A, NAVY_B)          # 返回 RGBA
L     = Image.new("RGBA", (W, H), (0,0,0,0))
ImageDraw.Draw(L).text(..., fill=(255,255,255,14))
out   = Image.alpha_composite(base, L).convert("RGB")
```
**判据**：渲染后抽样水印区域像素，其亮度应≈底色；若≈255 说明没混合。

### 叠加层规格
- 每段生成**一张整帧 RGBA PNG**，段内 `overlay=0:0` 一次叠上；字幕天然跨整段，省掉逐时刻 enable 链。
- 字幕条：圆角矩形 + 金色描边 + 左侧金色竖条；主字 Bold、副字 Medium；`textlength` 超宽时**逐档缩字号**。
- 中文字体（**只许 OFL**）：`C:/Windows/Fonts/Noto Sans SC Bold (TrueType).otf`(Bold) / `Noto Sans SC (TrueType).otf`(常规)；
> ⛔ **字体授权硬规则（2026-10-17 起）**：中文字体**只许用 SIL OFL 授权的** —— `Noto Sans SC` / `Noto Sans SC Bold` / `Noto Serif SC` / `思源宋体` / `思源黑体`。
> **禁止**使用**微软雅黑、中易黑体、中易宋体、等线（Deng）、楷体、仿宋**等**非免费商用**字体
> —— 收费产品中把字形渲染进成片属高风险；**按字体名称判定，不看文件名**。
> 路径含空格/括号时，**复制到工作目录并命名为 `noto.otf` / `noto-bold.otf`**，用相对路径调用。

  字距要手写（逐字符累加 `textlength`），Pillow 无 letter-spacing 参数。
- **竖屏安全边距**：字幕条底部放在 `H-340` 而非 `H-58`，避开抖音/视频号的底部 UI 遮挡区。

## 四、ffmpeg 分段合成

### 统一编码参数（保证 concat `-c copy` 可行）
```
-c:v libx264 -crf 19 -preset medium -pix_fmt yuv420p -r 30
-c:a aac -b:a 192k -ar 48000 -ac 2 -movflags +faststart
```
Crf 16 时 88 秒 1080p 会到 ~95 MB（≈13 Mbps），对"720p 源上采"是浪费；**crf 19 约 6 Mbps / 65 MB** 更合适。

### 三类段
```bash
# (0) 【动手前先做一次方向判定】决定"满屏"还是"fit"：
#     源真实宽高比 == 画幅宽高比 → 才允许直接铺满
#     源真实宽高比 != 画幅宽高比 → 必须走 fit（模糊底 + 整幅入画），否则必然变形

# (1) 视频段（横屏）：仅在"源真实方向也是横的"时才可直接铺满
"[0:v]scale=1920:1080:flags=lanczos,setsar=1,fps=30[bg];[bg][1:v]overlay=0:0:format=auto[v]"
#     -map [v] -map 0:a -t DUR ...
#     ⚠️ 源若是竖拍（带 displaymatrix）→ 这一行会把 720x1280 竖画面拉成 1920x1080 横画面。
#        正解是改走与照片段相同的 fit 布局（两侧模糊底），而不是铺满。

# (2) 视频段（竖屏）：模糊底 + 裁切带 + 叠加层
"[0:v]split=2[a][b];
 [a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,
    scale=180:320,gblur=sigma=7,scale=1080:1920:flags=bicubic,eq=brightness=-0.32:saturation=0.70,fps=30[bg];
 [b]scale=1280:720:flags=lanczos,crop=1080:720:100:0,scale=1080:720:flags=lanczos,fps=30[fg];
 [bg][fg]overlay=0:540[c];[c][1:v]overlay=0:0:format=auto[v]"
#     ⚠️ [b] 的 scale=1280:720 同样写死了"源是横的"。源为竖拍时先 transpose，
#        或干脆整段换成 fit 布局（见下"整幅展示"一节）。

# (3) 照片段：平移 Ken Burns（保留整幅内容）
"[0:v]scale=1920:-2:flags=lanczos,crop=1920:1080:0:'(in_h-out_h)*t/DUR',
 zoompan=z='min(1+0.0006*on,1.06)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'
        :s=1920x1080:fps=30,setsar=1[base];[base][1:v]overlay=0:0:format=auto[v]"

# (4) 卡段（片头/片尾）：静帧 + 淡入淡出，输入补静音
#     -loop 1 -framerate 30 -i CARD.png  -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=48000
#     -vf "scale=W:H:flags=lanczos,setsar=1,format=yuv420p,fade=t=in:st=0:d=0.6"  -t DUR
```

### ⚠️ crop 在视频输入上的静默陷阱

```bash
# ✗ crop 直接作用于 h264 解码输出 → "Invalid too big or non positive size for width '1080' or height '720'"
#   （即便解码帧确为 1280x720、SAR 1:1、rawvideo 字节数 = w*h*1.5 完全正确）
"$FF" -ss 33 -i src.mp4 -frames:v 1 -vf "crop=1080:720:100:0" out.png      # 失败

# ✓ 先插一层 scale 产生新帧，crop 即正常
"$FF" -ss 33 -i src.mp4 -frames:v 1 -vf "scale=1280:720,crop=1080:720:100:0,scale=1080:720" out.png
```
- 同源图片输入（`-loop 1 -i x.jpg`）上 crop 正常 → 说明是**解码输出帧**的问题，不是参数问题。
- **ffmpeg 7.1 的 `crop` 没有 `eval` 选项**，传 `eval=frame` 报 `Option not found`；x/y **默认逐帧求值**（可做平移动画）。
- `zoompan` 要求输入宽高比 == 输出 `s`，否则被拉伸；4:3 图进 16:9 帧须**先 crop 再 zoompan**。
- 平移表达式避免 `min(...,1)`：直接写 `(in_h-out_h)*t/DUR`，`t` 到 DUR 恰好取满，无逗号更稳。

### ⚠️ 安全删除守卫会拦构建目录清空
`shutil.rmtree(build_dir)` 在目录文件数 ≥50 时返回 `SAFE_DELETE_BULK_CONFIRM_REQUIRED` 并**终止脚本**。
→ **构建目录不必清空**：所有 ffmpeg 调用带 `-y` 直接覆盖即可，零删除、零风险。

### ⚠️⚠️ 三个必踩坑：drawtext 中文层 / Python 传参 / 中文路径

本项目（`<项目目录>\某高校校区防水实例`，39.68s 竖屏案例片）走的是
**drawtext 烧中文文字层**路线（不预渲染叠加层 PNG），一次踩齐三坑，共同特征是
**报错信息完全不指向真因**——三个都曾在"看起来正确的写法"上反复失败。

#### ① `fontfile` 的 Windows 盘符冒号**必须转义**

```bash
# ✗ 报 "Error parsing a filter description around: " —— 报错点根本不在 fontfile
-vf "drawtext=fontfile='C:/Windows/Fonts/NotoSansSC-VF.ttf':text='标题':x=..:y=.."
# 真因：filter 描述里 `:` 是选项分隔符 → 被解析成 `fontfile=C` + `:/Windows/...` 找不到选项名

# ✓ 盘符冒号写成 \: ，路径用正斜杠
-vf "drawtext=fontfile='C\:/Windows/Fonts/NotoSansSC-VF.ttf':text='标题':..."
```
- 排查弯路：先怀疑了字体缺失、`text` 里的中文、`x/y` 表达式，全不是。
  **判据极简**：把整个 `fontfile` 选项删掉（走 fontconfig）能过 → 就是它。

#### ② 但 `alpha=` / `enable=` 表达式里的逗号**不要**转义

```bash
# ✗ 过度转义 —— 反而把语法弄坏
alpha='if(lt(t,1)\,0\,1)'          # 报同样的 "parsing a filter description around"
# ✓ 单引号已经保护了逗号，原样写
alpha='if(lt(t,1),0,1)'
```
- 去程表达式（淡入淡出）同理，整串用单引号包住即可：
  `alpha='if(lt(t,0.35),t/0.35,1)'`。
- 口诀：**冒号要逃（`\:`），逗号不逃**。二者规则相反，混用必翻车。

#### ③ ⚠️⚠️ Python `subprocess` 调 ffmpeg 传长滤镜串**会被破坏**

```python
# ✗ 同一条字符串：bash 里直接调 OK，从 Python subprocess 传进去报
#   "Error parsing a filter description around: ,"（断点恰在第一个逗号处）
subprocess.run([FF, "-vf", long_filter_string, ...])
```
- 本项目最终架构（**推荐直接照搬**）：**Python 只准备滤镜文件，Bash 负责执行 ffmpeg**。
  ```python
  # Python：把滤镜串写进 ASCII 临时目录，不放中文路径
  WORK = os.path.join(tempfile.gettempdir(), "cc_ovl")   # %TEMP%\cc_ovl
  open(os.path.join(WORK, "vf.txt"), "w", encoding="utf-8").write(vf)
  ```
  ```bash
  # Bash：把文件内容当参数喂给 ffmpeg
  "$FF" -y -i in.mp4 -vf "$(cat vf.txt)" -c:a copy out.mp4
  ```
- 中文文字内容**一律用 `textfile=` 加载 UTF-8 无 BOM 小文件**，不要把中文写进 `text=`：
  避免标点（`·`、`，`）被 filter 解析器当分隔符，也避免命令行编码问题。
- 另一条失败路线（勿再试）：`-filter_complex_script fc.txt` —— bash / bat 调用均报
  `Failed to set value 'fc.txt' for option 'filter_complex_script'`。

#### ④ ffmpeg 不认含中文的输入/输出/cwd 路径

```bash
# ✗ 报 "Invalid argument"（输入、输出、工作目录只要有一处含中文就炸）
# ✓ 全流程走 ASCII 暂存目录，成功后再搬回中文名
cp "成片.mp4" "$WORK/in.mp4" && "$FF" ... "$WORK/out.mp4" && cp "$WORK/out.mp4" "成片_带字幕.mp4"
```
- 同理 `cv2.imread` 也读不了非 ASCII 路径 → 统一 `PIL.Image.open` 再 `cv2.cvtColor`（见验证链第 8 条）。

#### ⑤ ⚠️ `yuvj420p` 会静默出现（JPEG 输入段专用坑）

```bash
# 症状：出片 Stream 显示 yuvj420p(pc, ...) 而非 yuv420p(tv, bt709)
#   —— 部分平台（尤其中文短视频渠道）会色彩偏移，画面发灰/过饱和。
# 真因：-loop 1 -i x.jpg 这类 JPEG 输入解出 full-range，ffmpeg 默认编成 yuvj420p。
# ✓ 每段编码都显式写死；滤镜链最前面再加一层 format=yuv420p：
"$FF" ... -vf "format=yuv420p,..." -pix_fmt yuv420p -color_range tv \
      -colorspace bt709 -color_primaries bt709 -color_trc bt709 ...
```
- ⚠️ **只传 `-pix_fmt yuv420p` 不够**（`yuvj420p` 仍可能被保留），必须连 `-color_range tv` 一起给。
- **判据**：出片后 `ffmpeg -i out.mp4 2>&1 | grep "Stream #0:0"`，必须见到 `yuv420p(tv, bt709)`。
  只看 `-pix_fmt` 参数等于没验。

#### ⑥ ⚠️ 慢放段的时长统计会骗人（`setpts` 专用坑）

```bash
# 慢放：setpts 拉伸时间轴，输出时长 = 素材取长 / slow
-vf "crop=...,scale=...,setpts=1.83*PTS,fps=30"
```
- 🔴 **陷阱**：若统计脚本仍按"素材取长"累加输出时长，会得出「慢放没生效、这段只有 2.54s」
  的**错误结论**（实测片段文件其实已是 4.63s），进而误改参数、越改越乱。
- ✓ 统计值用 `出长 = 取长 / slow` 换算；**判据一律以 `ffmpeg -i 片段文件` 实测时长为准**。
- 素材不足时的补齐手段：慢放（`setpts`）优先于"拉长静止帧"，但**先目检动作幅度**——
  原地俯身/静态远景慢放无痕，大幅走位慢放会显假。

### 旁白驱动剪辑：用 TTS 的实际停顿点定时长，不要硬凑整

本项目诉求是"约 60 秒"，但 TTS 实测只有 **38.18s** → 改走**画面适配旁白**，而不是拉长/填充。
（v2 重写旁白后为 56.42s，自然接近 60s；**不要为凑时长注水句子**。）

```bash
# 用停顿点自动切出语义段落边界
"$FF" -i vo.mp3 -af silencedetect=noise=-30dB:d=0.30 -f null - 2>&1 | grep silence_
# → EDGE = [0.00, 6.94, 12.37, 17.02, 24.74, 30.53, 34.36, 38.18]
```
- 由 `EDGE` 反推每段时长 `SEGLEN[i] = EDGE[i+1]-EDGE[i]`，各段画面时长严格等于对应旁白段 —— 声画天然对齐。
- 每个语义段可再拆 1~2 个实拍片段，起点用 `-ss` 挑（如 p1 用 1.2s 与 1.6s 各一段），保证"有动作"而非静止。
- **横屏 → 竖屏**统一 `crop=ih*9/16:ih:iw*X:0`；`X` 必须**逐素材目检标定**（人物偏左取 0.13、居中 0.25、偏右 0.40），
  固定取中心会把人物裁出边缘。
- 静态桶图做片头/片尾端板时，`scale=W*2:H*2:force_original_aspect_ratio=increase,crop=W*2:H*2`
  （3:4 竖图直接 `scale=W*2:-1` 高度不够 3840 → 报 `Invalid too big or non positive size for width`）。

#### ⭐ 段边界定位：比纯 silencedetect 更稳的两步法

单靠 `silencedetect` 会在**句读处全报停顿**，分不清哪几个是段落边界。改用：

1. **字数比例预估**：中文 TTS 语速近似匀速 → `预估边界 = 总时长 × 累计字数 / 总字数`。
2. **就近吸附**：从 silencedetect 的停顿区间里，挑**离预估值最近**的那个区间中点作真实边界。
3. **★ 波形图标线目检**（不可省）：
   ```bash
   "$FF" -y -i vo.mp3 -filter_complex "showwavespic=s=1400x300:colors=0x2E86DE" -frames:v 1 wave.png
   # 再用 PIL 按 edge/总时长×宽度 画竖线 + 标段名，肉眼确认每条线都落在能量谷
   ```
   本项目 6 条边界全部落在波形谷；若某条落在语音中间，说明该段字数比例与语速偏差大，
   需回到第 2 步换一个更近的停顿区间。**只报数字不画线，等于没验。**

#### ⭐ TTS 中文多音字：用同音字改写 TTS 文本，字幕仍写正确字

- 现象：`水性丙烯酸面漆` 的「丙」被读成「丁」（bǐng→dīng）。
  但「丙」在普通话里只有 bǐng 一读，模型读错只能**绕开它**。
- ✅ 做法：TTS 的 `text` 参数里写**同音字**「**饼**烯酸」（"饼"只有 bǐng 一读，必定读对），
  而**字幕/drawtext 仍写正规的「丙烯酸」** —— 音频与字幕分离，各用各自最优的表示。
- ⚠️ 本机**听不到音频**（Read 工具不支持音频、无 whisper/vosk），
  所以"TTS 读对了吗"**不能自判** → 要出**对比试听文件**（A 原字 / B 同音字 / C 加注音）
  交用户确认，或直接采用同音字这种**确定性方案**（不依赖听辨）。
- 专有名词（校名/机构全称）同理：先在 TTS 前用 WebSearch 核实全称，
  再决定"旁白报全称、字幕保留简称"这类分工。

### ⚠️ 混音的两个静默错误：`-shortest` 截断 + amix 输出单声道

```bash
# ✗ 成片时长莫名少了尾板的 2.5s、且音频变单声道
... [vo][bg]amix=inputs=2:duration=longest ... -shortest
```
- **`-shortest` 会按较短输入（BGM 之外的分支）截断整片** → 改用 `-t {总时长}` 精确控时，删掉 `-shortest`。
- `amix` 不保证通道布局 → 各分支显式 `aformat=channel_layouts=stereo:sample_rates=48000`，
  合片再补 `-c:a aac -b:a 192k -ac 2`。
- 混音后必须 `volumedetect` 复核（实测合格值：`mean=-26.1dB / max=-8.3dB`，不削波、BGM 为背景级）。

### 「整幅展示」照片段：用精确等比 + 双偶的 fit 布局
产品全景/全家福这类图**不能裁**，要整幅入画。做法：照片按精确比例缩到目标框内，四周用
**自身放大模糊**作底（比纯色底高级），再描一圈金框。

```python
# ✗ 近似：bh 定死 → bw = round(bh*ar)，会有 ~0.06% 画幅偏差（亚像素，但既然被投诉"变形"就归零）
# ✓ 精确：取原图约分后的 (p,q)，令 k = min(max_w//p, max_h//q) 并取偶 → (p*k, q*k) 宽高比误差恒为 0
import math
def exact_even(photo, max_w, max_h):
    im = Image.open(photo); g = math.gcd(im.width, im.height)
    p, q = im.width // g, im.height // g
    k = min(max_w // p, max_h // q)
    if k % 2: k -= 1
    return p * k, q * k
```
```bash
# 横屏 fit：照片 ≤1800x856、上留 34；竖屏 fit：照片 ≤1064x1500、居中
"[0:v]split=2[a][b];
 [a]scale=W:H:force_original_aspect_ratio=increase,crop=W:H,scale=w/8:h/8,gblur=sigma=7,scale=W:H:flags=bicubic,
    eq=brightness=-0.32:saturation=0.70[bg];
 [b]scale=BW:BH:flags=lanczos[fg];
 [bg][fg]overlay=BX:BY[c];[c][1:v]overlay=0:0:format=auto[v]"
```
- 金框**画在叠加层 PNG 里**，坐标必须与 `overlay=BX:BY` 完全一致（金框 = `[BX-4, BY-4, BW+8, BH+8]`）。
- 底部留白要够：横屏照片底边 ≈886 → 字幕条顶边 ≈899，间隙 13px；竖屏字幕条固定在 `H-340`。

### 改稿时的责任边界（用户反馈"某段/整片变形"）

**`SAR=1:1` 不能当作"无变形"的证据 —— 它是假阴性。**
本项目实测：源片带 `displaymatrix -90°`，管线把 720×1280 竖画面拉成 1920×1080，
成片的 `SAR` 依然是 `1:1`，分辨率/帧数/时长全对，常规自检全部通过，而画面已变形 267%。

正确的归因顺序（缺一步就会误判）：
1. **比像素，不比参数**：从**源**与**成片**同一时刻各抽一帧，缩到同尺寸算 `central MAD` 与边缘质心位移。
   `MAD > 20` 或质心位移 > 10px ⇒ 不是重采样误差，是几何变换级差异。
2. **查 displaymatrix**：`ffmpeg -i src.mp4 2>&1 | grep -A2 "Side data"`，
   再核对"抽帧实测尺寸"是否等于"`-i` 报的尺寸"——不等即有旋转。
3. **核对每个 scale**：两向都给死值（`scale=1920:1080`）时 `force_original_aspect_ratio` **不生效**，
   非等比源会被硬塞进目标框。
4. 以上都不成立，才谈"拍摄本身"（俯角过陡确实会把圆桶压成扁椭圆）。

> ⚠️ 本项目上一次误判：把用户的"变形"投诉归结为"拍摄俯角过陡"，并据此删段改稿 —— **结论是错的**，
> 真因是第 1、2 步没做。用户第二次仍投诉"还是变形"，才回头查出旋转矩阵。
> **在说出"这是素材的问题"之前，必须先完成像素级比对。**
>
> 补充：当源视频方向与目标画幅天然冲突、且**修完仍有观感损失**时，
> 换一条路线（改用手上的高清原图做静态展示）往往比硬修更稳 —— 见下节。

## 五、拼接与混音
```bash
# 拼接（同编码参数，可直接 copy）
printf "file '%s'\n" seg1.mp4 seg2.mp4 ... > concat.txt
"$FF" -y -f concat -safe 0 -i concat.txt -c copy -movflags +faststart base.mp4

# 混音：原声（高通 + 压缩 + 增益 + 限幅） ‖ BGM（归一到背景级 + 首尾淡入淡出）
"[1:a]atrim=0:TOTAL,asetpts=N/SR/TB,aresample=48000,
      loudnorm=I=-26:TP=-3.0:LRA=9,afade=t=in:st=0:d=2.0,afade=t=out:st=FADE:d=2.6[bgm];
 [0:a]highpass=f=90,acompressor=threshold=-18dB:ratio=3.5:attack=8:release=280:makeup=4dB,
      volume=3.0,alimiter=limit=0.94:level=disabled[org];
 [org][bgm]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95:level=disabled[aout]"
# -map 0:v -map [aout] -c:v copy -c:a aac -b:a 192k
```
- **先测再定增益，不要盲目归一到 -14 LUFS**：手机实拍常见 `mean≈-33 dB / max≈-3.5 dB`
  （底噪低、处理音峰值高）。按均值猛提会让峰值削波、按峰值配平会让环境音听不见。
- 无原声段用 `anullsrc` 补真静音（**不是**不接音轨，否则 concat 会错位）。
- `loudnorm` 对纯静音段增益无效（0×gain=0），可安全整轨处理。

## 六、备选路线：整片改「全静态图版」

**什么时候该换这条路**：源视频方向与目标画幅天然冲突（竖拍素材要出横屏版）、
源片运动冗余/抖动严重、或客户诉求已从"过程记录"变成"逐件看清规格"。
本项目第二次改稿即走此路：撤下两段手机竖拍视频，改用 11 张高清原图逐件展示。

### 架构：Pillow 逐帧 → rawvideo 管道 → ffmpeg 编码（单进程）

```python
p = subprocess.Popen(
    [FF,"-y","-f","rawvideo","-pix_fmt","rgb24","-s","%dx%d"%(W,H),
     "-r",str(FPS),"-i","-","-an","-c:v","libx264","-crf","19",
     "-preset","medium","-pix_fmt","yuv420p","-r",str(FPS),
     "-movflags","+faststart",out],
    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
for i in range(n):
    p.stdin.write(frame.tobytes())
p.stdin.close()
err = p.stderr.read().decode("utf-8","replace"); p.wait()
```
Ken Burns 完全自控（比 `zoompan` 可控、无抖动与量化问题），逐帧算法可断言、可复现。

### ⚠️ 性能坑：每帧重新下采样 4000px 原图 → 慢 8 倍

首版实测 **174 ms/帧**（4 段 690 帧跑不完 120s 前台超时）。根因是每帧都从 4096×3072 原图
crop 再 LANCZOS resize。**正解：预缩放一次。**

```python
def prescale(raw, box, zmax):
    """缩到「输出尺寸 × zmax」的精确等比小图；zmax 略大于最大放大倍数即可。"""
    _,_,bw,bh = box
    tw, th = _exact_even_wh(raw.size, ceil(bw*zmax), ceil(bh*zmax))
    return raw.resize((tw, th), Image.LANCZOS)
src = prescale(raw, box, 1.0 + ZOOM + 0.01)     # 4000px -> ~700px，整段只做一次
# 之后每帧只在小图上 crop：降至 39~83 ms/帧
```
Ken Burns 只放大 ~7.5%，源分辨率远大于输出，**预缩放对画质无损**。

### 几何纪律：只对「窗口尺寸」取整一次

```python
# ✗ 两端各取整一次 -> 误差叠加（实测最坏 0.23%）
c = src.crop((round(x0), round(y0), round(x0+cw), round(y0+ch)))
# ✓ 先定整数窗口尺寸，再由它回推左上角（实测最坏 0.116%，即 1.31px @1136px）
w, h = int(round(iw/z)), int(round(ih/z))
x0, y0 = int(round((iw-w)/2.0)), int(round((ih-h)/2.0))
c = src.crop((x0, y0, x0+w, y0+h)).resize((bw, bh), Image.LANCZOS)
```
- `0.116%` 是**整数像素框架下的理论下限**（1/860 比例分辨率的一半），不是还能继续优化的量。
- 自检方式：把**逐帧**窗口比例与"原图宽高比"比对，报**最坏值**。只报设计值等于没验。

### 叠加层：用 `paste` 而非 `alpha_composite`

```python
f = bg.copy()
f.paste(fg, (bx, by))          # 前景无 alpha，直接贴
f.paste(ov, (0, 0), ov)        # RGBA 叠加层当 mask —— 省掉两次 convert("RGBA")
```

### 横屏放竖图的版面事实（别硬拧）

3:4 竖图放进 16:9 画幅，**只能占约 1/3 幅宽**（高度受限 → 宽 = 高×0.75）。
实测 `max_h=856`：竖图 642×856、横图 1136×852。
曾想"裁成 4:3 让它变宽"，**出裁切预览逐张目检后否决**——桶身、两支滚筒、两袋手套都会被切掉。
最终处理：**保留整幅 fit，把背景压得更暗（`brightness 0.46 → 0.40`）制造聚光感**来补偿空旷。

> 判据：**任何"为了让画面更满"而做的裁切，都必须先出裁切预览图逐张目检。**

### 音频：无原声时删掉整条原声分支

```bash
"[1:a]atrim=0:TOTAL,asetpts=N/SR/TB,aresample=48000,
      loudnorm=I=-19:TP=-3.0:LRA=9,afade=t=in:st=0:d=2.0,afade=t=out:st=FADE:d=2.6[aout]"
# -map 0:v -map [aout] -c:v copy
```
纯 BGM 是唯一音轨，目标响度用 **`I=-19`**（不是背景级的 -26）。
段间**硬切**即可 —— 靠 Ken Burns + 字幕条 + BGM 维持连贯；`xfade` 会改总时长、牵动音频，不必用。
片头/片尾卡的淡入淡出在 Pillow 里做（`ImageEnhance.Brightness(img).enhance(1.0-k)`）。

## 七、验证链（缺一不可）

1. **帧数断言**：`总帧数 == Σ(段秒数 × fps)`，且 `ffmpeg -i` 报的 Duration 与之吻合。
2. **抽帧目检**：每段中点抽一帧拼联络表，**逐帧核对字幕文字 vs 画面里的物件**。
3. **音频峰值**：`-af volumedetect` → `max_volume` 应 ≤ -0.3 dB（不削波）。
4. **BGM 全程可闻**：对"无原声段"单独测窗口，应仍有 ~-27 dB 均值（证明音乐没断）。
5. **画框/安全区**：竖屏字幕条底部 ≈ `H-340`；横屏整幅照片段的金色画框位置与 overlay 坐标一致。
6. **几何比例逐帧验证**（本项目因"变形"被投诉两次后增设的硬关卡）：
   对每段**每一帧**计算"裁剪窗口宽高比"与"原图宽高比"的相对偏差，报**最坏值**。
   判据：输出框与预缩放源的偏差必须 **== 0**（精确等比）；逐帧窗口偏差 **≤ 0.2%**（整数像素下限）。
   只报设计值（"我们做了等比缩放"）等于没验。
7. **源—成片像素比对**（专门用于"变形"类投诉归因）：
   同刻各抽一帧、缩到同尺寸，算 `central MAD` 与边缘质心位移。见第四节"责任边界"。
8. **端到端定位核验**（比"用设计值自证"强得多）：对每段"缩放恰为 1.0 的那一帧"
   （此刻画面即完整原图），把原图按设计尺寸精确等比缩放成模板，
   用 `cv2.matchTemplate(..., TM_CCOEFF_NORMED)` 在**整个成片帧**里独立搜索它的实际位置。
   判据：最佳匹配位置 == 设计坐标（±降采样倍率），且相关度 ≥ 0.9 —— 同时证明"没移位"与"没拉伸"。
   > ⚠️ 三个必踩坑：
   > ① **`cv2.imread` 在 Windows 上读不了非 ASCII 路径**（报 `can't open/read file`）
   > → 改用 `PIL.Image.open` 再 `cv2.cvtColor`（本项目路径含中文，实踩）；
   > ② 成片若有 scrim/压暗层，**模板必须施加同样的 scrim**，
   > 否则相关度被无谓拉低（实测 0.82 vs 施加后 0.99），会被误读成"变形"；
   > ③ 全帧搜索是 `O(W·H·w·h)`，直接跑慢到不可用 → 帧与模板**同除 4 再匹配**（精度 4px，足够）。

## 八、AgentEarth 生成免版税 BGM

- 工具：`ae_cassetteai_music_generator`（**10 额度/次**，必填 `prompt` + `duration` 10–180 秒）。
  提示词要写明"instrumental only / no vocals / no dominant lead melody"，否则主旋律会盖住字幕与读白。
  `ae_elevenlabs_music`（1440 额度/次）通常不必选。
- **`ExecuteTool` 必须传 `tool_url`，不是 `tool_name`**：
  ```json
  {"tool_url":"https://agentearth.ai/agent-api/v1/tool/execute?tool_name=ae_cassetteai_music_generator",
   "params":{"prompt":"...","duration":95}}
  ```
  传 `tool_name` 会得到 `must have required property 'tool_url'` 的参数校验失败。
- 异步完成判据：结果里出现 `audio_file.url`（**不要**依赖 status 字段）。
- 下载：**直连优先**（本机旧代理端口可能已失效 → `requests.Session(trust_env=False)`）；
  远端可能是分块传输（`Content-Length: None`），**最终断言以接口报的 `file_size` 为准**；
  顺序写入的文件是合法前缀，**支持断点续传**（`Range: bytes=<已有字节>-`，注意 200 与 206 分支）。
- **长下载必须 `run_in_background=true`**：走 `python … | tail` 的管道会绕过自动转后台，120s 被 SIGTERM 打断。

## 九、往期实例（可对照）

### 实例 A：指铠 ZK-720 开箱视频（双画幅、静态图路线）
项目 `<项目目录>`：
- 脚本 `output\<session>\working\_zk720_video\`：`_gfx.py`（卡片/叠加层）、
  `_build.py`（实拍剪辑路线：分镜表 + 分段 + 拼接 + 混音）、
  `_static.py`（**全静态图路线**：Pillow 逐帧 + rawvideo + 纯 BGM）、
  `_verify.py`（成片四关验证：元数据/音量/模板匹配定位/抽帧）、`_dl.py`（断点续传下载）。
- **v1.0 / v1.1（已作废，保留备查）**：`指铠ZK-720_开箱视频_横屏16x9_v1.0.mp4`
  （1920×1080 / 64.9 MB / 86.00s）、`..._竖屏9x16_v1.0.mp4`（1080×1920 / 47.7 MB / 86.00s）。
  **含未修正的 displaymatrix 旋转畸变 —— 不要当作参考样本。**
- **v2.0（现行）**：`指铠ZK-720_开箱视频_横屏16x9_v2.0.mp4`（1920×1080 / 17.7 MB / 1957 kb/s / 65.50s）、
  `..._竖屏9x16_v2.0.mp4`（1080×1920 / 22.0 MB / 2479 kb/s / 65.50s）；
  13 段 / 1965 帧；峰值 −2.5 dB、均值 −19.3 dB；几何核验 11/11 段通过。

### 实例 B：某高校校区屋顶防水案例片（竖屏、旁白驱动 + drawtext 中文层）

项目 `<项目目录>\某高校校区防水实例`：
- 素材：11 段手机实拍（全部 1280×720/30fps，四步工艺流程 + 第三年验收）+ 1 张产品实物图。
- 路线与实例 A 不同：**不走 Pillow 预渲染叠加层，直接 drawtext 烧中文文字层**，
  并**用 TTS 旁白时间轴反推画面时长**（非先定画面再配音）。
- 脚本 `_build\build.py`（段落编排 + 竖屏裁切 + 拼接 + 混音）、`_build\prep_overlay.py`
  （生成 drawtext 滤镜串 → 写 `%TEMP%\cc_ovl\vf.txt`，由 Bash 执行）；
  中间件 `_build\vo.mp3`（TTS 38.18s）、`_build\bgm.wav`（59.91s）。
- 成片：`某高校校区屋顶防水案例_带字幕.mp4`（**34.76MB / 39.68s / 1080×1920 / 30fps / stereo 48kHz**，
  均值 −26.1dB、峰值 −8.3dB）；另有同内容无文字层版 `..._案例.mp4`（33.1MB）。
- 文字层构成：片头主副标题（避开产品桶身标签区，副标题配半透明底条）、5 个步骤角标、片尾品牌条。
- 本次新踩、已并入第四节的坑：`fontfile` 冒号转义、`alpha/enable` 逗号不转义、
  Python subprocess 传滤镜串被破坏、ffmpeg 中文路径不受理、`-shortest` 截断 + amix 单声道。
- ⚠️ 排版纪律：片头标题**不要压在桶身标签上**（初版与"渗入固结型防水涂料"重叠 → 上移到白色桶盖区）；
  步骤角标**不要压安全帽**（y 从 152 下移到 196）。凡文字层落位，都要抽帧目检一次。

**v2 修正版（旁白纠错 + 画面优化）**：
- 触发：用户指出两处旁白错误 —— ①「某高校」应报**全称「某职业技术大学」**；
  ②「水性丙烯酸面漆」的「丙」被读成「丁」，应为 bǐng。
- 改动四处：① 旁白重写（校名全称 + 「丙烯」→ TTS 写同音字「**饼烯酸**」，字幕仍写「丙烯酸」），
  56.42s；② **验收段换实拍**（v1 角标"验收·第三年无渗漏"却配七件套未开封产品图，逻辑错位 →
  改用 `防水处理完毕（现在为第三年未见任何渗漏）.mp4`，2.77s 慢放到 6.12s）；
  ③ 片头副标题补全称行「某职业技术大学 · 某校区」，底条宽度改按"字号×字数"自适应；
  ④ **片尾端板改 fit 布局**（v1 把 4:3 横图强铺 9:16 裁掉 25% 高度 + 推近后只剩局部、构图切碎 →
  改「自身模糊底 + 整幅入画」，七件套完整展示）。
- 新坑：`yuvj420p` 静默出现（JPEG 输入段）、慢放段时长统计骗人（`setpts` 段）—— 均已并入第四节 ⑤⑥。
- 成片：`某高校校区屋顶防水案例_v2_带字幕.mp4`（41.79MB / 57.62s / 1080×1920 / 30fps /
  `yuv420p(tv,bt709)` / stereo 48kHz；mean −26.2dB、max −6.2dB）。
- 脚本：`_build\build_v2.py`、`_build\prep_overlay_v2.py`、`_build\vo_text.py`、`_build\vo_edges.py`。
  横屏比竖屏**体积更小**是正常的：竖屏里竖图占 74% 幅面（1062×1416），横屏里同图只占 33%（642×856），细节少、码率自然低。
