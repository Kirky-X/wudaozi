# EVAL — stable-diffusion.cpp 引擎评估:Boogu 本地轴 sd-cli 替换/并存可行性

> 调研建议#17(架构级长期项)的实机评估。**pin 版本:`3f8527a`(2026-09-27,master-929,ggml 子模块 `89c4413`)**——上游自述 API 常变,本报告全部数字与结论仅对该 pin 负责。
> 评估日期:2026-10-02。评估环境:WSL2 + RTX 5080(16303 MiB)、CUDA 12.8(nvcc)、cmake 4.4.0、g++ 13.3、`-j12`。

## TL;DR

1. **引擎在本机可构建、可运行**:CUDA backend(native arch 编译)构建成功,`sd-cli` 产出正常。
2. **Boogu-Image 一级支持已验证到实机**:fp8_scaled 权重(Comfy-Org 公开)+ Qwen3-VL-8B Q4_K_M 文本编码器 + FLUX VAE,在本机 16GB 卡上实测出图成功——**10B 模型 @1024²/50 步 183.7s,峰值显存 13.8GB**,质量目检正常。
3. **架构红利全部核实到源码**:`--rng` 显式语义(cuda=webui/cpu=comfyui)、`--max-vram` 分段执行+预取、`--vae-tiling`(解码缓冲 6.66GB→416MB)、`-M vid_gen` 本地视频(Wan 全系)、ADetailer 局部重绘、Boogu 权重自动识别(`VERSION_BOOGU_IMAGE`)。
4. **决策待定**(替换 vs 并存 boogu/diffusers,需用户拍板):本评估只回答"可行性、成本、差距",不代决策。详见 §4。

## 1. 构建

```bash
git clone --recursive https://github.com/leejet/stable-diffusion.cpp   # pin 3f8527a
cmake -B build -DSD_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=native
cmake --build build --config Release -j12    # 产物 build/bin/sd-cli
```

注意:`--depth 1` 克隆不带子模块,必须 `git submodule update --init --recursive`(ggml 缺失会在 configure 阶段报 `does not contain a CMakeLists.txt`)。

## 2. 实测基准(RTX 5080 / WSL2)

### 2.1 引擎烟测(sd-v1.5 Q4_0 合并 GGUF,1.49GB)

| 项 | 值 |
|----|----|
| 512×512 / 20 步生成 | **2.80s** |
| 峰值显存(含桌面基线) | ~4.0GB |

产物:`output/sd15_test.png`(有效 PNG,`file` 校验)。

### 2.2 Boogu-Image Base fp8_scaled(10B,核心问题)

权重(合计 ≈14.6GB,已落 `~/software/stable-diffusion.cpp/models/`):

