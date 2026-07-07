# wudaozi（吴道子）

Boogu-Image 文生图 / 图生图 Agent Skill。把模糊图片需求结构化为 7 维 prompt，按场景从 2×2×2 模型矩阵选模型，自动管理种子、宽高比、输出路径。

命名取自唐代画圣吴道子。

## 文件结构

```
wudaozi/
├── SKILL.md                       # 入口路由 + 模型矩阵决策表
├── scripts/
│   └── boogu.py                   # 核心包装：矩阵路由 + 默认值 + 种子 + 输出路径 + 资源探测
├── references/
│   └── prompt-template.md         # 结构化 prompt 7 维度模板 + 案例
└── README.md                      # 本文件
```

## 快速开始

```bash
# 1. 自检（不依赖 GPU）
python3 scripts/boogu.py __selfcheck__

# 2. 文生图（默认 base + bf16 + 1:1，自动种子，输出到 $PWD/boogu-output/）
python3 scripts/boogu.py t2i -i "一只在月光下的橘猫，电影感，高细节"

# 3. turbo + 竖屏（4 步快约 10×）
python3 scripts/boogu.py t2i -i "..." --turbo --aspect 9:16

# 4. 图生图（编辑参考图）
python3 scripts/boogu.py ti2i -i "把背景换成沙滩" --input photo.jpg

# 5. 调试（无 GPU 时只看命令）
python3 scripts/boogu.py t2i -i "..." --dry-run
```

## 模型矩阵（2×2×2 = 8 组）

| 模式 | turbo | 量化 | 模型                             |
| ---- | ----- | ---- | -------------------------------- |
| t2i  | base  | bf16 | `Boogu-Image-0.1-Base`           |
| t2i  | base  | fp8  | `Boogu-Image-0.1-Base-fp8`       |
| t2i  | turbo | bf16 | `Boogu-Image-0.1-Turbo`          |
| t2i  | turbo | fp8  | `Boogu-Image-0.1-Turbo-fp8`      |
| ti2i | base  | bf16 | `Boogu-Image-0.1-Edit`           |
| ti2i | base  | fp8  | `Boogu-Image-0.1-Edit-fp8`       |
| ti2i | turbo | bf16 | `Boogu-Image-0.1-Edit-Turbo`     |
| ti2i | turbo | fp8  | `Boogu-Image-0.1-Edit-Turbo-fp8` |

- **t2i / ti2i**：文生图 / 图生图（编辑）
- **base / turbo**：50 步 CFG 高质量 / 4 步 DMD 快速
- **bf16 / fp8**：非量化 / 量化（省约 50% 显存）

脚本会按 `(mode, turbo, quantized)` 自动选模型与官方入口脚本，并填充对应默认参数。

## 关键约束（务必知悉）

1. **GPU 必需**：真出图需 CUDA。无 GPU 环境只能 `--dry-run` 或 `--device cpu`（极慢）。
2. **模型本地可用性**：本机已下载 `Base` + `Turbo`（T2I 非量化）。其余 6 组需用户下载到 `~/software/Boogu-Image/models/`；脚本会探测缺失并报错。
3. **分辨率**：模型原生最大 2K（2048），所有宽高必须 16 对齐（脚本自动处理）。
4. **ti2i 单图编辑**：模型聚焦"一张参考图"的编辑，非多图融合。

## 默认参数

| 维度                   | base | turbo                |
| ---------------------- | ---- | -------------------- |
| 步数                   | 50   | 4                    |
| text guidance          | 4.0  | 1.0                  |
| image guidance（ti2i） | 1.0  | 1.0                  |
| dmd_conditioning_sigma | —    | t2i=0.001 / ti2i=0.0 |
| CFG                    | 启用 | 关闭（DMD 学生推理） |

## 结构化 Prompt

用户需求通常不完整。SKILL.md 强制把需求拆成 **7 维度**补全后再生成（详见 [`references/prompt-template.md`](references/prompt-template.md)）：

主体 → 动作/神态 → 背景/环境 → 构图/视角 → 光线 → 风格/媒介 → 画质

## 特殊场景（logo / IP / 产品衍生图）

三类 t2i 子任务，**走同一 Boogu-Image t2i 后端，仅 prompt 模板不同**（不绑定任何外部 API）。模板见 [`references/prompt-template.md`](references/prompt-template.md) § logo / § IP / § product。

> ⚠️ Boogu-Image 出的是"插画感 logo/角色"，非矢量设计稿。需精确矢量 logo → 用专门设计工具。

## 许可

MIT
