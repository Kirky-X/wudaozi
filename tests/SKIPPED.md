# wudaozi tests/SKIPPED.md — 冒烟套件未覆盖项及原因

原则：③副作用脚本/副作用代码路径不写假测试。以下路径涉及真实网络调用或外部
二进制依赖，离线环境无法验证，也未用 mock 伪装成"已测试"。

## 真实 API 调用层（所有 provider）

| 未覆盖路径 | 位置 | 原因 |
| --- | --- | --- |
| agnes 生图全流程（构造→POST→下载落盘） | `scripts/agnes.py` `call_api` / `_download` / `main`（非 dry-run） | 调 `https://apihub.agnes-ai.com` 真实生成 API，消耗额度且结果不确定；冒烟只测请求组装（`build_body`）与响应处理（`save_image`，下载函数 mock） |
| kolors 生图全流程 | `scripts/kolors.py` `call_api` / `_download` / `main`（非 dry-run） | 同上，调 `https://www.aiping.cn` 真实 API |
| vision 图像理解全流程 | `scripts/vision.py` `call_api` / `main`（非 dry-run） | VLM 推理按 token 计费，离线不可复现 |
| video 创建任务→轮询→mp4 下载全流程 | `scripts/video.py` `create_task` / `poll_task` / `download_video` 的真实网络 IO / `main`（非 dry-run） | 视频生成分钟级耗时 + 费额度；状态机逻辑已用 mock urlopen 测（completed/failed/timeout/id 缺失），仅真实 HTTP IO 未测 |
| boogu 真实推理 | `scripts/boogu.py` `check_resources` / `subprocess.run` / `main`（非 dry-run） | 需本地 `~/software/Boogu-Image` venv + 模型权重 + GPU；dry-run 路径已测（参数组装与脚本路由） |
| `agnes.remove_chroma` 本地去色 | `scripts/agnes.py` | 需可选依赖 Pillow；缺 Pillow 环境下无法验证（深层套件 scripts/test_agnes.py 有 `importorskip` 版本） |
| `--count > 1` 批量并发路径 | `scripts/agnes.py` / `kolors.py` `main` 线程池分支 | 依赖真实 `call_api` 成功返回；`--count` 入参校验（1-8）已测 |

## 如需在线验证

各脚本自带 `--dry-run`（只打印等价 curl，不打网络）可作为在线冒烟起点；
真实调用属生成任务，应由使用者按 SKILL.md 显式发起，不进入离线测试套件。
