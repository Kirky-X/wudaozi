# Boogu Local Image Generation — Detailed Guide

> 从 SKILL.md 下沉的 boogu 专属细节：路由决策树、模型矩阵、默认值速查。agnes/kolors/vision/video 用户无需读本文件。

## Route Request — Decision Tree & Keywords

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


---

## Model Matrix (2×2×2)

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


---

## Defaults Quick Reference

| Dimension | base | turbo |
|-----------|------|-------|
| Steps | 50 | 4 |
| text guidance | 4.0 | 1.0 |
| image guidance (ti2i) | 1.0 | 1.0 |
| empty_instruction guidance (ti2i) | — | 0.0 |
| dmd_conditioning_sigma | — | t2i=0.001 / ti2i=0.0 |
| Use CFG | Yes | No (DMD student inference) |
| Relative speed | 1× | ~10× |

> **Seed 复现边界**：`--seed` 只保证**同机、同软件环境、同模型档位**下可复现——RNG 后端随 CUDA 版本/驱动/diffusers 版本变化，跨机器或跨环境同 seed 出图不承诺一致（diffusion 采样无跨环境数值稳定性承诺）。跨会话对比参数请同机同环境跑；本地引擎已是三家 provider 里唯一可完整复现的（云端 agnes/kolors 无 seed 概念）。产物 PNG 已内嵌全量生效参数（seed/steps/cfg/量化档，webui 兼容 `parameters` chunk），对比图互可追溯。

> **sd-cli 引擎路线实测**：stable-diffusion.cpp（pin 3f8527a）已在本机完成 Boogu-Image fp8 实机评估——10B @1024²/50 步 183.7s、峰值显存 13.8GB、`--rng` 显式 webui/comfyui 语义、`--max-vram`/`--vae-tiling` 显存治理、`-M vid_gen` 本地视频。可行性成立，**替换/并存决策待定**；完整数据与待定项见仓库根 [`EVAL-sd-cpp-2026-10-02.md`](../EVAL-sd-cpp-2026-10-02.md)。

**Parameter sweep**（本地专属）：`--sweep steps=20,30,50 text-guidance=4.0,3.5,3.0`——同 seed 一次扫一组参数（lockstep 等长配对，单值广播；**非笛卡尔积**），一命令出整组对比图，每轮带 `[SWEEP] run i/n` stderr 标记，单轮失败不中断其余轮次（退出码非 0）。

**Asset references**（本地专属）：`--ref <asset>` 引用 `assets.py` 角色/画风资产（style 资产默认 `--ref-role style`）；`--ref-role subject|style|composition` 显式声明参考图角色语义。官方脚本单图输入，多张仅取第一张（多参考图走 agnes）。

Video duration presets (num_frames, frame_rate, all 8n+1): `3s`=(81,24) · `5s`=(121,24) · `10s`=(241,24) · `18s`=(441,24).
Video resolution presets (W,H): `16:9`=(1152,768) · `9:16`=(768,1152) · `1:1`=(960,960) · `4:3`=(1024,768) · `3:4`=(768,1024).

---
