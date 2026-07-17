<div align="center">
  <img src="public/readme-demo.gif" alt="@workersio/skills running inside a coding agent terminal" width="100%">
</div>

<h1>Skills to find unknown bugs before release!</h1>

<p>
  We help your agents test edge cases in your software where rare production bugs hide.
</p>

<p>
  <a href="https://github.com/workersio/skills/blob/main/LICENSE"><img alt="License" src="https://img.shields.io/github/license/workersio/skills?style=for-the-badge&color=111827"></a>
  <a href="https://github.com/workersio/skills/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/workersio/skills?style=for-the-badge&color=111827"></a>
</p>

Most AI-written tests optimize for coverage. They assert implementation details,
mock away the real risk, and pass even when the product breaks.
`@workersio/skills` gives coding agents a testing workflow that asks a stricter
question: will this test catch a real regression that users, operators,
reviewers, or maintainers care about?

`@workersio/skills` provides the general testing skill with five command modes:

```text
$wio scan      # Find high-value tests to add next.
$wio test      # Run candidate discovery, strategy, implementation, and review.
$wio workload  # Generate realistic, replayable workloads with new bug-finding value.
$wio review    # Judge whether a test should be kept, redone, or removed.
$wio doctor    # Audit suite health, weak assertions, flakes, mocks, and CI blind spots.
```

It also includes `$workload-harness`, a separate model-authoring skill for the
deterministic WIO interception pipeline. It cites repository contracts, authors
code-native Python or TypeScript atoms, requires human ratification, and then
drives the public local SDK/CLI loop. The skill does not embed its own ranker,
runner, policy, evidence rules, or stop logic.

## Works With

<p>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="public/openai-dark.svg">
    <img src="public/openai-light.svg" alt="Codex" width="22" align="center">
  </picture> &nbsp;&nbsp;
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="public/claude-dark.svg">
    <img src="public/claude-light.svg" alt="Claude Code" width="22" align="center">
  </picture> &nbsp;&nbsp;
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="public/cursor-dark.svg">
    <img src="public/cursor-light.svg" alt="Cursor" width="22" align="center">
  </picture> &nbsp;&nbsp;
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="public/copilot-dark.svg">
    <img src="public/copilot-light.svg" alt="GitHub Copilot" width="22" align="center">
  </picture> &nbsp;&nbsp;
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="public/gemini-dark.svg">
    <img src="public/gemini-light.svg" alt="Gemini" width="22" align="center">
  </picture>
</p>

`@workersio/skills` is packaged for Codex and Claude Code today. The core skill
content is plain Markdown, so the testing workflow can also be adapted by other
coding agents that support project skills, instructions, or reusable prompts.

## Install

Direct skill install:

```bash
npx skills add workersio/skills
```

Codex plugin marketplace:

```bash
codex plugin marketplace add workersio/skills
```

Claude Code plugin marketplace:

```bash
claude plugin marketplace add workersio/skills
claude plugin install wio@workersio-skills
```

For local Codex plugin testing from this checkout:

```bash
codex plugin marketplace add .
```

## What It Provides

| Area | What the agent gets |
| --- | --- |
| Test discovery | Maps product behavior, recent changes, existing tests, CI, and risk areas before choosing what to test. |
| Strategy selection | Chooses the right level: unit, component, integration, contract, E2E, workload, fuzz, property, mutation, resilience, or monitoring. |
| Test writing | Adds focused tests using the repository's own framework, naming, fixtures, helpers, and runner conventions. |
| Workload generation | Creates realistic, adversarial, seeded, replayable sessions or traffic that add coverage beyond wrappers and parameter sweeps. |
| Workload model authoring | Authors and ratifies cited code-native atoms, then delegates deterministic generation, execution, evidence, and explanation to WIO. |
| Test review | Applies a strict value gate: `KEEP`, `REDO`, or `REMOVE`. Coverage alone is not enough. |
| Suite health | Finds weak assertions, over-mocking, broad snapshots, flakes, skipped tests, slow feedback loops, and CI blind spots. |

## Command Guide

