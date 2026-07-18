---
name: wudaozi
description: "Multi-capability media generation skill: text-to-image/image-to-image, image understanding, video generation. Triggers: text-to-image/image-to-image/generate image/AI drawing/output image/boogu/agnes/kolors/draw one/illustration/product image/IP character image/change background/edit image; image understanding/see image/recognize image/OCR/solve problem/DeepSeek-OCR; generate video/text-to-video/image-to-video/agnes-video. Image generation via agnes cloud/boogu local/kolors (text-to-image only), understanding via agnes-2.0-flash/aiping DeepSeek-OCR-2, video via agnes-video-v2.0. Routes by capability→provider, keys via environment variables."
license: MIT
---

# wudaozi — Multi-capability Media Generation Skill

Transforms users' vague media requirements into executable commands: **Select capability → Select provider → Structured prompt → Run script**.

## Capability × Provider Matrix

| Capability | Trigger Keywords | Provider (script) | Key Environment Variables |
|------------|------------------|-------------------|---------------------------|
| Text-to-image t2i | draw/generate/AI drawing/output image | **agnes** cloud · **boogu** local · **kolors** cloud (aiping) | `AGNES_API_KEY` / — / `AIPING_API_KEY` |
| Image-to-image ti2i | edit image/change background/add elements/edit this | **agnes** cloud · **boogu** local (⚠️ kolors **does not support** ti2i) | `AGNES_API_KEY` / — |
| Image understanding | see image/recognize image/what's in this image/solve problem/OCR | **agnes** (agnes-2.0-flash) · **aiping** (DeepSeek-OCR-2) | `AGNES_API_KEY` / `AIPING_API_KEY` |
| Video generation | generate video/text-to-video/image-to-video/multi-image/keyframes | **agnes** (agnes-video-v2.0: t2vid/ti2vid/multi/keyframes async polling) | `AGNES_API_KEY` |

> 🔴 **CHECKPOINT · Capability boundary**: This skill **only handles generation and understanding**. Video/audio editing, 3D models, PS-like fine retouching (matting/color grading/compositing) are **out of scope** — don't force these onto generation models.

---

## Provider Selection (Three image generation providers)

| Dimension | agnes cloud | kolors cloud (aiping) | boogu local |
|-----------|-------------|----------------------|-------------|
| Capability | t2i + ti2i | **t2i only** (no ti2i) | t2i + ti2i |
| Deployment | Set `AGNES_API_KEY` and ready | Set `AIPING_API_KEY` and ready | Requires GPU + local models + venv |
| Speed | Seconds per image | Seconds per image | base: minutes / turbo: seconds |
| VRAM | No requirement | No requirement | 16GB+ (fp8 can reduce to ~8GB) |
| Customization | size/prompt | size/prompt | turbo/fp8/seed/steps/cfg all available |
| Privacy | prompt/image uploaded to cloud | prompt uploaded to cloud | Fully local, never leaves machine |
| Failure handling | Explicit errors, no fallback | Explicit errors, no fallback | Explicit errors, no fallback |
| Best for | No GPU / quick generation | No GPU / alternative when agnes is rate-limited | Has GPU / privacy-sensitive / batch tuning |

**Default routing**: `AGNES_API_KEY` set → image generation via agnes, understanding via agnes, video via agnes; not set → ask user "configure key or use boogu locally". kolors serves as t2i alternative when agnes is rate-limited/unavailable, requires separate `AIPING_API_KEY` configuration.

> 🔴 **CHECKPOINT**: Local GPU blocked by OS (NVML blocked), boogu actual image generation must run on machine with CUDA (local can only use `--dry-run`). Without GPU, use agnes/kolors cloud for actual generation.

---

## Overall Flow

