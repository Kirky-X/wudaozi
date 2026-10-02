# Structured Prompt Template

> Users' image generation requirements are usually incomplete ("draw a cat"). This template breaks down vague requirements into **7 dimensions**, completes each dimension one by one, then assembles the Boogu `--instruction`. Boogu-Image has good support for Chinese, which is the primary language; English is used only when specific style terms are more precise.

## Core Formula

```
[Subject] + [Action/Expression] + [Background/Environment] + [Composition/Perspective] + [Lighting] + [Style/Medium] + [Quality/Detail]
```

**Order matters**: Subject comes first, quality serves as the fallback. Any missing dimension should be filled with reasonable defaults from the "options library" below, but **you must explicitly list the complete 7 dimensions** for user confirmation — never silently fill them in.

---

## Seven-Dimension Options Library

### 1. Subject — Who/what is the focal point

- **Person**: age/ethnicity/hairstyle/clothing (e.g., "a silver-haired elder in a navy blue changshan")
- **Animal**: breed/color/pose (e.g., "an orange British Shorthair, curled up")
- **Object**: material/era/state (e.g., "a brass vintage pocket watch, dial slightly oxidized")
- **Scene**: architecture/landmark/nature (e.g., "Guilin karst peak forest")
- Default if missing: ask user to provide; cannot be empty

### 2. Action/Expression

- Person: smiling/thinking/running/glancing back/studying
- Animal: sleeping curled/pouncing/gazing/grooming
- Still life: floating/scattered/displayed ("persimmons scattered on a wooden table")
- Default if missing: Person → "standing still, gazing"; Still life → "natural display"

### 3. Background/Environment

- Natural: mountains/ocean/forest/desert/snowfield/starry sky
- Indoor: cafe/study/lab/ancient temple
- Abstract: solid gradient/light bokeh/geometric
- Default if missing: Match the subject's temperament (Chinese style → landscape painting; portrait → simple bokeh)

### 4. Composition/Perspective

- Shot size: close-up / half-body / full-body / long shot / panorama
- Perspective: eye-level / top-down / low angle / bird's eye / worm's eye
- Lens: 35mm street / 85mm portrait / wide-angle / macro
- Composition rule: rule of thirds / centered symmetry / leading lines / frame composition
- Default if missing: Portrait → "85mm half-body, rule of thirds"; Landscape → "wide-angle long shot"

### 5. Lighting — Determines atmosphere

- Natural: golden hour / blue hour / noon harsh light / overcast soft light / moonlight
- Artificial: neon / candlelight / industrial cool light / cyberpunk purple
- Direction: backlight / sidelight / top light / Rembrandt lighting
- Default if missing: Warm scene → "golden hour backlight"; Cool scene → "blue hour sidelight"

### 6. Style/Medium — Determines tone

- Photography: Leica street / Hasselblad portrait / film grain / cinematic
- Painting: Chinese gold-leaf / ink wash / oil painting impasto / ukiyo-e / concept art
- Rendering: 3D / isometric vector / pixel / low-poly
- Default if missing: Realistic → "cinematic photography"; Artistic → "concept art"

### 7. Quality/Detail — Fallback enhancement

- Standard phrases: "highly detailed / sharp / 8K / masterpiece / professional quality"
- Material emphasis: "skin texture / fabric weave / metallic sheen"
- Default if missing: Always append "highly detailed, professional quality"

---

## Templates (Copy directly)

### Chinese Template

```
[Subject], [action/expression]. Background is [background]. [Shot size], [perspective], [lens], [composition].
[Lighting description]. [Style/medium] style, highly detailed, professional quality.
```

### English Template (use when specific style terms are more precise)

```
[subject] [action], set in [background]. [shot size], [view], [lens], [composition].
[lighting]. [style/medium] style, highly detailed, masterpiece, professional quality.
```

---

## Three Complete Examples

### Example A: Street Photography (Portrait)

