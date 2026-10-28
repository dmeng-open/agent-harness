# agent-harness

This project builds LLM pipelines and a tool-calling agent on top of one
primitive: a chat-completion call that takes messages and returns a string.
It uses no agent framework and no provider tool-calling. The tool registry,
the text protocol for tool calls, the agent loop, retrieval, the terminal,
context compaction, memory, approvals, and guardrails are all built here.

The agent works over two corpora:

- An email archive: 26,278 emails from the Enron corpus, June to August 2001.
- 24 internal documents of Cardinal Energy, a fictional company.

[docs/GUIDE.md](docs/GUIDE.md) describes every module, the interface
contract, the data, the tests, and the milestones.

## Setup

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/).
   The project needs Python 3.11 or newer, and uv installs one if needed. On
   Windows, also install [Git for Windows](https://git-scm.com/download/win),
   because the terminal sandbox runs commands with its `bash.exe`.
2. Create `.env` and set `ANTHROPIC_API_KEY`. The file is gitignored.
   Models named `anthropic/...` call the Anthropic API directly; any other
   model goes through OpenRouter and needs `OPENROUTER_API_KEY`.

   ```sh
   cp .env.example .env
   ```

3. Unpack the email archive. The script verifies the checksum of
   `data/emails.jsonl.gz` and writes `data/emails/emails.jsonl`.

   ```sh
   uv run python data/download.py
   ```

4. Run the tests.

   ```sh
   uv run pytest
   ```

Run every command from the repository root with `uv run`.

## Tests

**Deterministic tests** run by default and make no model calls. Where code
needs a model, they pass a `ScriptedLM`, which replays a fixed list of
replies.

```sh
uv run pytest                          # all deterministic tests
uv run pytest tests/test_priority.py   # one milestone
```

**Live tests** call the real model and compare results against the
thresholds in `tests/thresholds.py`. They cost money.

```sh
uv run pytest -m live -s                                         # all live tests
HARNESS_EVAL_SLICE=5 uv run pytest tests/test_priority.py -m live -s  # first 5 items only
```

With `-s`, each live test prints its score and the items it got wrong.

## Tools

```sh
uv run python -m harness.show bm25 "larchfield audit"     # run one pipeline on real data
uv run python -m harness.show digest 2001-06-22 --labels --limit 30
uv run python -m harness.chat --mode confirm              # talk to the agent
uv run python -m harness.simulation --slice 3             # simulated-user evaluation
uv run python -m harness.llm                              # spending report
```

## Model calls and spending

Every model call goes through `harness.llm.LM`.

```python
from harness.llm import LM

lm = LM()            # the agent model, anthropic/claude-haiku-5-5
judge = LM("judge")  # the evaluation judge, anthropic/claude-sonnet-5-5
text = lm([{"role": "user", "content": "Say hello."}])
```

- **Cache.** Each reply is stored under `.lm_cache/`, keyed on the model,
  the sampling settings, and the exact messages. A repeated call is free.
- **Ledger.** Each paid call is appended to `.lm_cache/ledger.jsonl` with
  its token counts and cost.
- **Budget.** Once the ledger total reaches `HARNESS_BUDGET_USD`, the wrapper
  raises `BudgetExceeded` instead of making new calls.

Deleting `.lm_cache/` deletes both the cache and the ledger.

## The terminal sandbox

`harness.sandbox.run_terminal(cmd)` runs one shell command for the
agent, with a program allowlist, a scrubbed environment, and a timeout. On
macOS and on Linux with bubblewrap, it also uses an operating-system jail.
There is no jail on Windows. To see which jail your machine uses:

```sh
uv run python -c "from harness import sandbox; print(sandbox.jail())"
```

## License

MIT. See [LICENSE](LICENSE).