```mermaid
flowchart TD
    Req(["User requirement"]) --> Cap{"Select capability"}
    Cap -- "draw/output image/edit image" --> IMG["Image generation capability"]
    Cap -- "see image/recognize image/solve problem" --> VIS["Image understanding"]
    Cap -- "generate video" --> VID["Video generation"]
    IMG --> M{"Has reference image?"}
    M -- "Yes (edit/change/modify)" --> TI2I["ti2i image-to-image<br/>⚠️ kolors not supported"]
    M -- "No" --> T2I["t2i text-to-image"]
    TI2I --> ProvImg{"Provider?<br/>agnes / boogu"}
    T2I --> ProvImg2{"Provider?<br/>agnes / kolors / boogu"}
    ProvImg -- agnes --> A4["agnes.py"]
    ProvImg -- boogu --> B1["Step 1 routing → Step 3 matrix → boogu.py"]
    ProvImg2 -- agnes --> A4
    ProvImg2 -- kolors --> K4["kolors.py (t2i only)"]
    ProvImg2 -- boogu --> B1
    VIS --> ProvVis{"Provider?<br/>agnes / aiping"}
    ProvVis -- agnes --> V4["vision.py agnes"]
    ProvVis -- aiping --> V4B["vision.py aiping"]
    VID --> Vmode{"How many reference images?"}
    Vmode -- "0 images" --> T2V["t2vid text-to-video"]
    Vmode -- "1 image (URL)" --> TI2V["ti2vid image-to-video"]
    Vmode -- "≥2 images (URL)" --> Vmk{"Transition type?"}
    Vmk -- "Scene fusion" --> MLT["multi multi-image video"]
    Vmk -- "Inter-frame transition" --> KF["keyframes keyframe"]
    T2V --> VID4["video.py (async polling)"]
    TI2V --> VID4
    MLT --> VID4
    KF --> VID4
    A4 --> Out(["PNG"])
    K4 --> Out
    B1 --> Out
    V4 --> Txt(["Text (stdout/txt)"])
    V4B --> Txt
    VID4 --> Mp4(["MP4"])
```

All capabilities share **Step 2 · Structured prompt** (see below). When using boogu for image generation, additionally go through Step 1 (routing) and Step 3 (model matrix); other providers go directly to Step 4.

---

## Step 1 — Route Request (boogu only)

> agnes / kolors / vision / video skip this step (no turbo/fp8/seed/steps concepts).

Determined in order by **reference image → speed → VRAM**. Decision tree is preferred over table (expresses judgment priority):

```mermaid
flowchart TD
    Start(["User request"]) --> Q1{"Has reference image?<br/>'edit/change/modify/add elements'"}
    Q1 -- Yes --> TI2I["mode = ti2i<br/>image-to-image"]
    Q1 -- No --> T2I["mode = t2i<br/>text-to-image"]
    TI2I --> Q2{"Need fast iteration?<br/>'quick/sketch/iterate/batch'"}
    T2I --> Q2
    Q2 -- Yes --> TURBO["turbo<br/>4 steps · no CFG · ~10× faster"]
    Q2 -- No --> BASE["base<br/>50 steps · CFG 4.0 · high quality"]
    TURBO --> Q3{"VRAM constrained?<br/>OOM / ≤16G GPU"}
    BASE --> Q3
    Q3 -- Yes --> FP8["fp8 quantization<br/>~50% VRAM savings"]
    Q3 -- No --> BF16["bf16 non-quantized"]
    FP8 --> Final(["Proceed to Step 2"])
    BF16 --> Final
```

**Keyword quick reference** (natural language triggers, works with decision tree):

| User says... | mode | turbo | Quantization |
|-------------|------|-------|--------------|
| "draw/generate/AI drawing/output image" | t2i | No | No |
| "quick/sketch/try versions/iterate" | t2i | **Yes** | Depends on VRAM |
| "edit image/change background/add elements/edit this" | ti2i | No | No |
| "quick edit/batch editing" | ti2i | **Yes** | Depends on VRAM |
| "VRAM insufficient/OOM/16G GPU" | — | — | **Yes** |

**Default decision**: When not specified = `t2i + base + bf16 + 1:1 + auto random seed`.