- User's words: "draw an elderly scavenger"
- 7-dimension completion:
  1. Subject: An elderly scavenger with weathered skin, dark complexion, deep wrinkles
  2. Action: Head bowed, organizing a woven bag, expression weary yet focused
  3. Background: City street, trash cans and traffic lights in the background
  4. Composition: 35mm street, eye-level, rule of thirds slightly left
  5. Lighting: Overcast soft light, slight diffuse reflection
  6. Style: Leica street photography, film grain
  7. Quality: High detail, photographic texture
- Final instruction:
  > An elderly scavenger with weathered skin, dark complexion, and deep wrinkles, head bowed organizing a woven bag, expression weary yet focused. Background is a city street with trash cans and traffic lights in the distance. 35mm street shot, eye-level perspective, rule of thirds slightly left. Overcast soft light. Leica street photography style, film grain, high detail, photographic texture.

### Example B: Chinese Art Style (Landscape)

- User's words: "Guilin landscape"
- Final instruction (following official test_base.sh paradigm):
  > A Chinese gold-leaf style landscape painting, depicting the magnificent scenery of Guilin mountains under golden light. Mountains layered in the distance, river like a mirror, mountain peaks outlined with glowing golden lines. The painting combines azurite and malachite mineral pigments with gilded texture, featuring oil painting impasto brushstrokes in certain areas, golden particles floating in the air, creating a dreamy, hazy, yet grand atmosphere.

### Example C: IP Character (Product/Character)

- User's words: "make an owl IP"
- After 7-dimension completion:
  > An anthropomorphized owl IP character, round body, wearing copper-framed round glasses, dressed in a dark brown vest, expression wise and gentle. Background is a warm old library with scattered scrolls and ink bottles. Half-body close-up, eye-level perspective, centered composition. Soft warm sidelight. Pixar 3D rendering style, delicate material, high detail, professional concept design.

---

## Image-to-image (ti2i) — Change + Preserve

> Image-to-image prompt mindset **differs from text-to-image**: instead of describing a scene from scratch, it declares "what to change + what to preserve". Works with both agnes-image-2.1-flash and boogu ti2i.

### Reference role: `--ref-role subject|style|composition`

参考图"拿来做什么"决定指令语义，CLI 用 `--ref-role` 声明（agnes/boogu，确定性子句注入）：

| Role | 语义 | 典型需求 |
|------|------|----------|
| `subject`（默认） | 参考图即主体本身，行为与历史一致 | "把她的背景换成沙滩"、"给这只猫戴顶帽子" |
| `style` | **只借画风勿抄主体**——注入"参考图仅作风格参照（色板/质感/渲染风格），不得复现其主体"约束 | "用这张图的赛博朋克画风画一只完全不同的机器狗" |
| `composition` | **只借构图勿抄主体**——注入"仅作构图参照（取景/裁切/机角/光位），渲染不同主体"约束 | "借这张海报的构图与光位，主体换成我们的产品" |

裸参考图无法表达后两种意图（模型会无条件把参考图当主体）——"借构图换主体"类需求必须显式传 role。

### Core Formula

```
[Change requirements] + [New style/scenery] + [Elements to add or remove] + [Elements to preserve]
```

**Order matters**: First state what the result should look like, then state what cannot change. **Preserved elements are the soul of ti2i** — without preservation, the model has free rein, causing composition drift and subject deformation.

### Four-Element Options Library

| Element | How to write | Example |
|---------|-------------|---------|
| Change requirements | Verb-led, specify overall transformation direction | "Change to cyberpunk nightscape" / "Switch to watercolor style" |
| New style/scenery | Target tone or environment | "Cinematic cyberpunk" / "Rainy night street" |
| Add/Remove | Specific element additions or deletions | "Add neon signs and wet road reflections" / "Remove background pedestrians" |
| Preserve | Composition/subject/layout/camera angle — invariant items | "Preserve original street layout, camera angle, and main building shapes" |

### Complex Edits: Visual Hierarchy

For multi-element edits, declare in layers to avoid element conflicts:

```
[Primary subject: preserve/change] + [Background environment: replace] + [Secondary details: add/remove] + [Style/lighting constraints]
```

Example: "Port city built on cliffs (preserve subject), change daytime to cloudy sunset sky (replace background), add hundreds of small boats and glowing windows (add detail), maintain cinematic realism and wide-angle composition (constraints)."

