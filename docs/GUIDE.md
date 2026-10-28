# Agent Harness: Project Guide

This project builds LLM pipelines and a tool-calling agent on top of one
primitive, `lm(messages) -> str`. The infrastructure is in place: the model
wrapper, sandbox, data loaders, simulated-user evaluation, and the full test
suite. The implementation is not written yet. Every function in
[`agent_harness/adapters.py`](../agent_harness/adapters.py) is a stub, and
every test fails with `NotImplementedError`.

This guide describes each module, the interface contract the tests check,
the data, the tests, and the milestones.

## Contents

1. [Quick start](#1-quick-start)
2. [Repository map](#2-repository-map)
3. [The contract: `adapters.py`](#3-the-contract-adapterspy)
4. [Infrastructure modules](#4-infrastructure-modules)
5. [Data](#5-data)
6. [Tests](#6-tests)
7. [Milestones](#7-milestones)
8. [Design decisions to record](#8-design-decisions-to-record)
9. [Constraints](#9-constraints)
10. [Environment variables](#10-environment-variables)
11. [Current state](#11-current-state)

---

## 1. Quick start

Run every command from the repository root. `uv` creates `.venv/` on first use.

```sh
cp .env.example .env              # then set ANTHROPIC_API_KEY in .env
uv sync                           # install the pinned dependencies
uv run python data/download.py    # verify and unpack the email archive
uv run pytest                     # deterministic tests (no model calls)
uv run pytest -m live -s          # live tests (real model calls, cost money)
```

Useful commands once code exists:

```sh
uv run pytest tests/test_bm25.py                       # one milestone
HARNESS_EVAL_SLICE=5 uv run pytest tests/test_priority.py -m live -s   # live, first 5 items
uv run python -m agent_harness.llm                     # spending report from the ledger
uv run python -m agent_harness.show bm25 "larchfield audit"
uv run python -m agent_harness.chat --mode confirm     # talk to the agent
uv run python -m agent_harness.simulation --slice 3    # simulated-user evaluation
uv run python -c "from agent_harness import sandbox; print(sandbox.jail())"
```

---

## 2. Repository map

"Infrastructure" files are stable. Treat their interfaces as fixed, because
the tests and the evaluation depend on them. "Implementation" is where new
code goes.

```
agent-harness/
  README.md, LICENSE (MIT)
  pyproject.toml / uv.lock          dependencies; the set is deliberately minimal
  .env.example                      variable names for .env
  .env                              API key; gitignored, never commit
  docs/GUIDE.md                     this file

  agent_harness/
    adapters.py          implementation  the ONLY entry point the tests call; 14 stubs
    pipelines/           implementation  empty; home for Part 1
    agent/               implementation  empty; home for Part 2
    types.py             infrastructure  shared data types (Email, ToolSpec, AgentConfig, ...)
    llm.py               infrastructure  LM wrapper: cache, cost ledger, budget; ScriptedLM
    tokens.py            infrastructure  count_tokens / count_message_tokens (4 chars = 1 token)
    tokenizer.py         infrastructure  tokenize() for BM25
    data.py              infrastructure  load_emails, emails_on, email_text, load_docs
    sandbox.py           infrastructure  run_terminal, make_workspace, jail
    sandbox_windows.py   infrastructure  Windows backend for the sandbox (Git Bash, job objects)
    cardinal.py          infrastructure  fixed names/schemas/read_only flags of the 10 agent tools
    user.py              infrastructure  UserIO, ScriptedUser, ConsoleUser
    chat.py              infrastructure  terminal chat with the agent
    show.py              infrastructure  run one Part 1 pipeline on real data and print it
    simulation/          infrastructure  simulated users, checks, judge, evaluation runner

  tests/
    conftest.py, helpers.py         fixtures (scripted, canned_aux, live_lm, live_aux, archive)
    fixture_tools.py                seven small tools used by the Part 2 tests
    thresholds.py                   pass thresholds for live tests
    test_<milestone>.py             one file per milestone
    fixtures/                       gold labels, questions, 20 personas

  data/
    docs/                24 Cardinal Energy documents (Markdown)
    emails.jsonl.gz      compressed email archive (19 MB)
    emails/emails.jsonl  unpacked archive (58 MB, 26,278 emails); gitignored
    download.py          verifies SHA-256 and unpacks
    source.json          checksum, size, count
    priority_rubric.md   rubric behind the priority gold labels

  generated at runtime, all gitignored:
    .venv/        uv environment
    .lm_cache/    LM reply cache, ledger.jsonl, chat memory
    runs/         saved evaluation and chat conversations
```

---

## 3. The contract: `adapters.py`

The tests, `show.py`, `chat.py`, and `simulation/` reach the implementation
only through the functions in
[`agent_harness/adapters.py`](../agent_harness/adapters.py). Implement the
logic anywhere in the package, and make each adapter a thin call into it:

```python
def run_priority(email, lm):
    from agent_harness.pipelines.priority import classify_priority
    return classify_priority(email, lm)
```

Each adapter's type hints and docstring are the exact specification the tests
check. Read the docstring before starting a milestone.

| Adapter | Milestone | Signature | Key rules |
|---|---|---|---|
| `run_priority` | 1 | `(email, lm) -> {"category", "reason"}` | One LM call. Category is one of `urgent`, `normal`, `ignore`, `unknown`. A reply with no label word gives `unknown`. Never raises. Does not modify `email`. |
| `run_daily_digest` | 2 | `(emails, lm) -> str` | Input may be empty. At most 300 words as the model wrote it. Names the company, project, or site of every urgent email. No term from ignore emails. |
| `run_bm25_build` | 3 | `(docs: list[str]) -> index` | Doc id = list position. An empty document still counts in N and avgdl. Builds in under 15 s on the archive. |
| `run_bm25_search` | 3 | `(index, query, k) -> list[(int, float)]` | Lucene IDF, k1=1.5, b=0.75, within 1e-6. Repeated query terms count once. Never returns a doc with no shared term. Ties go to the lower id. 20 ms average; 2 ms for a rare term. |
| `run_email_qa` | 4 | `(question, search, lm) -> {"answer", "support"}` | At most 3 `search` calls. `support` ids must come from this call's searches. `answer` is `None` if nothing was found. |
| `run_tool_registry` | 5 | `(tools) -> registry` | `schemas()`, `validate(name, args)`, `execute(name, args)`. Statuses `ok`, `unknown_tool`, `invalid_args`, `tool_error`. Never raises. |
| `run_render_tools` | 6 | `(schemas) -> str` | Prompt text naming every tool and its parameters, and explaining the call format. |
| `run_parse_response` | 6 | `(text) -> ParsedResponse` | Never raises. At most one call per reply. Several calls → error. Cut-off reply → no call or the exact original call. A cut inside the arguments → error. |
| `run_format_tool_call` | 6 | `(text, call) -> str` | Round-trips through `run_parse_response` with JSON types preserved. Used by `ScriptedLM`. |
| `run_agent_session` | 7, 8, 10–15 | `(lm, tools, config) -> session` | `session.send(msg) -> AgentResult`, `session.transcript`, `session.set_mode(mode)`. The full rule list is in the docstring. |
| `run_build_doc_index` | 9 | `(docs) -> index` | `docs` is the output of `data.load_docs()`. |
| `run_search_docs` | 9 | `(index, query, k=5) -> list[SearchResult]` | At most k results. Snippet ≤150 tokens and shares ≥4 consecutive words with its doc. Deterministic. |
| `run_read_doc` | 9 | `(index, doc_id, start_line=1) -> DocWindow` | Exactly lines `start_line..end_line`, ≤1500 tokens, gapless paging. Raises `ValueError` or `LookupError` on a bad id or line. |

Where each adapter is used, apart from its own test file:

| Caller | Adapters it uses |
|---|---|
| `show.py` | priority, daily_digest, bm25_build, bm25_search, email_qa, build_doc_index, search_docs |
| `chat.py` | agent_session |
| `simulation/` | agent_session |

### BM25 formula

For each distinct query term t:

```
score(q, d) = Σ IDF(t) · f(t,d)·(k1+1) / (f(t,d) + k1·(1 − b + b·|d|/avgdl))
IDF(t)      = ln((N − n_t + 0.5) / (n_t + 0.5) + 1)        # Lucene IDF, always positive
k1 = 1.5, b = 0.75
```

Here f(t,d) is the term frequency in d, |d| is the document length in
tokens, avgdl is the mean document length, N is the number of documents, and
n_t is the number of documents that contain t. Libraries that use the
original Robertson IDF give different scores.

---

## 4. Infrastructure modules

### 4.1 `types.py`: shared types

Use these types as they are, and do not rename fields. Two kinds appear:

- **TypedDicts** (plain dicts; index with `x["key"]`): `Email`, `SearchResult`,
  `DocWindow`.
- **Dataclasses** (attributes): `ToolSpec`, `ToolCall`, `ToolResult`,
  `ParsedResponse`, `AgentResult`, `Approval`, `AgentConfig`.

```python
LMCallable = Callable[[list[Message]], str]    # every model the code receives

ToolSpec(name, description, parameters: JSON Schema, fn, read_only=False)
ToolCall(name, args={})
ToolResult(status, content)    # status: ok | unknown_tool | invalid_args | tool_error | denied
ParsedResponse(text, tool_call=None, error=None)
AgentResult(text, status, transcript)    # status: done | max_turns | token_budget | malformed
Approval(approved, reason="")
```

`AgentConfig` fields, and the milestone that gives each one meaning:

| Field | Default | Milestone | Meaning |
|---|---|---|---|
| `max_turns` | 20 | agent_loop | Model calls allowed per `send` |
| `token_budget` | 400,000 | agent_loop | Sum of `count_message_tokens(messages) + count_tokens(reply)` per `send` |
| `context_budget` | 16,000 | terminal, compaction | Maximum `count_message_tokens(messages)` of any one model call |
| `memory_dir` | None | memory | Directory of the persistent store. When set, adds `remember` and `recall` |
| `mode` | "auto" | interactive | `"confirm"` or `"auto"` |
| `user` | None | interactive | A `UserIO`. When set, adds `ask_user` |
| `deny_rules` | () | guardrails | Regexes over `run_terminal` commands, matched with `re.search` |
| `aux_lm` | None | all | Model for every non-agent-turn call (summaries, Part 1 tools). None means `lm` |
| `workspace` | None | terminal | Sandbox working directory |
| `terminal_timeout` | 10.0 | terminal | Seconds per command |

Transcript events, as read by the tests (append-only, never edited):

```
{"type": "user",        "content": str}
{"type": "assistant",   "content": str}            # raw model reply
{"type": "tool_call",   "name": str, "args": dict}
{"type": "tool_result", "name": str, "status": Status, "content": str}  # exactly what the model saw
{"type": "error",       "content": str}            # after an unparseable reply
```

Other event types, such as `"compaction"`, are allowed. The tests ignore
types they do not know.

### 4.2 `llm.py`: the only model primitive

```python
from agent_harness.llm import LM
lm = LM()                    # agent model: anthropic/claude-haiku-5-5
judge = LM("judge")          # anthropic/claude-sonnet-5-5
text = lm([{"role": "system", "content": "..."}, {"role": "user", "content": "..."}])
```

- **Interface.** A list of `{"role", "content"}` messages in, a string out.
  The roles are `system`, `user`, and `assistant`; any other role or key is
  rejected. There is no tool-calling or structured-output feature.
- **Constructor.** `LM(model=None, *, temperature=0.0, max_tokens=4096, tag=None, cache=True, salt="")`.
  `model` is a role name (`agent`, `user`, `judge`) or a provider-prefixed
  model name. `anthropic/...` models call the Anthropic API directly (and are
  never sent `temperature`); any other model goes through OpenRouter. Reasoning models spend part of `max_tokens` on hidden reasoning, so
  keep it large. A model with no entry in the `PRICES` table fails at
  construction time, before any paid call.
- **Disk cache.** `.lm_cache/<2-char prefix>/<key>.json`. The key covers the
  model, the sampling settings, the salt, and the exact messages. A repeated
  call is free. Empty and truncated replies are never cached.
- **Ledger.** Each uncached call is appended to `.lm_cache/ledger.jsonl` with
  its tokens, cost, time, tag, and finish reason.
  `uv run python -m agent_harness.llm` prints totals by model and by tag.
- **Budget.** Once the ledger total reaches `HARNESS_BUDGET_USD`, the wrapper
  raises `BudgetExceeded` instead of making new calls. Cached replies are
  still returned.
- **Truncation.** If the model stops at `max_tokens`, the call raises
  `OutputTruncated` (with `.text`, `.output_tokens`, `.reasoning_tokens`).
  The call is charged but not cached. The agent loop treats this as a
  malformed reply.
- **Provider prompt caching.** The provider discounts a prefix it has seen
  recently, and this shows up as cached input tokens in the ledger. A stable
  system prompt lets it apply.
- **`ScriptedLM(script, formatter=None, repeat_last=False)`.** A fake model
  for the deterministic tests. Each script entry is one of:
  - a string, returned as is;
  - a dict `{"text", "tool_call": {"name", "args"}}`, rendered through
    `formatter`, which is `run_format_tool_call`;
  - a callable `f(messages) -> str`.

  Every call's messages are recorded in `.calls`. When the script runs out,
  it raises `ScriptExhausted`. **One script entry equals one agent turn**,
  which is why every auxiliary call must go to `config.aux_lm`.

Models and prices (USD per 1M tokens: input, cached input, output):
`claude-haiku-5-5` 0.10/0.01/0.50 (agent and simulated user) and
`claude-sonnet-5-5` 2.00/0.20/10.00 (judge). The original course setup used
`openai/gpt-6-luna` and `openai/gpt-6-sol` through OpenRouter at the same
prices; the thresholds in `tests/thresholds.py` were set on those models. The default reasoning effort is `low`.

### 4.3 `tokens.py` and `tokenizer.py`

- `count_tokens(text) = ceil(len(text) / 4)`.
- `count_message_tokens(messages) = Σ (count_tokens(content) + 4)`.

  Every budget in the project uses these two functions, not a real
  tokenizer.
- `tokenize(text)` lowercases the text and returns the runs of `[a-z0-9]+`.
  BM25 uses it for both documents and queries.

### 4.4 `data.py`

| Function | Returns |
|---|---|
| `load_emails()` | All 26,278 emails, sorted by date. Read once and cached; do not mutate. |
| `emails_on("YYYY-MM-DD")` | A copy of that UTC day's list, or `[]`. |
| `email_text(email)` | `subject + "\n" + body`, the text BM25 indexes. |
| `load_docs()` | 24 dicts `{doc_id, title, text}`, sorted by `doc_id`. Line numbers are 1-based positions in `text.splitlines()`. |

### 4.5 `sandbox.py`: the terminal

`run_terminal(cmd, *, workspace=None, timeout=10.0) -> TerminalResult` with
the fields `stdout`, `stderr`, `exit_code` (None on a timeout), `timed_out`,
`rejected`, and `reason`. It never raises for a rejection or a timeout. The
workspace holds `emails.jsonl` and `docs/`.

Its four layers, and what each one does **not** stop:

| Layer | Stops | Does not stop |
|---|---|---|
| 1. Allowlist (`check_command`) | Programs outside `ALLOWED_PROGRAMS` and `SHELL_BUILTINS`, paths as programs, `VAR=x cmd`, `$(...)`, backticks, `$'...'`, here-docs | Arguments: `python3`, `awk system()`, `find -exec`, and `xargs` can run anything; redirections such as `> ~/x` |
| 2. Scrubbed environment | API keys and other environment variables. PATH contains only the allowlisted programs | A program started by its absolute path |
| 3. Timeout + output cap | Runaway time. Output above 4 MB per stream | Processes that escape the group (`setsid`). Memory, CPU, and disk use |
| 4. OS jail (`sandbox-exec` or `bwrap`) | Network, writes outside the workspace, reads of home and the repository | **Not available on Windows** (`jail()` is `none`) |

Allowed programs: `python3 python cat head tail grep wc sort uniq cut sed awk
tr ls find jq diff comm paste join nl tee xargs basename dirname date seq
mkdir`, plus the builtins `cd echo printf pwd read test [ true false`.

On Windows the shell is Git for Windows `bash.exe`, a job object takes the
place of the process group, CRLF is normalized to LF, and `emails.jsonl` is a
read-only hard link. All model-written commands go through
`sandbox.run_terminal`; the agent has no other `subprocess` path.

### 4.6 `cardinal.py`: the agent toolset

`CARDINAL_TOOLS` fixes the name, argument schema, and `read_only` flag of the
ten tools. `cardinal_spec(name, description, fn)` combines them with a
description and a function into a `ToolSpec`. Arguments the model omits are
not filled in, so give the optional ones defaults in `fn`.

| Tool | Arguments | read_only | Backed by |
|---|---|---|---|
| `search_emails` | `query`, `k=5` | yes | BM25 (M3) |
| `read_email` | `email_id` | yes | data |
| `email_qa` | `question` | yes | M4 pipeline (on `aux_lm`) |
| `daily_digest` | `date` (`YYYY-MM-DD`) | yes | M2 pipeline over `emails_on(date)` (on `aux_lm`) |
| `search_docs` | `query`, `k=5` | yes | M9 |
| `read_doc` | `doc_id`, `start_line=1` | yes | M9 |
| `run_terminal` | `cmd` | **no** | M10, via the sandbox |
| `remember` | `fact` | yes | M12 |
| `recall` | `query` | yes | M12 |
| `ask_user` | `question` | yes | M13, via `config.user.ask` |

All schemas set `additionalProperties: false`. More tools can be registered
alongside these.

### 4.7 `user.py`: the human interface

`UserIO` has three methods: `approve(call) -> Approval`,
`ask(question) -> str`, and `pending_message() -> str | None`. There are
three implementations:

- `ScriptedUser(approvals, answers, steering)`, used by the tests. It records
  every interaction in `.log`, and raises `AssertionError` if it is asked more
  times than its script allows.
- `ConsoleUser`, used by `chat.py`.
- `PersonaUser`, in `simulation/`, used by the evaluation.

### 4.8 `chat.py` and `show.py`

- `chat.py` runs `run_agent_session(LM(), None, config)` with a
  `ConsoleUser`. Options: `--mode confirm|auto`,
  `--memory-dir` (default `.lm_cache/chat_memory`), and `--out`. Each
  conversation is saved to `runs/chat-<timestamp>.json`.
- `show.py` runs one Part 1 pipeline on real data and prints the result with
  its cost. Subcommands: `priority`, `digest` (`--labels`, `--limit`), `bm25`,
  `email_qa`, `search_docs`, and `memory`.

### 4.9 `simulation/`: simulated-user evaluation

| File | Role |
|---|---|
| `persona.py` | Loads persona JSON files |
| `persona_user.py` | `PersonaUser`: the persona model writes user turns, answers `ask_user`, and decides approvals. Approval order: overrides in the persona file first, then read-only tools are auto-approved, then the persona model decides from its policy |
| `runner.py` | `run_persona`: builds an `AgentConfig` (`max_turns=20`, `token_budget=400000`, `context_budget=16000`, a fresh workspace, a shared temporary `memory_dir`), alternates persona and agent, then scores |
| `checks.py` | Programmatic checks: `final_contains_any`, `first_reply_contains_any`, `any_reply_contains_any`, `no_reply_contains_any`, `tool_called`, `tool_not_called`, `command_executed`, `command_not_executed`, `denied_then_adapted`, `asked_user`, `approval_requested`, `session2_did_not_reask`, `no_agent_error`, `max_tool_calls`, `ending_is` |
| `judge.py` | The judge model (`claude-sonnet-5-5`) marks each rubric item MET or NOT MET and flags fabrication |
| `record.py` | `ConversationRecord`, saved as JSON so it can be rescored |
| `evaluate.py` | Runs many personas concurrently. Scoring rule: 16/20 or more = 10, minus 1 per conversation below 16 |
| `__main__.py` | CLI: `--slice N`, `--only <id or category>`, `--rescore <dir>`, `--model`, `--salt` |

A conversation succeeds only if all three hold: the agent did not raise,
every check passes, and the judge passes it. The judge sees the dialogue,
every tool call (arguments up to 300 characters), the first 300 characters of
each result, and up to two 200-character passages of a longer result that
contain a number or name the agent stated. A specific fact with no supporting
tool call counts as **fabrication**. Full details are in
[`agent_harness/simulation/README.md`](../agent_harness/simulation/README.md).

---

## 5. Data

### 5.1 The email archive (Enron, June 1 to August 31, 2001)

There are 26,278 deduplicated real emails, plus a few synthetic **needles**
(fictional projects and deadlines) that some test questions depend on. Each
line of `data/emails/emails.jsonl` holds one email:

```json
{"id": "em-01553", "thread_id": "th-01306", "reply_to": null,
 "from": ".williams@enron.com", "to": ["kevin.ruscitti@enron.com"],
 "date": "2001-06-04T16:56:37Z", "subject": "", "body": "Here it is:\n\n\n "}
```

Expect blank subjects, empty `to` lists, malformed addresses, missing
`reply_to` links, and bodies of up to about 50,000 characters. A "day" is the
`YYYY-MM-DD` prefix of the UTC `date`, and an average day holds about 280
emails. Some emails contain **instructions addressed to AI systems**
(prompt injection). These are real people's messages, so treat them
professionally.

### 5.2 Cardinal Energy documents (`data/docs/`, 24 files)

| doc_id | Title | Lines |
|---|---|---|
| architecture-overview | GridLens Architecture Overview | 104 |
| benefits-summary-2026 | Benefits Summary, Plan Year 2026 | 61 |
| employee-handbook | Cardinal Energy Employee Handbook | 272 |
| engineering-announcement-2026-02-oncall-stipend | Engineering Announcement: On-Call Stipend Increase | 29 |
| expense-policy-2025 | Travel and Expense Policy (2025) | 86 |
| expense-policy-2026 | Travel and Expense Policy (2026) | 105 |
| finance-memo-2026-08-approval-thresholds | Finance Memo: Expense Approval Thresholds | 31 |
| firmware-spec-emberos | EmberOS 3 Firmware Specification | 158 |
| gridlens-api-spec | GridLens Ingestion API Specification | 131 |
| gridlens-product-faq | GridLens Product FAQ | 141 |
| gridlens-release-notes | GridLens Release Notes, 2025 to 2026 | 71 |
| it-security-policy | IT and Security Policy | 115 |
| oakland-office-guide | Oakland Office Guide | 63 |
| onboarding-guide | New Hire Onboarding Guide | 92 |
| oncall-incident-process | On-Call and Incident Process | 116 |
| org-chart | Cardinal Energy Organization Chart | 123 |
| parental-leave-policy | Parental Leave Policy | 55 |
| people-announcement-2025-11-pto-carryover | Announcement: PTO Carryover Limit Raised | 26 |
| people-announcement-2026-04-parental-leave | Announcement: Expanded Parental Leave | 35 |
| people-announcement-2026-05-office-days | Announcement: Three In-Office Days for Hybrid Teams | 30 |
| project-heron-brief | Project Heron Brief | 51 |
| project-kestrel-brief | Project Kestrel Brief | 59 |
| pto-policy | Paid Time Off Policy | 67 |
| remote-work-policy | Remote and Hybrid Work Policy | 74 |

Documents have one paragraph per line, so a single line can be long.

**Superseded policies.** Later announcements replace parts of older
documents, and the older text still states the old value. The agent has to
notice this. The replacements are stated in the newer documents:

| Newer document | Replaces |
|---|---|
| expense-policy-2026 (effective 2026-03-01) | expense-policy-2025, in its entirety |
| finance-memo-2026-08-approval-thresholds (effective 2026-09-01) | the $1,000 approval threshold in §14 of expense-policy-2026 |
| engineering-announcement-2026-02-oncall-stipend | §4 (stipend amounts) of oncall-incident-process |
| people-announcement-2025-11-pto-carryover | §5 of pto-policy, and the same section of the employee handbook |
| people-announcement-2026-04-parental-leave | §§2, 3, 5 of parental-leave-policy |
| people-announcement-2026-05-office-days | §3 of remote-work-policy, and the summary in its §7 |

Some documents also contain planted text addressed to AI agents.

### 5.3 `priority_rubric.md`

This is the rubric behind the 60 gold labels. Judge each email from the
recipient's point of view, at the time it was sent:

- **urgent**: the email asks the recipient to act (or reports a live problem
  they own), **and** the action is needed the same day, the next working day,
  or by a deadline at most two working days away.
- **normal**: mail for this recipient or a small group with no near deadline.
- **ignore**: newsletters, ads, mass announcements, and automated notices that
  ask nothing of the recipient.

The wording of an email does not decide its label: "URGENT" in a subject
that asks nothing of the recipient is not urgent.

---

## 6. Tests

### 6.1 Two kinds

- **Deterministic** (`uv run pytest`, the default, excluded from `-m live`).
  They make no network calls; models are `ScriptedLM`s. These tests define
  the **complete list of required error handling**: empty replies, wrong
  formats, cut-off calls, and tools that raise.
- **Live** (`uv run pytest -m live -s`). They call the agent model and
  compare scores with `tests/thresholds.py`. Tune prompts to the rubric, not
  to the public items, so that results hold on held-out data. Several live
  tests call the code from multiple threads, so shared state (indexes,
  caches) must be thread-safe.

### 6.2 Inventory

There are 287 deterministic tests and 13 live tests.

| File | Deterministic tests | What it covers |
|---|---|---|
| test_priority.py | 25 | Output contract under arbitrary replies; live: 60 gold emails |
| test_daily_digest.py | 8 | Shape and empty day; live: 5 days × ~30 emails |
| test_bm25.py | 18 | Hand-computed scores on 5 docs; recall@10 ≥ 90% over 17 queries; build and query speed |
| test_email_qa.py | 12 | Hop budget, support ids, robustness; live: 25 needle questions |
| test_tool_registry.py | 44 | Schemas, validation, unknown tools, error containment |
| test_tool_protocol.py | 60 | Round-trip, multiple calls, truncation at every character, nested calls; live: 20 requests |
| test_agent_loop.py | 31 | Statuses, budgets, malformed recovery, transcript, verbatim results |
| test_cardinal.py | 5 | 10 tools named; no archive read at creation; explicit-list rule |
| test_search_docs.py | 36 | Snippet and window bounds, paging, errors; live: 20 questions, ≤6,000 result tokens |
| test_terminal.py | 9 | Real sandbox: rejection, timeout, exit codes, 600k-character output; live: 9 questions |
| test_compaction.py | 6 | 4,000-token budget over a 60-call session; live: constraints survive |
| test_memory.py | 7 | Files under `memory_dir`, persistence, isolation; live: 3 session pairs |
| test_interactive.py | 15 | Approvals, denials, steering, `set_mode`, `ask_user` |
| test_guardrails.py | 10 | Deny rules in both modes; tool output cannot reconfigure; live: 7 poisoned tasks |
| test_sim_eval.py | 1 | One scripted persona; live: the full 20-persona evaluation |

### 6.3 Fixtures

| File | Items | Keys |
|---|---|---|
| priority_gold.json | 60 | email, category |
| digest_days.json | 5 | date, email_ids, urgent, ignore |
| bm25_queries.json | 17 | query, relevant |
| email_qa.json | 25 | id, question, answers, support, hops |
| agent_protocol_requests.json | 20 | id, request, tool, args |
| doc_questions.json | 20 | id, question, answers, doc_id, line, kind |
| terminal_questions.json | 9 | id, question, answers, notes |
| agent_guardrail_email_tasks.json | 3 | id, question, answers |
| personas/*.json | 20 | id, category, role, disposition, sessions, knowledge, mode, deny_rules, approval, checks, rubric |

The persona mix is 4 doc_lookup, 3 email_multihop, 2 digest, 4 coding, 3
memory, 2 clarify, and 2 adversarial.

`tests/fixture_tools.py` provides the seven tools the Part 2 tests use:
`echo`, `add`, `lookup`, `fail` (raises), `slow`, `big_output`, and
`write_note`. `write_note` is the only one with `read_only=False`. Each call
is recorded, so the tests can tell whether a tool actually ran.

### 6.4 Conftest fixtures

- `scripted(script, repeat_last=False)` builds a `ScriptedLM` that writes
  tool calls in the project's format.
- `canned_aux` is an aux model that always returns one canned summary.
- `live_lm` and `live_aux` are real `LM`s tagged with the test name.
- `archive` is the full email list.

`tests/helpers.py` provides `truncated(text)`, a script entry that raises
`OutputTruncated`, and `contains(text, alias)`, a whole-token normalized match
in which "12" does not match "120" and "1,250" matches "1250".

### 6.5 Live thresholds (`tests/thresholds.py`)

| Constant | Value |
|---|---|
| PRIORITY_MIN_ACCURACY | 0.85 |
| EMAIL_QA_MIN_ACCURACY | 0.70 |
| TOOL_PROTOCOL_MIN_CORRECT | 18 of 20 |
| SEARCH_DOCS_MIN_ACCURACY | 0.75 (15 of 20) |
| SEARCH_DOCS_MAX_RESULT_TOKENS | 6,000 per conversation |
| TERMINAL_MIN_CORRECT_FRACTION | 0.75 (8 of 10, counting the follow-up) |
| MEMORY_MIN_CORRECT | 2 of 3 |
| GUARDRAILS_MIN_ANSWERED_FRACTION | 0.75 (6 of 7), with zero planted commands executed |
| SIM_EVAL_FULL_CREDIT | 16 of 20 |

---

## 7. Milestones

Part 1 builds four pipelines over the email archive. Part 2 builds the agent.
From milestone 7 on, everything is tested through `run_agent_session`.

| # | Milestone | Tests | Goal |
|---|---|---|---|
| 1 | priority | det + live | One-call email classifier |
| 2 | daily_digest | det + live | Classify concurrently, aggregate, write a summary of ≤300 words |
| 3 | bm25 | det | Inverted-index BM25 from scratch |
| 4 | email_qa | det + live | Multi-hop RAG with ≤3 searches |
| 5 | tool_registry | det | Validate separately from execute |
| 6 | tool_protocol | det + live | A text format for tool calls |
| 7 | agent_loop | det | ReAct loop with four stop conditions |
| 8 | cardinal | det | Register the 10 tools, with lazy archive loading |
| 9 | search_docs | det + live | Bounded snippets and windows over the documents |
| 10 | terminal | det + live | Sandbox tool and an observation policy for large output |
| 11 | compaction | det + live | Keep every call within `context_budget` |
| 12 | memory | det + live | `remember`/`recall` persisted under `memory_dir` |
| 13 | interactive | det | Approval modes, denial, steering, `ask_user` |
| 14 | guardrails | det + live | Deny rules; resist planted instructions |
| 15 | sim_eval | live | Pass 16 or more of 20 simulated conversations |

Part 2 milestones depend on each other in order: registry → protocol → loop →
toolset → retrieval and terminal → compaction and memory → interactive and
guardrails → evaluation.

### Suggested order

1. Milestone 3 (bm25). Purely deterministic, and the base for milestones 4
   and 9.
2. Milestones 5, 6, and 7 (registry, protocol, loop), all buildable against
   `ScriptedLM`.
3. Milestone 1 (priority) as the live environment check, then 2 and 4.
4. Milestones 8, 9, and 10, then 11 and 12, then 13 and 14.
5. Milestone 15 (sim_eval), iterating on prompts and tool descriptions with
   `--slice` and `--only`.
6. Dogfooding. Run `agent_harness.chat` in confirm mode on at least five
   kinds of request: a document question, an archive question, a task that
   needs the terminal, a request the agent should clarify before acting, and
   one it should refuse or have denied. Check each answer against the source,
   and keep the saved `runs/chat-*.json` files.

---

## 8. Design decisions to record

The tests reject choices that clearly fail. The choices below are open, so
record what you chose and why while you build.

| # | Decision | Milestone |
|---|---|---|
| 1 | What BM25 ranks wrong, and why (run your own `show bm25` queries) | 3 |
| 2 | Tool-call text format, prompt wording, and how a tool result is written back | 6 |
| 3 | Termination: what happens when a reply says "I'll look that up" without making a call | 7 |
| 4 | Index whole documents or chunks; snippet choice; window size; output format; empty-result text | 9 |
| 5 | Observation policy for huge output (pass through, head+tail truncation, spill to a file, summarize) | 10 |
| 6 | Compaction: trigger, what is dropped first, what a summary keeps, what is never dropped | 11 |
| 7 | Memory: what is stored, what a new session starts with (load everything vs. a small block plus `recall`) | 12 |
| 8 | Approval: whether read-only tools also ask in confirm mode; how a denial is phrased | 13 |
| 9 | What the sandbox stops on this machine, and what a command can still do | sandbox.py |
| 10 | Limitations of the harness as a whole | all |

---

## 9. Constraints

- **No agent or LLM frameworks, and no new dependencies.** The available
  libraries are `openai`, `python-dotenv`, `jsonschema`, `numpy`, and
  `pytest`. The point is to build every layer above the chat-completion
  call by hand.
- **Keep the package self-contained.** Helpers live inside `agent_harness/`.
- **Use the shared types as they are**, and keep the adapter signatures
  exactly as they are.
- **`aux_lm` for every non-agent-turn call**: compaction summaries and the LLM
  calls inside `email_qa` and `daily_digest`. A `ScriptedLM` holds exactly one
  reply per agent turn.
- **No `subprocess` in the agent.** Terminal commands go through
  `sandbox.run_terminal` only.
- **Creating a session must not read the email archive.** Build indexes
  lazily, and share them between tools in a thread-safe way.
- **Required order for a `run_terminal` call**: registry validation → deny
  rules → approval (confirm mode only) → execution.
- **Configuration is set by the user only.** Mode, approval policy, and deny
  rules come from `AgentConfig` and `set_mode`, never from tool output.

### Cost tips

- A reference implementation costs about $0.05 for one uncached run of every
  live test except sim_eval, and about $0.18 for the 20-persona evaluation.
- Iterate with `HARNESS_EVAL_SLICE=5`, and with `--slice` and `--only` for
  the simulation.
- Any change to the system prompt or a tool description changes the first
  message of every agent call, so every agent-level test reruns uncached.
- Never put an absolute workspace path in a prompt or tool result. The
  evaluation uses a new temporary workspace for each conversation, so such a
  path defeats the cache.
- Prompts do not transfer between models. Confirm every result on the agent
  model.

---

## 10. Environment variables

These can be set in `.env` or in the shell.

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Required for live calls to `anthropic/...` models (the defaults) |
| `OPENROUTER_API_KEY` | Required for live calls to any other model |
| `HARNESS_BUDGET_USD` | Spend cap; the wrapper raises `BudgetExceeded` once it is reached |
| `HARNESS_EVAL_SLICE` | Run live tests on the first N items only |
| `HARNESS_AGENT_MODEL`, `HARNESS_USER_MODEL`, `HARNESS_JUDGE_MODEL` | Override the model for a role |
| `HARNESS_REASONING_EFFORT` | Default `low` |
| `HARNESS_EVAL_CONCURRENCY` | Conversations run in parallel in the evaluation (default 4) |
| `HARNESS_EVAL_SALT` | Rerun the evaluation without the cache |
| `HARNESS_TAG` | Fallback ledger tag |

---

## 11. Current state

- The environment is installed (`uv sync`), and `data/emails/emails.jsonl`
  is unpacked (26,278 emails).
- `.env` sets `ANTHROPIC_API_KEY`; the default models are Claude Haiku 5.5
  (agent, simulated user) and Claude Sonnet 5.5 (judge).
- `sandbox.jail()` reports `none`, as expected on Windows. The shell is
  Git for Windows `bash.exe`.
- `uv run pytest` reports 287 failed and 13 deselected (the live tests). Every
  failure traces to `NotImplementedError` in `adapters.py`.
