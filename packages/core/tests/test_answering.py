"""Grounded answers: prompt, citations, no model call without sources."""
from page_core.answering import NO_SOURCES_ANSWER, SYSTEM_PROMPT, answer_question, build_prompt
from page_core.context import optimize_context
from page_core.llm import Generation
from test_context import garden

import pytest


class FakeModel:
    name = "fake-model"

    def __init__(self, text="Water twice a week [2], in full sun [1][9][1]."):
        self.text, self.calls = text, []

    def generate(self, system, prompt, *, max_output_tokens):
        self.calls.append((system, prompt, max_output_tokens))
        return Generation(self.text, 321, 17, "STOP")


def package(budget=1000, question="tomato sun water"):
    _, hits, graph = garden()
    return optimize_context(question, hits, graph, budget=budget)


def test_answer_is_grounded_and_cites_sources():
    context = package()
    fake = FakeModel()
    answer = answer_question("How should I grow tomatoes?", context, fake, max_output_tokens=200)

    (system, prompt, limit), = fake.calls
    assert system == SYSTEM_PROMPT and "only the user's notes" in system and "[1]" in system
    assert prompt == build_prompt("How should I grow tomatoes?", context)
    assert context.result.context_text in prompt and prompt.endswith("Question: How should I grow tomatoes?\n")
    assert limit == 200
    assert answer.called_model and answer.model == "fake-model"
    assert (answer.input_tokens, answer.output_tokens, answer.finish_reason) == (321, 17, "STOP")
    assert [block.number for block in answer.citations] == [1, 2]  # 9 doesn't exist; duplicates once
    assert answer.package is context


def test_no_sources_means_no_model_call():
    _, hits, graph = garden()
    empty = optimize_context("tomato", hits, graph, budget=3)  # nothing fits
    fake = FakeModel()
    answer = answer_question("anything?", empty, fake)
    assert fake.calls == [] and not answer.called_model
    assert answer.text == NO_SOURCES_ANSWER and answer.citations == ()
    assert (answer.input_tokens, answer.output_tokens) == (0, 0)


def test_invalid_inputs():
    with pytest.raises(ValueError):
        answer_question("  ", package(), FakeModel())
    with pytest.raises(TypeError):
        answer_question("q", "context", FakeModel())  # type: ignore[arg-type]