### Three Complete Examples

**Example A · Style Transfer** (original: "turn this street scene into cyberpunk"):
> Transform the daytime street scene into a cinematic cyberpunk nightscape, adding neon signs and wet road reflections, while preserving the original street layout, camera angle, and main building shapes.

**Example B · Partial Recoloring** (original: "change this cup to orange, keep everything else"):
> Change the subject cup's color to orange, while preserving the original composition, background environment, lighting direction, and all other elements unchanged.

**Example C · Background Replacement** (original: "change background to beach"):
> Replace the background with a tropical beach scene, adding ocean waves and distant sailboats as environmental elements, while maintaining the person's pose, clothing, camera angle, and lighting direction unchanged.

---

## Special Scenario Templates (Logo / IP / Product Derivatives)

> All three are **t2i subtasks using the same Boogu-Image t2i backend**, only prompt templates differ. Boogu doesn't bind to any external API.

### § Logo · Brand logo / Icon / Hero visual

**One question at a time to clarify priority**: Purpose (brand hero visual / App icon / social avatar) → Style (minimalist geometric / hand-drawn / wordmark) → Tone (warm / cool / energetic).

**Template formula**:

```
[Core graphic imagery], [brand tone adjective]. Centered symmetric composition, [solid/minimalist] background.
[Minimalist vector/flat/hand-drawn] style, [brand primary color palette], uniform soft light with no harsh shadows, high detail, professional brand design.
```

**Complete example**: "make a coffee brand logo" →

> A geometric graphic mark fusing a coffee bean and coffee cup, warm handcrafted tone. Centered symmetric composition, pure cream-white background. Minimalist vector flat style, warm earthy color palette (brown, cream, orange), uniform soft light with no harsh shadows, high detail, professional brand design.

- Recommended: `t2i base --aspect 1:1`
- ⚠️ Output is an **illustration-style logo**, not a scalable vector source file; requires post-processing vectorization (Illustrator / Figma tracing).

### § IP · Anthropomorphized character / Mascot / Character design

**One question at a time to clarify priority**: Species/prototype (animal / fictional / personified) → Personality (wise / lively / aloof) → Rendering style (Pixar 3D / designer toy blind box / flat vector).

**Template formula** (expanded from Example C):

```
An anthropomorphized [species] IP character, [body type], [clothing/accessories], expression [personality descriptor].
Background is [simple scene matching the character's temperament]. Half-body close-up, eye-level perspective, centered composition.
Soft [warm/cool] sidelight. [Pixar 3D / designer toy blind box / flat vector] rendering style, delicate material, high detail, professional concept design.
```

- Recommended: `t2i base --aspect 3:4` or `1:1`
- Derivative tip: Want "character turnaround view" → add "front/side/back three-view arrangement" to the subject dimension

#### Character consistency kit（角色一致性三件套 · 结构吸收自 awesome-gpt-image-2，MIT）

角色需要跨姿势/跨视角/跨衍生场景保持可辨识时，三件套配合使用：

**1 · 身份锚点前置** —— 先锁脸型/发型/服装识别点，再写任何变形/风格化/玩具化。
模型对靠前的身份描述权重更高；先写风格化会把它当成主要约束，角色随之漂移：

```
Identity anchors (never change): round face, short black bob with straight bangs,
copper-framed round glasses, freckles on both cheeks, dark brown vest with brass buttons.
Stylization (may vary): 3D designer-toy rendering, chibi proportions, glossy vinyl material.
```

**2 · 拆解五官替代笼统词** —— "a beautiful girl"锚定不了任何东西，每个笼统词都换成可核对的具体部位：

| 笼统词 ❌ | 拆解后 ✅ |
|-----------|-----------|
| beautiful eyes | large almond eyes, dark brown iris, slight upward tilt at the outer corners |
| cute face | round face, small pointed chin, button nose with faint freckles |
| elegant dress | high-collar A-line navy dress, three-quarter sleeves, pearl buttons down the front |

