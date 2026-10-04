# Video Prompt Guide — 5-Stage Template · Camera-Move Library · Multi-Shot Planner

> 视频提示词的**完整叙事级**指南。短需求/单镜头走 [`prompt-template.md`](prompt-template.md) § Video Generation 的 6 元素公式（快速路径）；本指南用于：叙事短片、逐秒时间线控制、高角色一致性要求、multi/keyframes 多镜头。
>
> 结构吸收自 [jnMetaCode/ai-shortfilm-prompts](https://github.com/jnMetaCode/ai-shortfilm-prompts)（MIT，仅其自著内容）的 methodology.md 与 templates/；本文全部措辞为本仓库自著。上游 `prompts/` 目录为 Mx-Shell 保留所有权利（ARR），**未搬运任何条目**。运镜英文措辞保留英文——视频模型对英文提示词更稳。

## 选择路径

| 场景 | 用什么 |
|------|--------|
| 单镜头、需求简单（"猫在沙滩走"） | 6 元素快速路径（prompt-template.md） |
| 叙事短片、逐秒控制、身份一致性要求高 | 本指南 § 5-Stage Template |
| `multi` / `keyframes` 多图视频 | 本指南 § Multi-Shot Planner（三件套） |

---

## 5-Stage Template（顺序不可打乱）

五段各自负责一层锚定：**Stage 1-2 锚定主体身份 → Stage 3 锚定视觉基调 → Stage 4 立镜头规则 → Stage 5 排时间线**。Stage 5 里出现的每个名词（"残骸"、"主角"）都依赖 Stage 2 的定义——顺序打乱后模型容易丢失对应关系，产生身份漂移。

五段拼接后整体作为 `--instruction` 传入（多行文本直接传，无需压成一行）。

### Stage 1 · Theme tags（主题标签，竖线分隔）

```
科幻短片 | 沙漠星球 | 孤独宇航员 | 电影感
```

用最少的标签锚定"这是什么片子"。给模型一个最高层的语义锚点，后续所有段落都在这个语义域内解释。

### Stage 2 · Subject & Scene（角色/场景锚定）

```
Face: 30 岁亚洲女性宇航员，短发，左眉一道细疤
Clothing: 白色舱内服，橙色臂章，银色胸牌编号 AX-07
Scene: 红色荒漠星球地表，远处废弃飞船残骸，昏黄尘暴
```

身份识别点（脸型/发型/疤痕/服装识别物）必须**具体到可核对**——这是防 subject drift 的第一道锚。写"一个美丽的宇航员"等于没写。

### Stage 3 · Atmosphere & Quality（氛围/画质，含相机与镜头锚定）

```
Atmosphere: 夕阳低角度暖光，尘暴弥漫，孤独压抑
Camera: 35mm 胶片质感，手持轻微晃动，2.39:1 宽画幅感
Quality: cinematic realism, high dynamic range, fine film grain
```

> **纪律：参数不入 instruction**。分辨率/画幅/时长/帧率是运行参数，只走 CLI flags（`--aspect` / `--duration` / `--num-frames`）；写进指令不会被解析，还会与 flags 打架（指令写 "8K" 而实际输出 1152x768，落差全由用户承担）。画质**氛围词**（cinematic realism / high dynamic range）属于描述，可以写。

### Stage 4 · Camera Rules（镜头规则，三行）

```
镜头运动: 缓慢推进（dolly-in），主体始终居中
禁止事项: 不切换镜头，不出现文字/水印
一致性: 人物面部与服装全程不变
```

规则类约束单独成段——混在描述里模型会当成可选氛围词，单独列出才会被当作硬约束。

### Stage 5 · Timeline（逐秒或逐镜分镜）

```
0-3s: 宇航员跪地检查头盔，镜头由远推进至半身
3-5s: 抬头望向残骸，风掀起尘土
5-8s: 起身走向残骸，镜头跟随，渐远收尾
```

逐秒（3/5/10/18s 视频）或逐镜（multi/keyframes）。每条只写"谁在动 + 怎么动 + 镜头怎么动"，不要在这里重复 Stage 2/3 已锚定的外观描述。

### 完整示例（agnes-video t2vid，10s 由 241 帧 @24fps 组合）

```
科幻短片 | 沙漠星球 | 孤独宇航员 | 电影感
Face: 30 岁亚洲女性宇航员，短发，左眉一道细疤
Clothing: 白色舱内服，橙色臂章，银色胸牌编号 AX-07
Scene: 红色荒漠星球地表，远处废弃飞船残骸，昏黄尘暴
Atmosphere: 夕阳低角度暖光，尘暴弥漫，孤独压抑
Camera: 35mm 胶片质感，手持轻微晃动
Quality: cinematic realism, high dynamic range, fine film grain
镜头运动: 缓慢推进，主体始终居中
禁止事项: 不切换镜头，不出现文字/水印
一致性: 人物面部与服装全程不变
0-3s: 宇航员跪地检查头盔，镜头由远推进至半身
3-5s: 抬头望向残骸，风掀起尘土
5-8s: 起身走向残骸，镜头跟随
8-10s: 镜头缓缓拉远，身影渐小，渐远收尾
```

（执行命令里配 `--aspect 16:9 --duration 10s`——分辨率与时长走 flags，不进上面的 instruction。）

---

## Camera-Move Library（运镜库 · 裁剪收录）

每条：**名称（中英）+ 可直接粘贴的英文措辞（`{subject}` 占位）+ 戏剧效果 + 适用类型**。从上游 50 条中裁剪出通用性最强的条目；完整 50 条见上游 `templates/camera-move-library.md`（MIT）。

| 名称 | English phrase (paste-ready) | 戏剧效果 | 适用类型 |
|------|------------------------------|----------|----------|
| 推进 Dolly-in | slow dolly-in toward {subject} | 聚焦、压迫感、情绪积累 | 悬念/特写 |
| 拉远 Dolly-out | slow dolly-out revealing {subject}'s surroundings | 揭示环境、孤独感 | 开场/结尾 |
| 跟随 Tracking | tracking shot following {subject} from behind | 代入感、行进叙事 | 人物行走 |
| 环绕 Orbit | camera orbits around {subject} | 史诗感、立体展示 | 产品/IP 展示 |
| 横摇 Pan | slow pan from left to right across {subject} | 全景展示、从容 | 风景/场景 |
| 纵摇 Tilt | slow tilt up from {subject}'s feet to face | 逐步揭示、权威感 | 人物登场 |
| 手持 Handheld | handheld camera with subtle shake following {subject} | 纪实、紧张、临场 | 追逐/纪实 |
| 升降 Crane-up | crane shot rising above {subject} | 升华、宏大收尾 | 结尾 |
| 急推 Zoom crush | sudden zoom-in on {subject} | 冲击、惊吓 | 高潮点 |
| 静止 Static | static shot, {subject} moves within the frame | 稳定、观察者视角 | 对话/静物 |
| 越肩 Over-shoulder | over-the-shoulder shot framing {subject} | 对话感、窥视感 | 双人对话 |
| 微距 Macro | extreme macro close-up on {subject} | 细节张力、质感 | 产品/材质 |
| 低角度 Low-angle | low-angle shot looking up at {subject} | 崇高、压迫、英雄感 | 人物塑造 |
| 高角度 High-angle | high-angle shot looking down at {subject} | 渺小、脆弱、全局观 | 环境叙事 |
| 希区柯克变焦 Dolly-zoom | dolly-zoom on {subject}, background stretching | 不安、认知失调 | 心理惊悚 |
| 慢动作时报 Slow reveal | {subject} revealed slowly as mist clears | 悬念兑现 | 揭示时刻 |

**用法**：替换 `{subject}` 后直接拼进 Stage 4 的"镜头运动"行或 6 元素公式的运镜位。一条 `--instruction` 只用 1 个主动运镜（多运镜叠加容易互相打架，逐秒分镜里除外）。

---

## Multi-Shot Planner（multi / keyframes 模式 · 三件套）

对应 `video.py` 的 `multi`（多图融合）与 `keyframes`（关键帧过渡），素材为 `--images URL1 URL2 ...`（≥2 张公网图）。多镜头最大的失败模式是**跨帧身份/风格漂移**——三件套各堵一个漏洞。

### 1 · 主体注册表（Subject registry）——堵身份漂移

给每张图登记"图 N = 主体 X"，编号全程稳定，并在指令里显式声明同一性：

```
Image 1 = 主角 #1（红裙女性，短发）
Image 2 = 同一主角 #1 走到门口

指令声明: "The woman in image 1 and image 2 is the same person (#1).
Keep her face, red dress, and hairstyle identical across all shots."
```

### 2 · 氛围锁（Atmosphere lock）——堵风格漂移

风格核 + 色板**只写一次**，全程引用，不逐镜改写：

```
Style core: cinematic realism, warm sunset palette (amber, coral, dusty rose)
```

### 3 · 帧间运动方向声明（Inter-frame motion）——堵"自由发挥"

每对帧之间写明：谁在动、往哪动、镜头怎么动。只写"A 变成 B"模型会自由补全，导致轨迹漂移：

```
Frame 1 → Frame 2: #1 向画左行走三步，镜头同步左移（pan left），背景视差向后
```

### 反模式

- ❌ 两图主体描述不一致（图 1"红裙"、图 2 写成"蓝裙"）
- ❌ 只写"A 融合到 B"，不写运动方向与镜头行为
- ❌ 每个 keyframe 重复改写风格词（风格核漂移）

---

## Checklist（本指南场景）

- [ ] 5 段顺序未打乱？（Stage 5 的名词全部能在 Stage 2 找到定义）
- [ ] 运镜措辞直接粘贴英文、`{subject}` 已替换？
- [ ] 一条指令只用 1 个主动运镜（逐秒分镜除外）？
- [ ] multi/keyframes：主体注册表 + 氛围锁 + 帧间运动方向，三件套齐全？
- [ ] 短需求没有过度工程化？（单镜头简单需求走 6 元素快速路径即可）
- [ ] 身份识别点具体到可核对（疤痕/胸牌编号/发色），而非"美丽/帅气"类笼统词？
- [ ] 参数不入 instruction？（时长/画幅/分辨率/帧率全部走 CLI flags，指令里没有 "8K"/"18 秒" 类硬参数声明）

### 写后自检（生成前最后 30 秒）

- [ ] 通读一遍最终 instruction：每个名词都能在 Stage 2 找到定义？出现即删或回填锚定。
- [ ] 参数类词汇（分辨率/时长/帧率/模型名）已全部路由到 CLI flags？
- [ ] 质量失败预留迭代位：先 3s 短视频验证动作，失败按 SKILL.md Failure Modes 的视频 prompt 侧分支**单变量**修法改写（一次只改一段/一个镜头），不整段重写。