| Command | Use it when | Example |
| --- | --- | --- |
| `$wio scan [target]` | You do not yet know what to test. | `$wio scan checkout` |
| `$wio test [target]` | You want the full write-and-review loop. | `$wio test billing eligibility regression` |
| `$wio workload [target]` | The risk lives in realistic user, API, CLI, job, or load behavior. | `$wio workload onboarding session` |
| `$wio review [target]` | A test exists and you need to decide whether it has real value. | `$wio review tests/billing_eligibility_test.py` |
| `$wio doctor [target]` | The suite is hard to trust or maintain. | `$wio doctor API test suite` |

## Quality Bar

An approved test should answer:

- What user, operator, customer, or API consumer failure does this prevent?
- What production, release, support, debugging, or review risk does it reduce?
- Would it fail for the regression that matters?
- Which assertion or invariant catches the plausible bug?
- Does the setup preserve the important dependency, state, permission, timing, or data risk?
- Does this belong in local development, PR CI, nightly, release, or production monitoring?
- If this is a workload, what existing workload gap does it fill?

If those answers are weak, the test should be redesigned or removed.

## Subagents

`@workersio/skills` includes three optional focused subagents:

| Subagent | Role |
| --- | --- |
| `wio-candidate-scout` | Read-only discovery of high-value test candidates before implementation. |
| `wio-strategy-critic` | Read-only challenge of the selected strategy before editing tests. |
| `wio-test-reviewer` | Read-only post-write review that returns `KEEP`, `REDO`, or `REMOVE`. |

The main agent still writes the test and owns the final decision. Subagents
inspect, challenge, and review; they do not duplicate the reference library or
replace the main workflow.

## Repository Layout

| Path | Purpose |
| --- | --- |
| `plugins/wio/skills/wio/SKILL.md` | Source of truth for the skill workflow. |
| `plugins/wio/skills/wio/references/` | Detailed testing guidance loaded only when relevant. |
| `plugins/wio/skills/workload-harness/` | Thin authoring workflow, scaffold, checker, and SDK references for the deterministic harness. |
| `plugins/wio/agents/` | Claude Code plugin subagents. |
| `.codex/agents/` | Codex custom-agent TOML files for project or user installs. |
| `plugins/wio/hooks/hooks.json` | Shared plugin hook config. |
| `.agents/plugins/marketplace.json` | Codex marketplace entry. |
| `.claude-plugin/marketplace.json` | Claude Code marketplace entry. |
| `public/` | README assets, demo GIF, and agent icons. |

## Codex Agents And Hooks

Codex plugin installs include the skills. Codex custom agents and hooks are
separate native surfaces loaded from project or user configuration.

Enable the Codex agents globally:

```bash
mkdir -p ~/.codex/agents
cp .codex/agents/wio-*.toml ~/.codex/agents/
```

Enable the Codex agents for the current project:

```bash
mkdir -p .codex/agents
cp /path/to/wio-skills/.codex/agents/wio-*.toml .codex/agents/
```

Enable the Codex hook config for the current project:

```bash
mkdir -p .codex
cp /path/to/wio-skills/.codex/hooks.json .codex/hooks.json
```

## Claude Code Agents And Hooks

Claude plugin installs include the skill, plugin hooks, and Markdown
subagents from `plugins/wio/agents/`. Project-local Claude Code agents can also
be copied into `.claude/agents/` when a repository is not using the plugin.

## References

Detailed testing guidance lives only in
`plugins/wio/skills/wio/references/`. Reference topics cover behavior mapping,
risk-based testing, test levels, workload modeling, oracles, fixtures, mocks,
suite health, static analysis, security testing, fuzzing, property-based
testing, mutation testing, performance testing, resilience testing, and
regression selection.

## Contributing

Keep the public surface area small: the general `wio` skill with command modes
`scan`, `test`, `workload`, `review`, and `doctor`, plus the thin
`workload-harness` model-authoring skill.

Detailed testing guidance belongs in
`plugins/wio/skills/wio/references/`, not duplicated inside cloud folders,
subagents, hooks, or extra skill trees. When adding a reference topic, add both
`overview.md` and `tools.md`, then link it from
`plugins/wio/skills/wio/references/index.md`.

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution workflow and release
expectations.

## License

MIT. See [LICENSE](LICENSE).
