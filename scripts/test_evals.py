#!/usr/bin/env python3
"""wudaozi evals/triggers.json 数据契约测试（评审协议是 agent 行为，不在此跑）。

钉死：JSON 可解析 / 字段完整 / 20 条 / 60-40 切分 / 标签合法 / id 唯一 /
boundary 类全部 not / expected 与 category 一致性。
跑法：python3 -m pytest scripts/test_evals.py -v
"""
# ponytail: 触发判定是 LLM 行为（规则5：模型只做分类）；本测试只钉数据不腐烂。

import json
from pathlib import Path

import pytest

EVALS = Path(__file__).resolve().parent.parent / "evals" / "triggers.json"


@pytest.fixture(scope="module")
def data():
    return json.loads(EVALS.read_text(encoding="utf-8"))


class TestContract:
    def test_meta_complete(self, data):
        meta = data["meta"]
        assert meta["name"] == "wudaozi"
        assert meta["version"]
        assert "skill-creator" in meta["method"]

    def test_twenty_queries(self, data):
        assert len(data["queries"]) == 20

    def test_split_60_40(self, data):
        splits = [q["split"] for q in data["queries"]]
        assert splits.count("train") == 12
        assert splits.count("test") == 8

    def test_fields_complete(self, data):
        for q in data["queries"]:
            assert set(q) >= {"id", "split", "category", "query", "expected", "note"}, q["id"]
            assert q["expected"] in ("trigger", "not"), q["id"]
            assert q["split"] in ("train", "test"), q["id"]
            assert q["query"].strip(), q["id"]
            assert q["note"].strip(), q["id"]

    def test_ids_unique(self, data):
        ids = [q["id"] for q in data["queries"]]
        assert len(ids) == len(set(ids))

    def test_boundary_all_not(self, data):
        for q in data["queries"]:
            if q["category"] == "boundary":
                assert q["expected"] == "not", q["id"]
        assert any(q["category"] == "boundary" for q in data["queries"]), "必须有反向路由样本"

    def test_positive_samples_cover_all_capabilities(self, data):
        cats = {q["category"] for q in data["queries"] if q["expected"] == "trigger"}
        assert {"t2i", "ti2i", "vision", "video"} <= cats, "四大能力都要有正向样本"
