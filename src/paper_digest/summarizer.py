from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from .models import Paper, PaperSummary


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
SUMMARY_FIELDS = [
    "one_sentence",
    "research_category",
    "mechanism",
    "study_type",
    "laser_parameters",
    "target",
    "ion_species",
    "max_energy",
    "main_contribution",
    "limitations",
    "why_it_matters",
]


class Summarizer:
    def summarize(self, paper: Paper) -> PaperSummary:
        raise NotImplementedError


class FallbackSummarizer(Summarizer):
    def summarize(self, paper: Paper) -> PaperSummary:
        return PaperSummary.fallback(paper)


class OpenAISummarizer(Summarizer):
    def __init__(self, api_key: str, model: str | None = None) -> None:
        self.api_key = api_key
        self.model = model or os.getenv("OPENAI_MODEL") or "gpt-5.5"

    def summarize(self, paper: Paper) -> PaperSummary:
        payload = {
            "model": self.model,
            "instructions": (
                "你是激光等离子体和激光离子加速方向的文献助理。"
                "只根据用户提供的标题、作者、分类和摘要总结，不要编造摘要中没有的实验参数。"
                "请先判断论文是否确实属于激光离子加速/激光驱动离子源相关研究，"
                "依据包括 laser-driven ion/proton、laser-accelerated ion/proton、TNSA、RPA、BOA、MVA、"
                "collisionless shock acceleration、near-critical density target 等核心证据。"
                "如果核心相关性不足，将 research_category 写为‘其他/相关性存疑’，不要因为只出现材料缺陷、退火、半导体器件等词就判为相关。"
                "若核心相关性成立，再将 research_category 归为以下之一：实验、理论/模拟、机器学习交叉、材料辐照交叉、器件辐照交叉、其他。"
                "材料辐照交叉包括 radiation damage、irradiation damage、materials irradiation、defect formation/evolution、"
                "point defect、vacancy、interstitial、defect cluster、microstructure evolution、recrystallization/recrystallisation、annealing 等。"
                "器件辐照交叉包括 semiconductor device、electronics irradiation、single event effects、SEE、SEU、SEL、SET、SEB 等。"
                "机器学习交叉包括 machine learning、Bayesian optimization/optimisation、closed-loop optimization、active learning、surrogate model、neural network 等。"
                "输出必须是 JSON 对象，字段固定为："
                + ", ".join(SUMMARY_FIELDS)
                + "。如果摘要未提供某项信息，写“摘要中未明确说明”。"
            ),
            "input": _build_input(paper),
        }
        request = urllib.request.Request(
            OPENAI_RESPONSES_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
        text = _extract_output_text(data)
        return _summary_from_json(text, paper)


def make_summarizer(use_openai: bool = True) -> Summarizer:
    api_key = os.getenv("OPENAI_API_KEY")
    if use_openai and api_key:
        return OpenAISummarizer(api_key=api_key)
    return FallbackSummarizer()


def _build_input(paper: Paper) -> str:
    return "\n".join(
        [
            f"Title: {paper.title}",
            f"Authors: {', '.join(paper.authors)}",
            f"arXiv ID: {paper.paper_id}",
            f"Categories: {', '.join(paper.categories)}",
            f"Published: {paper.published.isoformat()}",
            f"Updated: {paper.updated.isoformat()}",
            "",
            "Abstract:",
            paper.abstract,
        ]
    )


def _extract_output_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    chunks = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    return "\n".join(chunks)


def _summary_from_json(text: str, paper: Paper) -> PaperSummary:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.removeprefix("json").strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return PaperSummary.fallback(paper)
    values = {field: _string_or_default(payload.get(field)) for field in SUMMARY_FIELDS}
    return PaperSummary(**values)


def _string_or_default(value: object) -> str:
    if value is None:
        return "摘要中未明确说明"
    if isinstance(value, str):
        return value.strip() or "摘要中未明确说明"
    return json.dumps(value, ensure_ascii=False)
