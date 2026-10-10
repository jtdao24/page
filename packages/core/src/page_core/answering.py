"""Grounded question answering over optimized context (Stage 12).

The question's context comes from Stage 10's optimizer; the model is told to
answer only from those numbered sources and cite them as [n]. Without any
relevant source, no model is called. Provider-neutral: any ``ChatModel`` works.
"""

import re
from dataclasses import dataclass

from page_core.context import ContextBlock, ContextPackage
from page_core.llm import ChatModel, Generation

SYSTEM_PROMPT = (
    "You answer questions using only the user's notes, which are given as numbered sources. "
    "Cite the source of every statement with its number in square brackets, like [1] or [2][3]. "
    "If the sources do not contain the answer, say that the notes don't cover it; do not use "
    "outside knowledge or guess. Answer concisely."
)
NO_SOURCES_ANSWER = "I couldn't find anything relevant to that in your notes."
_CITATION = re.compile(r"\[(\d{1,3})\]")


@dataclass(frozen=True, slots=True)
class Answer:
    text: str
    citations: tuple[ContextBlock, ...]
    package: ContextPackage
    model: str
    input_tokens: int
    output_tokens: int
    finish_reason: str
    called_model: bool


def build_prompt(question: str, package: ContextPackage) -> str:
    return f"Sources:\n\n{package.result.context_text}\nQuestion: {question.strip()}\n"


def cited_blocks(text: str, package: ContextPackage) -> tuple[ContextBlock, ...]:
    """Blocks the answer cites, in source-number order; unknown numbers are ignored."""
    numbers = {int(match) for match in _CITATION.findall(text)}
    return tuple(block for block in package.blocks if block.number in numbers)


def answer_question(question: str, package: ContextPackage, model: ChatModel, *,
                    max_output_tokens: int = 1024) -> Answer:
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be nonblank text")
    if not isinstance(package, ContextPackage):
        raise TypeError("package must be a ContextPackage")
    if not package.blocks:
        return Answer(NO_SOURCES_ANSWER, (), package, model.name, 0, 0, "NO_SOURCES", False)
    generation = model.generate(SYSTEM_PROMPT, build_prompt(question, package),
                                max_output_tokens=max_output_tokens)
    if not isinstance(generation, Generation):
        raise TypeError("model must return a Generation")
    return Answer(generation.text.strip(), cited_blocks(generation.text, package), package, model.name,
                  generation.input_tokens, generation.output_tokens, generation.finish_reason, True)