**3 · 动作分解参考表** —— 多姿势表/衍生系列用：4×4 网格 16 面板，左上角编号 1-16，每格一个动作、3-4 行指令。
**「同一角色/服装/比例」声明必须写在动作列表之前**——长动作序列会导致脸/服装漂移，约束必须先被读到：

```
A 4x4 character action reference sheet of [identity anchors], 16 panels numbered
1-16 in each panel's top-left corner.
The same character, same outfit, same proportions in every panel.
Panel 1: standing and waving. Panel 2: reading a book. ... Panel 16: sleeping curled up.
```

### § Product · Product image / Derivative / Merch visual

**One question at a time to clarify priority**: Purpose (e-commerce hero image / lifestyle scene / merch poster) → Tone (premium / fresh / Chinese style) → Background (solid color / scene / gradient).

**Template formula**:

```
[Product subject with material/color/state], [standing display/in use] at [background].
Centered composition, [shot size]. [Softbox sidelight / natural light], emphasizing [bottle/material] light and shadow.
[E-commerce product photography / lifestyle] style, [tone], high detail, [material texture].
```

**Complete example**: "create a product image for this perfume" →

> A frosted glass perfume bottle with a gold cap, standing upright on a light gray gradient seamless background. Centered composition, half-body close-up. Softbox sidelight emphasizing the frosted bottle texture and golden light and shadow. E-commerce product photography style, premium tone, high detail, clear glass and metal textures.

- Recommended: `t2i base --aspect 4:3` or `1:1`
- Derivative tip: Want "lifestyle scene image" → change background dimension to "wooden tabletop, scattered citrus and mint leaves, natural light from window"

---

## Negative Prompts (`--negative-instruction`)

CFG exclusion items. General template:

```
blurry, low quality, deformed, extra fingers, perspective errors, watermark, text, signature, overexposed, JPEG artifacts
```

Add by scenario:

- Portrait: malformed hands, asymmetric eyes, misaligned teeth
- Landscape: jarring elements, artificial feel, oversaturation
- Product: background clutter, excessive reflections

## Variant Syntax (`{a|b|c}` / `{_词库_}`) — batch with intended differences

`--count > 1` 时同一 instruction 复制 N 张 = N 张同质图。要刻意差异，在 instruction 里写变体语法（agnes/kolors，每份渲染一个**非重复**变体，组合不足时告警过采样）：

```
一只{橘色|黑色|白色}猫，{_lighting_}，电影感
python3 scripts/agnes.py t2i -i "..." --count 6     # 6 份各不相同的猫
```

- `{a|b|c}`：花括号枚举，一个取值位置；`{_lighting_}`：引用 [`wordbanks/lighting.txt`](wordbanks/lighting.txt) 词库（每行一个词，自建词库往 `references/wordbanks/` 放）
- 无变体语法时行为不变（N 份原样）；普通 `{花括号}`（无 `|`）不是语法，原样保留
- 云端出图不可复现（agnes/kolors 无 seed）；需要锚定复现的批量调参走 boogu `--seed` + `--sweep`

---

## JSON Structured Prompt Block (advanced · layout-precise needs)

The 7-dimension formula is prose; when the requirement needs **precise layout / multi-region control** (posters, UI mockups, infographics), a JSON block is more controllable. All providers accept arbitrary instruction text — fill in the skeleton and pass the whole thing as `--instruction` (single-line or with line breaks, no script changes needed):

```json
{
  "type": "poster",
  "platform": "A2 print portrait",
  "layout": {
    "header": { "content": "event title, max two lines", "position": "top-center" },
    "main":   { "content": "hero illustration of the subject", "position": "center", "size": "60% height" },
    "footer": { "content": "date + venue line, QR placeholder bottom-left", "position": "bottom" }
  },
  "style": "minimal flat, brand color #1A73E8 with neutral grays, generous whitespace",
  "constraints": ["no photographic faces", "no real contact info", "title must stay within two lines"],
  "quality": "high detail, professional typography, clean vector look"
}
```

Fill rules: `type/platform` 锚定用途与画幅 → `layout` 每个区域写清 content/position/size → `style` 一句话风格核（可带色板）→ `constraints` 列硬性禁令 → `quality` 收尾。**适用边界**：简单需求用 7 维公式更自然（JSON 是给版式类需求的，不是默认格式）。

