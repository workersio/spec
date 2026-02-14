You are given a raw Claude Code session transcript below.

Generate a reusable specification based on this session. Output ONLY the spec content — no explanation, no code fences, no preamble.

---

# Specification Generation

Analyze the entire session — the original task, every user correction, every tool call, and the final output — then distill it into a generalizable specification. The spec is NOT a session log. It is a standalone prompt that a fresh agent will receive with no prior context.

Key priorities:
1. User corrections are the most important signal. Every correction implies a requirement the agent got wrong initially. Each correction MUST become an explicit requirement with SHALL/MUST language.
2. Methodology MUST reflect what actually worked, not initial failed attempts. If approach A failed and approach B worked — only document approach B.
3. Generalize — replace session-specific values (file names, URLs, credentials) with descriptive placeholders. The spec must work for similar tasks, not just this exact one.
4. Keep it concise — this will be used as a one-shot prompt. A future agent receives this text and must be able to execute without further guidance.

---

## Output Format

Output the spec with YAML frontmatter (metadata) followed by markdown body (task):

```
---
title: "<short name, max 100 chars>"
description: "<one-liner, max 200 chars>"
tags: ["<tag1>", "<tag2>", "<tag3>"]
---

## Objective

<One paragraph: what this task accomplishes and why.>

## Requirements

### Requirement: <descriptive name>

The agent SHALL/MUST <specific behavior>.

#### Scenario: <descriptive name>
- **WHEN** <condition or trigger>
- **THEN** <expected outcome or action>

## Methodology

1. <Step that worked>
2. <Step that worked>

## Output Format

<Expected deliverable structure.>

## Quality Criteria

#### Scenario: <descriptive name>
- **WHEN** the output is reviewed
- **THEN** <specific quality check>
```

### Frontmatter Constraints

- `title` — required, max 100 characters (e.g. "Quarterly Financial Verification")
- `description` — required, max 200 characters (e.g. "Verify quarterly report figures against source data")
- `tags` — required, max 5 items, used for filtering and discovery

### Section Constraints

All sections (Objective, Requirements, Methodology, Output Format, Quality Criteria) are required.

- Each requirement MUST contain at least one SHALL or MUST keyword
- Each requirement MUST have at least one Scenario in WHEN/THEN format
- Quality Criteria MUST have at least one Scenario in WHEN/THEN format

---

## Rules

- Every requirement MUST use the keyword SHALL or MUST to indicate obligation
- Every requirement MUST have at least one Scenario with WHEN/THEN format
- Scenarios MUST use exactly `####` (four hashes) for their heading level
- User corrections from the session MUST become explicit requirements
- Be specific — "The agent MUST use openpyxl for Excel files" not "The agent MUST use the right tool"
- Do NOT include session-specific details (specific file names, URLs, credentials, data values from this run)
- DO generalize patterns — replace specific values with descriptive placeholders like `<input-file>`, `<target-url>`
- Methodology MUST only include steps that succeeded, not failed attempts
- If no user corrections occurred, focus on capturing the methodology and output format as requirements
- The spec MUST be self-contained — a future agent needs nothing beyond this spec and the input files

---

Output ONLY the specification content starting with `---` (the YAML frontmatter). No other text.

## Session Transcript

{transcript}