> 🔴 **CHECKPOINT**: Before deviating from defaults (enabling turbo / fp8 / ti2i / custom dimensions), first align with user on the reason (e.g., "VRAM constrained, recommend fp8"), get confirmation, then proceed to Step 2.

---

## Step 2 — Construct Structured Prompt

### Image generation (shared by agnes/boogu/kolors)

Read [`references/prompt-template.md`](references/prompt-template.md), complete users' vague requirements by **7 dimensions**:

1. Subject → 2. Action/Expression → 3. Background/Environment → 4. Composition/Perspective → 5. Lighting → 6. Style/Medium → 7. Quality

#### Vague requirements → Ask one question at a time for clarification

When users' requirements have **missing key dimensions** (subject unclear / style undefined / purpose not stated), **don't throw 7 questions at once**, and **don't silently fill defaults**. Ask **one question at a time** by priority, giving 2-4 candidate options + a "custom" exit:

> User: "Make a logo"
> ❌ Asking all at once "What brand/industry/color/style/font..."
> ✅ First round only ask the most critical: _"What scenario is this logo for?"_ Give candidates: `Brand visual / App icon / Social avatar / Custom`
> After user selects → ask next dimension (style preference: minimalist/geometric/hand-drawn/wordmark)
> After 2-3 rounds when key dimensions are complete → proceed to 7-dimension completion below

**Priority queue** (sorted by missing impact): Subject > Style/Medium > Background > Composition > Lighting > Quality. The last three dimensions can safely use defaults without asking user.

#### Explicit confirmation (mandatory)