> **分工边界（垂直场景模板）**：本仓库不内嵌 UI 截图/信息图/海报等垂直模板库——已由姊妹 skill `gpt-image-2-style-library` 负责（模板类别→风格标签→场景标签的选型路由，含双语 Guidance 与上游出处锚点）。分工：**style-library 管"选哪个模板/风格"，wudaozi 管"生成执行"（provider 路由 + 脚本）**。未安装该 skill 的环境，用上面的 JSON 骨架自行描述版式即可，不要双头维护两套模板。

---

## Checklist (Must review before generation)

- [ ] Are all 7 dimensions complete? Which dimensions used defaults, and do they need user confirmation?
- [ ] Are users' specified hard constraints (specific color, composition, person) included?
- [ ] Is the intended medium consistent (photography ≠ painting ≠ 3D)?
- [ ] Is the length between 30-400 characters? (Too short = insufficient info, too long = model diverges; hard limit enforced by boogu.py)
- [ ] Are negative prompts filled with general items?

---

## Video Generation (video) — Dynamic, not static

> Video prompt mindset **differs from image generation**: image generation describes "a single moment", video describes "evolution over time". The core is "subject moves + camera moves + what stays stable". Works with agnes-video-v2.0.

### Core Formula (text-to-video)

```
[Subject] + [Action] + [Scene] + [Camera movement] + [Lighting] + [Style]
```

Example: "A young astronaut walking across a red desert planet, dust blowing in the wind, slow cinematic tracking shot, dramatic sunset lighting, realistic sci-fi style"

### Motion Description Tips (Soul of video)

The most common video failure is "things that should move don't, things that shouldn't move do". **Explicitly declare what moves and what stays stable**:

```
[Moving parts: subject action + environmental dynamics] + while keeping [stable parts: identity/appearance/composition]
```

Example: "Animate the character with subtle breathing motion, hair moving gently in the wind, background lights flickering softly, **while keeping the face and outfit consistent**"

### By Mode

| Mode | Prompt focus | Example |
|------|-------------|---------|
| t2vid text-to-video | All 6 dimensions, emphasize camera movement + time evolution | "Cat walking on beach, waves gently lapping, slow cinematic push-in, golden sunset warm light, cinematic realism" |
| ti2vid image-to-video | Describe **how the single image comes alive**, declare what stays consistent | "The woman slowly turns around and looks back at the camera, natural facial expression, cinematic camera movement" |
| multi multi-image video | Describe **relationships between images** and scene transitions | "Use the first image as the starting scene and the second image as the target scene. Create a smooth transformation" |
| keyframes keyframe | Describe **inter-frame transitions**, maintain identity/perspective consistency | "Create a smooth transition from the first keyframe to the second, maintaining character identity and consistent camera angle" |

> The four modes correspond to `video.py`'s `t2vid`/`ti2vid`/`multi`/`keyframes`: multi = multi-image fusion, keyframes = keyframe transition, both use `--images URL1 URL2` (at least 2 public images). Both `--images` only accept **public URLs** (video generation does not support base64).
>
> **Cross-frame identity consistency**: multi/keyframes suffer from the same drift problem — put the identity anchors from § IP (identity anchors come FIRST) at the start of the instruction, and for multi-shot planning (subject registry / atmosphere lock / inter-frame motion) use [`video-prompt-guide.md`](video-prompt-guide.md) § Multi-Shot Planner.

### Video Checklist

- [ ] Is there a clear camera movement (push-in/pull-out/pan/orbit/static)?
- [ ] Did you declare "what moves + what stays stable" (to avoid subject drift)?
- [ ] Is the duration matched to content (3s test composition / 5s default / 10s narrative / 18s long take)?
- [ ] Did you test with short duration first, then extend when satisfied (video generation is slow and expensive)?

---

## Image Understanding (vision) — Role + Task + Output format

> Understanding/OCR prompt mindset **differs from generation**: instead of describing a scene, it **gives the model a role + clear task + specified output format**. Works with both agnes-2.0-flash and DeepSeek-OCR-2.

