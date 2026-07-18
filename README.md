# Wudaozi (吴道子) —— 多能力媒体生成技能（出图 · 图片理解 · 视频）

[![GitHub Release](https://img.shields.io/github/v/release/Kirky-X/wudaozi?style=flat-square)](https://github.com/Kirky-X/wudaozi/releases) [![GitHub License](https://img.shields.io/github/license/Kirky-X/wudaozi?style=flat-square)](LICENSE)

wudaozi 是一个面向 AI agent 的多能力媒体生成 skill，把用户的模糊需求变成一条能跑的命令：**选能力 → 选 provider → 结构化 prompt → 调脚本**。

| 能力         | provider（脚本）                                                | key 环境变量                          |
| ------------ | --------------------------------------------------------------- | ------------------------------------- |
| 文生图 t2i   | **agnes** 云端 · **kolors** 云端 · **boogu** 本地               | `AGNES_API_KEY` / `AIPING_API_KEY` / — |
| 图生图 ti2i  | **agnes** 云端 · **boogu** 本地（⚠️ kolors 不支持）              | `AGNES_API_KEY` / —                    |
| 图片理解     | **agnes**（agnes-2.0-flash）· **aiping**（DeepSeek-OCR-2）       | `AGNES_API_KEY` / `AIPING_API_KEY`    |
| 视频生成     | **agnes**（agnes-video-v2.0，异步轮询）                         | `AGNES_API_KEY`                        |

所有云端 provider 失败均显式报错，不自动 fallback（避免画质/风格跳变让用户困惑）。完整路由表与流程文档见 [SKILL.md](SKILL.md)。

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

> `npx skills add` 失败时，可从 [Releases](https://github.com/Kirky-X/wudaozi/releases) 手动下载 `wudaozi.skill`（zip 格式），解压后把 `SKILL.md` + `references/` + `scripts/` 复制到 agent skills 目录。

### 方式二：传统 git clone

```bash
git clone https://github.com/Kirky-X/wudaozi.git
# 将 SKILL.md + references/ + scripts/ 复制到 agent skills 目录
#   Claude Code:  ~/.claude/skills/wudaozi/
#   Trae:         ~/.trae-cn/skills/wudaozi/
```

### 配置 API key（云端 provider 必需）

按要用的 provider 导出对应环境变量（key 不入代码、不入 git，仅本地环境变量）：

```bash
export AGNES_API_KEY=agn-xxxxxxxx      # agnes 出图/理解/视频，从 agnes-ai.com 控制台获取
export AIPING_API_KEY=QC-xxxxxxxx      # kolors 文生图 / DeepSeek-OCR-2 图片理解，从 aiping.cn 获取

# 验证（5 个脚本各自的自检，不打网络）
python3 scripts/agnes.py  __selfcheck__
python3 scripts/kolors.py __selfcheck__
python3 scripts/vision.py __selfcheck__
python3 scripts/video.py  __selfcheck__
```

未配置任何 key 时，出图可走 boogu 本地（需 GPU）；云端 provider 之间相互独立，不自动 fallback。

## 快速开始

### 文生图 · agnes 云端（无需 GPU）

```bash
# 输出到 $PWD/agnes-output/
AGNES_API_KEY=agn-xxx python3 scripts/agnes.py t2i -i "一只在月光下的橘猫，电影感，高细节"
AGNES_API_KEY=agn-xxx python3 scripts/agnes.py t2i -i "..." --aspect 9:16   # 竖屏壁纸
```

### 文生图 · kolors 云端（agnes 限流时备选，⚠️ 仅 t2i）

```bash
AIPING_API_KEY=QC-xxx python3 scripts/kolors.py t2i -i "..." --aspect 16:9
```

### 文生图/图生图 · boogu 本地（需 CUDA）

```bash
python3 scripts/boogu.py __selfcheck__                                    # 自检（不依赖 GPU）
python3 scripts/boogu.py t2i -i "..."                                     # 文生图 base+bf16+1:1
python3 scripts/boogu.py t2i -i "..." --turbo --aspect 9:16               # turbo 4 步快约 10×
python3 scripts/boogu.py ti2i -i "把背景换成沙滩" --input photo.jpg        # 图生图
python3 scripts/boogu.py t2i -i "..." --dry-run                           # 调试（无 GPU 时只看命令）
```

### 图片理解（VLM）

```bash
# agnes 通识描述（本地图自动转 base64，实测 agnes 接受 data URI）
AGNES_API_KEY=agn-xxx python3 scripts/vision.py agnes --image photo.jpg -q "这张图里有什么"

# aiping DeepSeek-OCR-2 OCR/解题
AIPING_API_KEY=QC-xxx python3 scripts/vision.py aiping --image math.png -q "这道题怎么解答？"

# 结果存 txt（默认正文打 stdout，便于管道读取）
AGNES_API_KEY=agn-xxx python3 scripts/vision.py agnes --image x.jpg -q "..." --output result.txt
```

### 视频生成（异步轮询）

```bash
# 文生视频 5s 16:9（输出到 $PWD/video-output/）
AGNES_API_KEY=agn-xxx python3 scripts/video.py t2vid -i "猫在沙滩走，电影感，暖光"

# 3s 短视频试构图
AGNES_API_KEY=agn-xxx python3 scripts/video.py t2vid -i "..." --duration 3s

# 图生视频（首帧图必须是公网 URL，不支持 base64）
AGNES_API_KEY=agn-xxx python3 scripts/video.py ti2vid -i "镜头缓慢推进" --image https://x/a.png
```

## boogu 模型矩阵（2×2×2 = 8 组）

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

出图需求通常不完整。SKILL.md 强制把需求拆成 **7 维度**补全后再生成（详见 [`references/prompt-template.md`](references/prompt-template.md)）：

```
主体 → 动作/神态 → 背景/环境 → 构图/视角 → 光线 → 风格/媒介 → 画质
```

## 关键约束

1. **能力边界**：本技能只做生成与理解。视频/音频剪辑、3D 模型、PS 类精修合成（抠图/调色/拼接）不在范围。
2. **kolors 仅 t2i**：kolors 硬件约束只支持文生图，**不支持图生图**（CLI 直接拒绝 ti2i）。图生图走 agnes/boogu。
3. **视频 num_frames 须 8n+1**（81/121/241/441），≤441；frame_rate 1-60。入口校验拒绝，用 `--duration` 预设自动满足。
4. **视频 ti2vid `--image` 只接受公网 URL**（文档明确，不支持 base64）；本地图先传图床/OSS，或改用 t2vid。
5. **boogu GPU 必需**：boogu 真出图需 CUDA。无 GPU 环境只能 `--dry-run` 或 `--device cpu`（极慢）；要真出图请走 agnes/kolors。
6. **boogu 模型本地可用性**：本机已下载 `Base` + `Turbo`（T2I 非量化）。其余 6 组需用户下载到 `~/software/Boogu-Image/models/`；脚本会探测缺失并报错。
7. **分辨率**：boogu 模型原生最大 2K（2048），所有宽高必须 16 对齐（脚本自动处理）。agnes/kolors 是云端黑盒，size 清单未知，HTTP 400 时换 `--aspect` 预设。
8. **失败不 fallback**：所有云端 provider 失败均显式报错并退出，由用户决定重试或切 provider。

## 默认参数（boogu 出图）

| 维度                   | base | turbo                |
| ---------------------- | ---- | -------------------- |
| 步数                   | 50   | 4                    |
| text guidance          | 4.0  | 1.0                  |
| image guidance（ti2i） | 1.0  | 1.0                  |
| dmd_conditioning_sigma | —    | t2i=0.001 / ti2i=0.0 |
| CFG                    | 启用 | 关闭（DMD 学生推理） |

视频时长预设（num_frames, frame_rate，均 8n+1）：`3s`=(81,24) · `5s`=(121,24) · `10s`=(241,24) · `18s`=(441,24)。
视频分辨率预设（W,H）：`16:9`=(1152,768) · `9:16`=(768,1152) · `1:1`=(960,960) · `4:3`=(1024,768) · `3:4`=(768,1024)。

## 文件结构

```
wudaozi/
├── SKILL.md                       # 入口：能力×provider 矩阵 + 路由 + 流程
├── skill.json                     # skill 元数据（name/version/tag，.skill 包携带）
├── scripts/
│   ├── agnes.py                   # 出图 agnes 云端（t2i/ti2i，纯 stdlib）
│   ├── kolors.py                  # 出图 kolors 云端（仅 t2i）
│   ├── boogu.py                   # 出图 boogu 本地（2×2×2 矩阵路由）
│   ├── vision.py                  # 图片理解（agnes-2.0-flash / DeepSeek-OCR-2）
│   ├── video.py                   # 视频生成（agnes-video-v2.0 异步轮询）
│   └── test_*.py                  # 5 脚本单元测试（mock 网络层，不打真实 API/模型）
└── references/
    └── prompt-template.md         # 结构化 prompt 7 维度模板 + 案例（出图共用）
```

## 许可证

MIT