| 文件 | 体积 | 来源 |
|------|------|------|
| `boogu_image_base_fp8_scaled.safetensors` | 9.61GB | [Comfy-Org/Boogu-Image](https://huggingface.co/Comfy-Org/Boogu-Image/tree/main/diffusion_models)(公开) |
| `Qwen3-VL-8B-Instruct-Q4_K_M.gguf` | 4.68GB | [unsloth](https://huggingface.co/unsloth/Qwen3-VL-8B-Instruct-GGUF)(公开) |
| `ae.safetensors`(FLUX VAE) | 0.32GB | 上游指向 FLUX.1-dev(**门控**),取自公开镜像 foxmail/flux_vae(335MB,244 tensors,头校验通过) |

命令:

```bash
sd-cli --diffusion-model models/boogu_image_base_fp8_scaled.safetensors \
    --llm models/Qwen3-VL-8B-Instruct-Q4_K_M.gguf \
    --vae models/ae.safetensors \
    -p "a lovely cat, highly detailed" \
    --seed 42 --steps 50 -W 1024 -H 1024 \
    --diffusion-fa --offload-to-cpu --rng cuda [--vae-tiling] \
    -o output/boogu_1024_50.png
```

| 配置 | rc | 生成耗时 | 峰值显存 | VAE 解码缓冲 | 产物 |
|------|----|---------|---------|--------------|------|
| fa + offload-to-cpu | 0 | **183.7s** | 13.8GB | 6.66GB(decode 1.04s) | 1024² PNG ✓ |
| + `--vae-tiling` | 0 | **181.4s** | 13.8GB | **416MB**(decode 1.67s) | 1024² PNG ✓ |

观察:

- **峰值显存出现在扩散阶段**(≈13.8GB,离 16GB 上限余量 ~2.4GB);`--vae-tiling` 不降该峰值,但把 VAE 解码阶段缓冲压缩 **16×**(6.66GB→416MB,代价 +0.6s)——16GB 卡跑 10B 模型建议默认开启,桌面占用显存时余量更安全。
- fp8(e4m3)+ per-tensor `weight_scale` 由 patch 后 ggml 原生加载(源码核实:`src/model_io/safetensors_io.cpp` dtype 表、`src/model_loader.cpp` scale 处理);**默认构建(非 `SD_USE_UPSTREAM_GGML`)即支持**。
- Boogu 权重自动识别:`src/model_loader.cpp:533` 返回 `VERSION_BOOGU_IMAGE`,无需手动指定架构。
- 本机无 boogu(diffusers)基线(该栈未部署):183.7s 是**绝对值**,不是相对对比;与官方 pipeline 的速度对比待 boogu 部署后补测。
- 质量目检:家猫特写,构图/毛发/光影正常,无明显伪影(`output/boogu_1024_50.png`)。

## 3. 特性对照(sd-cli pin 版本 vs boogu.py 现状)

| 维度 | boogu.py(diffusers 包装)现状 | sd-cli(pin 3f8527a) | 证据(pin 内) |
|------|------------------------------|----------------------|----------------|
| 量化档 | bf16 / fp8 两档(需本地模型目录) | f16/q8_0/q5/q4_0/q4_1 + GGUF 运行时转换;fp8 原生;int8_convrot(Edit 系);**nvfp4 不支持** | `docs/quantization_and_gguf.md`、`docs/int8_convrot.md`、源码 grep nvfp4 零命中 |
| 显存治理 | `--enable_sequential_cpu_offload` 单招 | `--offload-to-cpu` + `--max-vram` 分段执行/预取 + `--vae-tiling` | `docs/performance.md:112-142`,实测 §2.2 |
| RNG/复现 | seed 回显,跨环境无承诺 | `--rng std_default/cuda/cpu` 显式选择(cuda=webui 语义、cpu=comfyui 语义) | `examples/common/common.cpp` "--rng" |
| 产物元数据 | 文件名兜底(v0.3.2 起内嵌 PNG tEXt) | webui 兼容 `parameters` 内嵌 + 可不加载模型直读 | `examples/cli/image_metadata.cpp` |
| 局部重绘 | 无 | ADetailer(YOLOv8 检测 + 裁剪 inpaint) | `docs/adetailer.md` |
| 本地视频 | 无 | `-M vid_gen`(Wan 1.3B/14B,Q8_0 GGUF 实证) | `docs/wan.md:70-81` |
| ti2i 语义 | ref-role 子句(v0.3.2,指令层) | Edit 模型 + `--llm_vision`(mmproj)视觉编辑 | `docs/boogu_image.md`(未实测,§4) |

## 4. 决策待定项(需用户拍板;本评估不代决策)

1. **替换 vs 并存**:boogu.py 包装官方 diffusers 推理脚本(turbo/DMD sigma、B11/B12 硬约束语义);sd-cli 是第二条独立推理栈。并存成本低(boogu.py 已有路由层);替换需逐条重验 turbo 语义等价性。
2. **ti2i/Edit 未实测**(需 mmproj-F16 1.08GB + Edit 权重 9.61/10.59GB):t2i 已实机验证;Edit 是文档可信但未实测项。
3. **turbo 系(DMD 4 步)未实测**:bf16 turbo 权重 19.17GB,需 fp8/turbo 档下载后补测。
4. **采纳则 pin**:上游 API 自述常变;采用时 pin 到本报告版本或当时最新 release 并登记进 boogu-guide。
5. **下载成本**:fp8 全栈 ≈14.6GB(已在本机);bf16 系单权重 19.17GB。

## 5. 复现

构建见 §1;bench 命令见 §2.2;显存采样 `nvidia-smi --query-gpu=memory.used -lms 300` 全程记录,取峰值。全部产物在本机 `~/software/stable-diffusion.cpp/output/`。