### Core Formula

```
[Role] + [Task] + [Context] + [Requirements] + [Output format]
```

Example: "You are an image analysis assistant. Analyze the provided image, summarize the key information, identify potential issues, and return the result in a structured table."

### Five-Element Quick Reference

| Element | Purpose | Example |
|---------|---------|---------|
| Role | Sets expert perspective, affects analysis depth | "You are a senior UI designer" / "You are an OCR expert" |
| Task | Specifies what to do | "Analyze UI issues in this screenshot" / "Recognize text in the image and output verbatim" |
| Context | Provides background, avoids vague responses | "This is a page where users report lag" / "This is a middle school math problem" |
| Requirements | Constrains focus areas | "Focus on button clickable areas" / "Preserve original formula symbols" |
| Output format | Specifies structured form | "Output in markdown table" / "Give solution step by step" / "JSON format" |

### Three Complete Examples

**Example A · UI Review**:
> You are a senior UI designer. Analyze this app screenshot, identify main UI elements, point out potential usability issues, and provide improvement suggestions. Focus on button clickable areas and visual hierarchy. Output in markdown table: Element | Issue | Suggestion.

**Example B · OCR Problem Solving**:
> You are an OCR and math problem solving expert. Recognize the math problem in the image (preserve original formula symbols), provide complete solution steps. This is a middle school geometry problem. Output format: Original problem → Given conditions → Find → Step-by-step solution → Answer.

**Example C · Content Recognition**:
> You are an image analysis assistant. Describe the subject, scene, atmosphere, and possible shooting intent of this image. Output in three-part format: Subject description / Scene atmosphere / Shooting intent speculation.

### ⚠️ Image Input Constraints (Avoid silent failure)

- **URLs must be publicly accessible**: URLs requiring login/authentication/hotlink protection cannot be read by models (usually no error, just returns "unable to recognize" or guessed content)
- **Local images use base64**: vision.py automatically converts to data URI, bypassing public access restrictions (both agnes/aiping accept data URI in practice)
- **Standard formats**: JPG/JPEG/PNG/WebP; for screenshots/UI images, it's recommended to add text description in the prompt to specify focus areas
- **Provider selection**: OCR/formulas/problem solving → aiping DeepSeek-OCR-2; general descriptions/UI analysis → agnes-2.0-flash

### DeepSeek-OCR-2 官方 prompt（模型只认两条主提示）

来源：deepseek-ai/DeepSeek-OCR-2 README（Main Prompts 仅两条）。经 OpenAI 兼容接口调用时 `<image>` 占位由 image_url 部分承担，文本部分写法：

| 用途 | 文本部分（-q 参数） |
|------|---------------------|
| 通用识别/自由 OCR | `<image>\nFree OCR.` |
| 版面级文档转 markdown（带 grounding 坐标） | `<image>\n<|grounding|>Convert the document to markdown.` |

- grounding 模式输出含 `<|ref|>标签<|det|>[[坐标]]|>` 结构标记，vision.py 默认剥离（`--raw` 保留原文）；坐标为 999 归一化值
- 解码参数已对齐官方参考实现：temperature=0 + max_tokens=8192（`finish_reason=length` 有截断告警）
- **多页文档**：vision 只吃单图——pdftoppm/PyMuPDF 拆页 → 逐页 vision.py → 以 `<--- Page Split --->` 拼接（agent 编排，SKILL.md § 4D）
- **网关透传已实测**（2026-10-02，aiping）：`temperature` 真实生效（0 两次输出完全一致；5.0 高温乱码，网关不做上限校验）；`<image>\nFree OCR.` 经 chat/completions 直接可用；`finish_reason` 正常返回（stop/length 均观察到）

### Understanding Checklist

- [ ] Did you provide a role (affects analysis depth)?
- [ ] Is the task specific and answerable (avoid vague instructions like "describe this")?
- [ ] Did you specify the output format (table/steps/JSON/three-part)?
- [ ] Did you avoid private URLs for image input (local uses base64, remote confirmed publicly accessible)?
- [ ] OCR/文档转写任务用的是官方 prompt 措辞（而非自拟描述）？
