# Wudaozi (吴道子) —— Boogu-Image 出图技能

[![GitHub Release](https://img.shields.io/github/v/release/Kirky-X/wudaozi?style=flat-square)](https://github.com/Kirky-X/wudaozi/releases)
[![GitHub License](https://img.shields.io/github/license/Kirky-X/wudaozi?style=flat-square)](LICENSE)

wudaozi 是一个面向 AI agent 的文生图/图生图 skill，封装 `~/software/Boogu-Image`（8 组模型矩阵 + DMD turbo 范式 + fp8 量化）。把用户的模糊图片需求（"画一只猫"）变成一张能跑的命令：**结构化 prompt → 选模型 → 填参数 → 调脚本**。

模型选择、种子、宽高比、输出路径全部由 [`scripts/boogu.py`](scripts/boogu.py) 确定性处理，**不交给模型猜**。完整路由表与流程文档见 [SKILL.md](SKILL.md)。

## 安装

### 方式一：通过 `skills` 包安装（推荐）

需 [Node.js](https://nodejs.org/) 18+ 和 `skills` npm 包(v1.5.12+)。`skills` 是 open agent skills 生态的 CLI，支持 68+ agents(Claude Code / Trae / Cursor / Codex / OpenCode 等)。

```bash
# 安装到 Claude Code
npx skills add Kirky-X/wudaozi --agent claude-code -y

# 安装到 Trae
npx skills add Kirky-X/wudaozi --agent trae -y

# 列出仓库中可被发现的所有 skills（不安装）
npx skills add https://github.com/Kirky-X/wudaozi.git --list
```

### 方式二：传统 git clone

```bash
git clone https://github.com/Kirky-X/wudaozi.git
# 将 SKILL.md + references/ + scripts/ 复制到 agent skills 目录
#   Claude Code:  ~/.claude/skills/wudaozi/
#   Trae:         ~/.trae-cn/skills/wudaozi/
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

脚本按 `(mode, turbo, quantized)` 自动选模型与官方入口脚本，并填充对应默认参数。

## 结构化 Prompt

用户需求通常不完整。SKILL.md 强制把需求拆成 **7 维度**补全后再生成（详见 [`references/prompt-template.md`](references/prompt-template.md)）：

```
主体 → 动作/神态 → 背景/环境 → 构图/视角 → 光线 → 风格/媒介 → 画质
```

## 关键约束

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

## 文件结构

```
wudaozi/
├── SKILL.md                       # 入口路由 + 模型矩阵决策表
├── scripts/
│   └── boogu.py                   # 核心包装：矩阵路由 + 默认值 + 种子 + 输出路径 + 资源探测
└── references/
    └── prompt-template.md         # 结构化 prompt 7 维度模板 + 案例
```

## 许可证

MIT