After all 7 dimensions are complete, **explicitly list the final result** to user (which dimensions used defaults, which dimensions are user's original intent/clarification answers), get confirmation, then assemble into `--instruction`.

> 🔴 **CHECKPOINT · 🛑 STOP**: List complete 7 dimensions → wait for user confirmation ("OK" / "change dimension X") → then proceed to Step 3/4. **Skipping confirmation to directly construct command is prohibited.**

Negative prompts use `--negative-instruction`: **not passing** uses built-in general template (recommended), passing **empty string** disables, passing **non-empty** overrides.

### Image understanding (vision)

Higher quality questions use **5-segment structure**: `[Role] + [Task] + [Context] + [Requirements] + [Output format]` (see `references/prompt-template.md` § Image Understanding). At minimum ensure **specific and answerable**, avoid vague instructions like "describe this". Give candidates by use case:

| Use Case | Example Question |
|----------|------------------|
| Content recognition | "What's in this image? List main objects and scenes" |
| OCR/Problem solving | "Recognize text in image and output verbatim" / "How to solve this problem? Give steps" |
| Detail description | "What are the clothing, expression, and actions of people in the image" |
| Comparative analysis | "What are the differences between this image and typical XX" |

> aiping `DeepSeek-OCR-2` excels at **OCR/formulas/problem solving**; agnes-2.0-flash is more balanced for **general descriptions**. Choose provider by use case.
>
> ⚠️ **Image URLs must be publicly accessible**: URLs requiring login/authentication/hotlink protection cannot be read by models (silent failure, no error, just guesses). Local images are automatically converted to base64 data URI by vision.py to bypass this limitation.

### Video generation (video)

Video prompt mindset **differs from image generation** — describes "evolution over time" rather than a single moment. Core formula: `[Subject] + [Action] + [Scene] + [Camera movement] + [Lighting] + [Style]` (see `references/prompt-template.md` § Video Generation). Add "camera movement + motion description":

- Camera: push-in/pull-out/pan/orbit/static
- **Motion description** (soul of video): Explicitly state "what moves + what stays stable" — "...hair moving gently in the wind, **while keeping the face and outfit consistent**", avoid subject drift
- Evolution: Timeline "first...then...finally..."
- Duration: 3s (test composition) / 5s (default) / 10s (full narrative) / 18s (long take, ≤441 frames)

> Video generation is **slow** (~1-3 minutes for 3s video), test with short duration first, extend when satisfied.

---

## Step 3 — Select Model (boogu only · 2×2×2 matrix)

> agnes / kolors / vision / video have no model matrix concept, skip this step; for ti2i, reference images are automatically converted to Data URI or passed through as public URLs by agnes.py in Step 4.

| Mode | turbo | Quantization | Model Directory | Entry Script | Key Parameters (auto-filled by script) |
|------|-------|--------------|-----------------|--------------|----------------------------------------|
| t2i | base | bf16 | `Boogu-Image-0.1-Base` | `inference.py` | steps=50, text_cfg=4.0 |
| t2i | base | fp8 | `Boogu-Image-0.1-Base-fp8` | `inference.py` | + `--use_fp8_weights` |
| t2i | turbo | bf16 | `Boogu-Image-0.1-Turbo` | `inference_turbo.py` | steps=4, cfg=1.0, dmd_sigma=0.001 |
| t2i | turbo | fp8 | `Boogu-Image-0.1-Turbo-fp8` | `inference_turbo.py` | Same as above + fp8 |
| ti2i | base | bf16 | `Boogu-Image-0.1-Edit` | `inference.py` | + image_cfg=1.0 |
| ti2i | base | fp8 | `Boogu-Image-0.1-Edit-fp8` | `inference.py` | Same as above + fp8 |
| ti2i | turbo | bf16 | `Boogu-Image-0.1-Edit-Turbo` | `inference_turbo.py` | dmd_sigma=0.0, empty_cfg=0.0 |
| ti2i | turbo | fp8 | `Boogu-Image-0.1-Edit-Turbo-fp8` | `inference_turbo.py` | Same as above + fp8 |

**Model availability** (scripts auto-detect and report errors):

- Locally downloaded: `Base`, `Turbo` (T2I non-quantized only)
- Requires user download: `Edit` series (image-to-image), all `-fp8` series
- User wants image-to-image or fp8 but no local model → **don't force run**, clearly inform "must download models/{name} first", or degrade to locally available combinations

---

## Step 4 — Call Scripts

### 4A · agnes cloud image generation (`scripts/agnes.py`)

```bash
# Text-to-image (default URL download + 1:1, output to $PWD/agnes-output/)
AGNES_API_KEY=agn-xxx python3 scripts/agnes.py t2i -i "<structured instruction>"

# Vertical phone wallpaper
AGNES_API_KEY=agn-xxx python3 scripts/agnes.py t2i -i "<instruction>" --aspect 9:16

# Image-to-image (local reference images auto-converted to base64, or pass public URL)
AGNES_API_KEY=agn-xxx python3 scripts/agnes.py ti2i -i "Change background to beach" --input photo.jpg

# No key / debug: only view curl, don't actually call
AGNES_API_KEY=agn-test python3 scripts/agnes.py t2i -i "<instruction>" --dry-run
```

agnes.py automatically: constructs `model/prompt/size(+reference image)` request → POST agnes endpoint → downloads URL or decodes base64 to PNG → truncates key to prevent leakage. Errors (401/429/400/timeout/no data in response) **report explicitly and exit, no fallback** — user decides to retry or switch provider.

Aspect ratio presets (same values as boogu): `1:1` · `3:4`/`4:3` · `2:3`/`3:2` · `9:16`/`16:9`. agnes does **not** do 16-alignment (cloud black box, unknown size list, use `--aspect` presets when encountering HTTP 400). Full CLI: `python3 scripts/agnes.py --help`.

### 4B · kolors cloud image generation (`scripts/kolors.py`, ⚠️ t2i only)

```bash
# Text-to-image (output to $PWD/kolors-output/)
AIPING_API_KEY=QC-xxx python3 scripts/kolors.py t2i -i "<structured instruction>"

# Custom size (image_size takes WxH directly)
AIPING_API_KEY=QC-xxx python3 scripts/kolors.py t2i -i "<instruction>" --image-size 1328x1328

# Use aspect ratio preset
AIPING_API_KEY=QC-xxx python3 scripts/kolors.py t2i -i "<instruction>" --aspect 9:16

# Debug
AIPING_API_KEY=QC-test python3 scripts/kolors.py t2i -i "<instruction>" --dry-run
```

> 🔴 **CHECKPOINT · kolors hard constraint**: kolors.py **only accepts t2i** (CLI `choices=["t2i"]`, passing ti2i directly rejected). User wants image-to-image → use agnes or boogu, **don't** attempt kolors. Size uses `--image-size WxH` or `--aspect` presets (`1:1`/`3:4`/`4:3`/`2:3`/`3:2`/`9:16`/`16:9`); if not passed, server provides default. Returns `data[0].url` for download, errors (401/429/400/timeout) report explicitly without fallback.

### 4C · boogu local image generation (`scripts/boogu.py`)

```bash
# Text-to-image (default base + bf16 + 1:1 + auto seed, output to $PWD/boogu-output/)
python3 scripts/boogu.py t2i -i "<structured instruction>"

# turbo + vertical + specified seed (reproducibility)
python3 scripts/boogu.py t2i -i "<instruction>" --turbo --aspect 9:16 --seed 42

# Image-to-image (edit reference image), fp8 saves VRAM
python3 scripts/boogu.py ti2i -i "Change background to beach" --input photo.jpg --quantized

# No GPU / debug: only view command, don't actually run
python3 scripts/boogu.py t2i -i "<instruction>" --dry-run

# Custom output directory
python3 scripts/boogu.py t2i -i "<instruction>" -o ./my-output/
```

Scripts automatically:

- Select official script and model by `(mode, turbo, quantized)` (deterministic lookup table)
- Fill turbo/base default parameter differences (steps, CFG, dmd_sigma)
- Generate random seed and echo when `--seed` not specified (for reproducibility)
- Output path defaults to `$PWD/boogu-output/`, filename includes mode+seed+size+timestamp to prevent overwriting
- Auto-calculate `max_input_image_pixels` and `max_input_image_side_length` by H×W (official recommended formula, ensures clarity)
- Detect venv/model/GPU, report errors explicitly with fix suggestions when missing

**Aspect ratio presets** (all 16-aligned, longest side ≤ 2048): `1:1`(1024²) · `3:4`/`4:3`(1024×1360) · `2:3`/`3:2`(1024×1536) · `9:16`/`16:9`(1024×1824). Can also use `--height/--width` for custom (scripts align down to 16).

**Key parameter overrides** (defaults usually suffice): `--steps` `--text-guidance` `--dmd-sigma` `--device` `--negative-instruction`. Full list: `python3 scripts/boogu.py --help`.

### 4D · Image Understanding (`scripts/vision.py`)

```bash
# agnes understands local image (auto-converted to base64; agnes accepts data URI in practice)
AGNES_API_KEY=agn-xxx python3 scripts/vision.py agnes --image photo.jpg -q "What's in this image"

# agnes understands public URL image
AGNES_API_KEY=agn-xxx python3 scripts/vision.py agnes --image https://example.com/a.jpg -q "Describe this image"

# aiping DeepSeek-OCR-2 problem solving/OCR
AIPING_API_KEY=QC-xxx python3 vision.py aiping --image math.png -q "How to solve this problem?"

# Save result to txt (default outputs to stdout for piping)
AGNES_API_KEY=agn-xxx python3 scripts/vision.py agnes --image x.jpg -q "..." --output result.txt
```

vision.py automatically: local path → base64 data URI, http(s) URL → pass through; constructs OpenAI-compatible chat/completions (content array: image_url + text) → calls corresponding provider → extracts content to stdout. Both providers accept base64 data URI in documentation/testing (agnes docs say only URL supported, but base64 works in practice). Errors (401/429/400/timeout) report explicitly without fallback.

### 4E · Video Generation (`scripts/video.py`, async polling)

```bash
# Text-to-video, 5s 16:9 (default)
AGNES_API_KEY=agn-xxx python3 scripts/video.py t2vid -i "Cat walking on beach, cinematic, warm light"

# 3s short video for composition testing + negative prompt
AGNES_API_KEY=agn-xxx python3 video.py t2vid -i "..." --duration 3s --aspect 16:9 \
    --negative-instruction "blurry, deformed"

# Image-to-video (first frame image must be public URL, base64 not supported)
AGNES_API_KEY=agn-xxx python3 video.py ti2vid -i "Slow camera push-in" --image https://x/a.png

# Multi-image fusion (multi): ≥2 public images, describe relationships/scene transitions between images
AGNES_API_KEY=agn-xxx python3 video.py multi -i "Smooth transition from scene A to scene B" \
    --images https://x/a.png https://x/b.png

# Keyframe transition (keyframes): ≥2 public images, describe inter-frame transitions, maintain identity/perspective consistency
AGNES_API_KEY=agn-xxx python3 video.py keyframes -i "Maintain character consistency, slow camera push-in" \
    --images https://x/a.png https://x/b.png

# Debug: only view create task curl
AGNES_API_KEY=agn-xxx python3 video.py t2vid -i "..." --dry-run
```

video.py async flow: POST `/v1/videos` to create task, get `video_id` → poll `GET /agnesapi?video_id=X` until `completed`/`failed`/timeout → download mp4 to `$PWD/video-output/`.

> 🔴 **CHECKPOINT · Video hard constraints**:
> - **num_frames must be 8n+1** (81/121/241/441), ≤441; frame_rate 1-60. Entry validation rejects to avoid server 400. Use `--duration` presets for automatic compliance.
> - **ti2vid `--image` / multi·keyframes `--images` only accept public http(s) URLs** (explicitly documented, video generation does not support base64) — local images must be uploaded to image hosting/OSS first. multi/keyframes require ≥2 URLs (single image uses ti2vid).
> - Video generation is slow, `--max-wait` defaults to 1200s (covers longest 18s video generation time); timeout prints `video_id` for manual `curl` query.

---

## Default Values Quick Reference (boogu image generation)

| Dimension | base | turbo |
|-----------|------|-------|
| Steps | 50 | 4 |
| text guidance | 4.0 | 1.0 |
| image guidance (ti2i) | 1.0 | 1.0 |
| empty_instruction guidance (ti2i) | — | 0.0 |
| dmd_conditioning_sigma | — | t2i=0.001 / ti2i=0.0 |
| Use CFG | Yes | No (DMD student inference) |
| Relative speed | 1× | ~10× |

Video duration presets (num_frames, frame_rate, all 8n+1): `3s`=(81,24) · `5s`=(121,24) · `10s`=(241,24) · `18s`=(441,24).
Video resolution presets (W,H): `16:9`=(1152,768) · `9:16`=(768,1152) · `1:1`=(960,960) · `4:3`=(1024,768) · `3:4`=(768,1024).

---

## Failure Modes and Fallback

> All cloud providers (agnes/kolors/vision/video) report errors explicitly and exit without automatic fallback on failure; user decides to retry or switch provider. Below table covers boogu local failure fixes.

| Trigger | First-line fix | Fallback |
|---------|----------------|----------|
| `[ERROR] Model not downloaded` | Prompt user to download corresponding model to `~/software/Boogu-Image/models/` | Degrade to locally available models (e.g., Edit missing → switch to t2i redraw) |
| `[WARN] GPU detection failed` | Add `--dry-run` to verify command; or `--device cpu` (very slow, debug only) | Guide to run on machine with CUDA |
| VRAM OOM | Add `--quantized` (fp8) | Reduce size: `--aspect 1:1` or smaller `--height/--width` |
| Blurry output | Check if H×W set too large but max_input too small (scripts auto-calculate by official formula) | Redo with base, or use higher resolution preset |
| ti2i edit "drifts" | Lower text_guidance, increase image_guidance | Use base instead of turbo (CFG more controllable) |
| Output doesn't match expectation | First adjust prompt (check 7 dimensions complete), then adjust seed/steps | Reproduce with same seed + single-dimension tuning |
| Video polling timeout | Increase `--max-wait`, or use printed `video_id` for manual `curl` query | Shorter duration (`--duration 3s`) to reduce generation time |
| Video file <10KB | Task abnormal completion, check prompt/seed, rerun | Change `--aspect` or `--duration` preset |

---

## Special Scenarios: Logo / IP Character / Product Derivatives

These three are **specialized subtasks of t2i**, using the same image generation backend (agnes/kolors/boogu all work), **only prompt templates differ**. Read corresponding sections in [`references/prompt-template.md`](references/prompt-template.md):

| User says... | Task Type | Template Section | Recommended Parameters |
|-------------|-----------|------------------|----------------------|
| "Make a logo / icon / brand visual" | Logo | prompt-template.md § logo | t2i, `--aspect 1:1`, clean background |
| "Make an IP / mascot / character" | IP character | prompt-template.md § IP | t2i, `--aspect 3:4` or `1:1`, 3D/trendy toy style |
| "Product image / derivative / merch visual" | Product derivative | prompt-template.md § product | t2i, `--aspect 4:3` or `1:1`, centered display |

> ⚠️ Image generation models are for **image generation**, not strong at logo/icon graphic design (precise geometry, vector text). Output is "illustration-style logo/character", **not usable vector design files**. For precise vector logos → use specialized design tools, don't force generation.

---

## Execution Anti-patterns (Don't do these)

- **Don't silently fill 7-dimension defaults to skip confirmation** — When subject/style/background missing, first use Step 2's "one question at a time" for clarification, confirm, then assemble instruction.
- **Don't run turbo on CPU** — 4-step DMD distillation diverges on CPU, must use base or switch to GPU.
- **Don't pass `--text-guidance != 1.0` or `--steps != 4` to turbo** — Script will reject/warn (B11/B12 hard constraints).
- **Don't use fp8 for high-fidelity ti2i editing** — Quantization loses details, use bf16 for editing tasks.
- **Don't pass only `--height` without `--width`** (or vice versa) — Script will reject (B1), single-dimension size change uses `--aspect`.
- **Don't add `--quantized` to non-fp8 models** (or vice versa) — Script will reject (B2, fp8 flag must match model directory).
- **Don't pass ti2i to kolors** — kolors hardware constraints only support t2i, CLI directly rejects; image-to-image uses agnes/boogu.
- **Don't pass local paths/base64 to ti2vid/multi/keyframes** — Video generation `--image`/`--images` only accept public URLs; upload local images first. multi/keyframes require ≥2 URLs.
- **Don't pass non-8n+1 num_frames to video** — Entry validation rejects; use `--duration` presets for automatic compliance.

---

## Don't Trigger This Skill

- User only wants to **find/view/filter existing images** (no generation, no understanding).
- User wants **audio/3D model** generation (this skill only does 2D images + video).
- User wants to **retouch/composite existing images** (PS-like operations, e.g., matting, color grading, compositing) → Use image processing tools, not generation models.
- User wants **video editing** (trim/merge/add subtitles to existing video) → This skill only **generates** video, doesn't edit.
- No local GPU and user unwilling/unable to run boogu on CUDA machine → boogu can only use `--dry-run`, **don't pretend to generate** (can use agnes/kolors cloud).

---

## Self-check

```bash
python3 scripts/agnes.py  __selfcheck__   # Image generation agnes: pure functions + key existence
python3 scripts/kolors.py __selfcheck__   # Image generation kolors: pure functions + image_size table + key existence
python3 scripts/boogu.py  __selfcheck__   # Image generation boogu: matrix lookup/16-alignment/resource detection
python3 scripts/vision.py __selfcheck__   # Image understanding: dual provider table + data URI + key existence
python3 scripts/video.py  __selfcheck__   # Video generation: 8n+1 rule + resolution/duration presets + key existence
python3 -m pytest scripts/               # Full unit tests (5 scripts, no real API/model calls)
```
