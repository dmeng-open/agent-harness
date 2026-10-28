"""Shared fixtures for the test suite."""

from __future__ import annotations

import os
import re

import pytest

from harness.llm import LM, ScriptedLM, _load_env

_load_env()  # so HARNESS_* settings in .env apply to the tests too


def _tag(request) -> str:
    # "tests/test_priority.py::test_live_accuracy" -> "test_priority/test_live_accuracy"
    node = request.node.nodeid.replace("tests/", "").replace(".py::", "/")
    return re.sub(r"\[.*\]$", "", node)


@pytest.fixture
def scripted():
    """Factory for a ScriptedLM whose scripted tool calls are written in
    your format (via the run_format_tool_call adapter).

        lm = scripted([{"text": "Looking.", "tool_call": {"name": "echo", "args": {"x": 1}}},
                       "The answer is 1."])
    """
    from harness import adapters

    def make(script, *, repeat_last: bool = False) -> ScriptedLM:
        return ScriptedLM(script, formatter=adapters.run_format_tool_call, repeat_last=repeat_last)

    return make


@pytest.fixture
def canned_aux():
    """An auxiliary model for deterministic tests: every call returns the
    same short string. Passed as AgentConfig.aux_lm so that summary calls and
    Part 1 tool calls never consume the scripted agent turns."""
    return ScriptedLM(["Summary of earlier conversation: (canned summary)."], repeat_last=True)


@pytest.fixture
def live_lm(request):
    """The real model for live tests: the default agent model."""
    return LM(None, tag=_tag(request))


@pytest.fixture
def live_aux(request):
    """A second real model instance, for AgentConfig.aux_lm in live tests."""
    return LM(None, tag=_tag(request) + "/aux")


@pytest.fixture(scope="session")
def archive():
    """The full email archive as a list of Email dicts."""
    from harness import data

    if not data.EMAILS_PATH.exists():
        pytest.fail(
            f"{data.EMAILS_PATH} is missing. Run `uv run python data/download.py` first.",
            pytrace=False,
        )
    return data.load_emails()


def eval_slice(items: list) -> list:
    """Apply HARNESS_EVAL_SLICE=N (keep the first N items) if it is set."""
    n = os.environ.get("HARNESS_EVAL_SLICE")
    return items[: int(n)] if n else items
