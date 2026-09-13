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

### Understanding Checklist

- [ ] Did you provide a role (affects analysis depth)?
- [ ] Is the task specific and answerable (avoid vague instructions like "describe this")?
- [ ] Did you specify the output format (table/steps/JSON/three-part)?
- [ ] Did you avoid private URLs for image input (local uses base64, remote confirmed publicly accessible)?
