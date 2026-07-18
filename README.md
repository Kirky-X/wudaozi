# Wudaozi — Multi-capability Media Generation Skill (Image Generation · Image Understanding · Video)

[![GitHub Release](https://img.shields.io/github/v/release/Kirky-X/wudaozi?style=flat-square)](https://github.com/Kirky-X/wudaozi/releases) [![GitHub License](https://img.shields.io/github/license/Kirky-X/wudaozi?style=flat-square)](LICENSE)

wudaozi is a multi-capability media generation skill for AI agents that transforms users' vague requirements into executable commands: **Select capability → Select provider → Structured prompt → Run script**.

| Capability | Provider (script) | Key Environment Variables |
|------------|-------------------|---------------------------|
| Text-to-image t2i | **agnes** cloud · **kolors** cloud · **boogu** local | `AGNES_API_KEY` / `AIPING_API_KEY` / — |
| Image-to-image ti2i | **agnes** cloud · **boogu** local (⚠️ kolors not supported) | `AGNES_API_KEY` / — |
| Image understanding | **agnes** (agnes-2.0-flash) · **aiping** (DeepSeek-OCR-2) | `AGNES_API_KEY` / `AIPING_API_KEY` |
| Video generation | **agnes** (agnes-video-v2.0: t2vid/ti2vid/multi/keyframes async polling) | `AGNES_API_KEY` |

All cloud providers report errors explicitly without automatic fallback (to avoid confusing users with style/quality jumps). For complete routing table and flow documentation, see [SKILL.md](SKILL.md).

## Installation

### Method 1: Install via `skills` package (Recommended)

Requires [Node.js](https://nodejs.org/) 18+ and `skills` npm package (v1.5.12+). `skills` is the CLI for open agent skills ecosystem, supporting 68+ agents (Claude Code / Trae / Cursor / Codex / OpenCode etc.).

```bash
# Install to Claude Code
npx skills add Kirky-X/wudaozi --agent claude-code -y

# Install to Trae
npx skills add Kirky-X/wudaozi --agent trae -y

# List all discoverable skills in repository (without installing)
npx skills add https://github.com/Kirky-X/wudaozi.git --list
```

> When `npx skills add` fails, you can manually download `wudaozi.skill` (zip format) from [Releases](https://github.com/Kirky-X/wudaozi/releases), extract it, and copy `SKILL.md` + `references/` + `scripts/` to the agent skills directory.

### Method 2: Traditional git clone

```bash
git clone https://github.com/Kirky-X/wudaozi.git
# Copy SKILL.md + references/ + scripts/ to agent skills directory
#   Claude Code:  ~/.claude/skills/wudaozi/
#   Trae:         ~/.trae-cn/skills/wudaozi/
```

### Configure API keys (required for cloud providers)

Export the corresponding environment variables based on the provider you want to use (keys are not stored in code or git, only as local environment variables):

```bash
export AGNES_API_KEY=agn-xxxxxxxx      # agnes image generation/understanding/video, get from agnes-ai.com console
export AIPING_API_KEY=QC-xxxxxxxx      # kolors text-to-image / DeepSeek-OCR-2 image understanding, get from aiping.cn

# Verify (5 scripts self-check, no network calls)
python3 scripts/agnes.py  __selfcheck__
python3 scripts/kolors.py __selfcheck__
python3 scripts/vision.py __selfcheck__
python3 scripts/video.py  __selfcheck__
```

When no keys are configured, image generation can use boogu locally (requires GPU); cloud providers are independent of each other without automatic fallback.

## Quick Start

### Text-to-image · agnes cloud (no GPU required)

```bash
# Output to $PWD/agnes-output/
AGNES_API_KEY=agn-xxx python3 scripts/agnes.py t2i -i "An orange cat under moonlight, cinematic, high detail"
AGNES_API_KEY=agn-xxx python3 scripts/agnes.py t2i -i "..." --aspect 9:16   # Vertical wallpaper
```

### Text-to-image · kolors cloud (alternative when agnes is rate-limited, ⚠️ t2i only)

```bash
AIPING_API_KEY=QC-xxx python3 scripts/kolors.py t2i -i "..." --aspect 16:9
```

### Text-to-image/Image-to-image · boogu local (requires CUDA)

```bash
python3 scripts/boogu.py __selfcheck__                                    # Self-check (no GPU dependency)
python3 scripts/boogu.py t2i -i "..."                                     # Text-to-image base+bf16+1:1
python3 scripts/boogu.py t2i -i "..." --turbo --aspect 9:16               # Turbo 4-step, ~10x faster
python3 scripts/boogu.py ti2i -i "Change background to beach" --input photo.jpg        # Image-to-image
python3 scripts/boogu.py t2i -i "..." --dry-run                           # Debug (view command without GPU)
```

### Image Understanding (VLM)

```bash
# agnes general description (local images automatically converted to base64, agnes accepts data URI)
AGNES_API_KEY=agn-xxx python3 scripts/vision.py agnes --image photo.jpg -q "What's in this image"

# aiping DeepSeek-OCR-2 OCR/problem solving
AIPING_API_KEY=QC-xxx python3 scripts/vision.py aiping --image math.png -q "How to solve this problem?"

# Save result to txt (default outputs to stdout for piping)
AGNES_API_KEY=agn-xxx python3 scripts/vision.py agnes --image x.jpg -q "..." --output result.txt
```

### Video Generation (async polling)

```bash
# Text-to-video 5s 16:9 (output to $PWD/video-output/)
AGNES_API_KEY=agn-xxx python3 scripts/video.py t2vid -i "Cat walking on beach, cinematic, warm light"

# 3s short video for composition testing
AGNES_API_KEY=agn-xxx python3 scripts/video.py t2vid -i "..." --duration 3s

# Image-to-video (first frame image must be public URL, base64 not supported)
AGNES_API_KEY=agn-xxx python3 scripts/video.py ti2vid -i "Slow camera push-in" --image https://x/a.png

# Multi-image fusion (multi) / Keyframe transition (keyframes): ≥2 public images
AGNES_API_KEY=agn-xxx python3 scripts/video.py multi -i "Transform from scene A to scene B" \
    --images https://x/a.png https://x/b.png
AGNES_API_KEY=agn-xxx python3 scripts/video.py keyframes -i "Maintain character consistency, push-in perspective" \
    --images https://x/a.png https://x/b.png
```

## boogu Model Matrix (2×2×2 = 8 configurations)

| Mode | turbo | Quantization | Model |
|------|-------|--------------|-------|
| t2i | base | bf16 | `Boogu-Image-0.1-Base` |
| t2i | base | fp8 | `Boogu-Image-0.1-Base-fp8` |
| t2i | turbo | bf16 | `Boogu-Image-0.1-Turbo` |
| t2i | turbo | fp8 | `Boogu-Image-0.1-Turbo-fp8` |
| ti2i | base | bf16 | `Boogu-Image-0.1-Edit` |
| ti2i | base | fp8 | `Boogu-Image-0.1-Edit-fp8` |
| ti2i | turbo | bf16 | `Boogu-Image-0.1-Edit-Turbo` |
| ti2i | turbo | fp8 | `Boogu-Image-0.1-Edit-Turbo-fp8` |

- **t2i / ti2i**: Text-to-image / Image-to-image (editing)
- **base / turbo**: 50-step CFG high quality / 4-step DMD fast
- **bf16 / fp8**: Non-quantized / Quantized (~50% VRAM savings)

Scripts automatically select model and official entry script based on `(mode, turbo, quantized)`, and fill corresponding default parameters.

## Structured Prompts

Requirements are usually incomplete. Structure by capability dimensions (see [`references/prompt-template.md`](references/prompt-template.md) for details):

| Capability | Structure |
|------------|-----------|
| Text-to-image | Subject → Action → Background → Composition → Lighting → Style → Quality (**7 dimensions**) |
| Image-to-image | Change requirements → New style → Add/remove elements → **Preserved elements** (change + preserve) |
| Video | Subject → Action → Scene → Camera movement → Lighting → Style (**6 dimensions** + motion description) |
| Image understanding | Character → Task → Context → Requirements → Output format (**5-segment**) |

## Key Constraints

1. **Capability boundary**: This skill only handles generation and understanding. Video/audio editing, 3D models, PS-like fine retouching (matting/color grading/compositing) are out of scope.
2. **kolors t2i only**: kolors hardware constraints only support text-to-image, **not image-to-image** (CLI directly rejects ti2i). For image-to-image, use agnes/boogu.
3. **Video num_frames must be 8n+1** (81/121/241/441), ≤441; frame_rate 1-60. Entry validation rejects invalid values; use `--duration` presets for automatic compliance.
4. **Video ti2vid `--image` / multi·keyframes `--images` only accept public URLs** (explicitly documented, base64 not supported); upload local images to image hosting/OSS first. multi/keyframes require ≥2 images (single image uses ti2vid).
5. **boogu GPU required**: boogu actual image generation requires CUDA. GPU-less environments can only use `--dry-run` or `--device cpu` (very slow); for actual generation, use agnes/kolors.
6. **boogu model local availability**: Local machine has `Base` + `Turbo` downloaded (T2I non-quantized). The other 6 configurations require user download to `~/software/Boogu-Image/models/`; scripts detect missing models and report errors.
7. **Resolution**: boogu models natively support max 2K (2048), all widths/heights must be 16-aligned (scripts handle automatically). agnes/kolors are cloud black boxes with unknown size lists; use `--aspect` presets when encountering HTTP 400 errors.
8. **No fallback on failure**: All cloud providers report errors explicitly and exit, letting users decide to retry or switch providers.

## Default Parameters (boogu image generation)

| Dimension | base | turbo |
|-----------|------|-------|
| Steps | 50 | 4 |
| text guidance | 4.0 | 1.0 |
| image guidance (ti2i) | 1.0 | 1.0 |
| dmd_conditioning_sigma | — | t2i=0.001 / ti2i=0.0 |
| CFG | Enabled | Disabled (DMD student inference) |

Video duration presets (num_frames, frame_rate, all 8n+1): `3s`=(81,24) · `5s`=(121,24) · `10s`=(241,24) · `18s`=(441,24).
Video resolution presets (W,H): `16:9`=(1152,768) · `9:16`=(768,1152) · `1:1`=(960,960) · `4:3`=(1024,768) · `3:4`=(768,1024).

## File Structure

```
wudaozi/
├── SKILL.md                       # Entry: capability×provider matrix + routing + flow
├── skill.json                     # Skill metadata (name/version/tag, carried by .skill package)
├── scripts/
│   ├── agnes.py                   # agnes cloud image generation (t2i/ti2i, stdlib only)
│   ├── kolors.py                  # kolors cloud image generation (t2i only)
│   ├── boogu.py                   # boogu local image generation (2×2×2 matrix routing)
│   ├── vision.py                  # Image understanding (agnes-2.0-flash / DeepSeek-OCR-2)
│   ├── video.py                   # Video generation (agnes-video-v2.0 async polling)
│   └── test_*.py                  # 5 script unit tests (mock network layer, no real API/model calls)
└── references/
    └── prompt-template.md         # Structured prompt 7-dimension template + examples (shared for image generation)
```

## License

MIT