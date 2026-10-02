# Trigger Evals — 触发回归评估集

> wudaozi 的触发面（4 能力 × 3 图像提供方 + OCR/视频 + 5 条反向路由）比官方示例技能复杂，最需要**行为级**触发回归。本目录是查询集与期望标签；协议结构吸收自 anthropics/skills 的 skill-creator（Description Optimization 一节），执行方式适配本仓：**判定由 agent 会话完成**（触发判定本质是 LLM 行为，不进 pytest——pytest 只钉数据契约，见 `scripts/test_evals.py`）。

## 数据集

[`triggers.json`](triggers.json)：20 条查询，`train`/`test` 按 **60/40** 切分。

- `train`（12 条）：调 description/触发词时的对照集——改动后在这 12 条上先自测。
- `test`（8 条）：**择优判据**——候选 description 在 train 上表现相当时，用 test 分高者。
- `category=boundary` 的均为"不应触发"（反向路由），覆盖 brandkit / cangjie / diting·maliang / style-library / 能力边界外。

## 协议（改触发词必跑）

1. **改动**：只动 SKILL.md frontmatter description（与 skill.json 同步）。
2. **评审**：新开 agent 会话（无本仓上下文），对每条 query 问"这个请求该路由给 wudaozi 吗？"；**每条查 3 次投票**（同一会话 3 问或 3 个独立会话），多数决。
3. **判据**：test 集 8 条全对才接受改动；train 允许 ≤1 错（记录在案）。
4. **留痕**：结果追加到本文件底部"运行记录"（日期/改动摘要/train、test 正确数）。

## 运行记录

| 日期 | 改动 | train | test | 备注 |
|------|------|-------|------|------|
| 2026-10-02 | 初版基线（description 898→651 字符瘦身，反向路由下沉正文） | 待跑 | 待跑 | 基线尚未执行评审（需 agent 会话，非 CI） |
