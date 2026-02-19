---
description: Save a session as a reusable agent (or fetch one from a URL)
argument-hint: "[url-or-id]"
disable-model-invocation: true
allowed-tools: Bash(curl *), Bash(jq *), Bash(mkdir *), Write(.claude/agents/*)
---

<!-- NOTE: Generation prompt duplicated in share/SKILL.md. Keep both in sync. -->

# Save Session as Agent

Generate a reusable agent file from the current conversation, or fetch one from a shared URL.

## Instructions

Check `$ARGUMENTS`:
- If **empty** → go to **Mode A** (generate from conversation)
- If **a URL or ID** → go to **Mode B** (fetch from remote)

---

## Mode A: Generate from Conversation

### Step 1: Generate the agent file

Analyze the entire conversation — the original task, every user correction, every tool call, and the final output — then distill it into a reusable agent file. The agent file is NOT a session log. It is a system prompt that a subagent will receive with no prior context.

Key priorities:
1. **User corrections are the most important signal.** Every correction implies a rule the agent got wrong initially. Each correction MUST become an explicit rule.
2. **Only capture what worked.** If approach A failed and approach B worked — only document approach B.
3. **Generalize** — replace session-specific values (file names, URLs, credentials) with descriptive placeholders. The agent must work for similar tasks, not just this exact one.
4. **Keep it concise** — this is a system prompt for a subagent. Shorter is better.

Output the agent file with YAML frontmatter followed by a system prompt body:

```
---
name: "<kebab-case-name>"
description: "<one-liner, max 200 chars>"
tools: Read, Glob, Grep, Bash, Write, Edit
model: sonnet
---

You are an agent that <role description — what this agent does>.

## Behavior

1. <First step the agent should take>
2. <Next step>
3. <...>

## Rules

- <Rule derived from user correction or session learning>
- <Another rule>

## Output

<What the agent should produce — format, structure, location.>
```

#### Frontmatter Constraints

- `name` — required, kebab-case, max 100 characters
- `description` — required, max 200 characters
- `tools` — required, comma-separated list of tools the agent needs (choose from: Read, Glob, Grep, Bash, Write, Edit, WebFetch, WebSearch)
- `model` — required, use `sonnet` unless the task clearly needs stronger reasoning (then use `opus`)

#### Body Constraints

- Start with a one-sentence role description: "You are an agent that..."
- **Behavior** section: numbered steps describing what the agent does, in order
- **Rules** section: bullet list of constraints and guidelines — every user correction from the session MUST appear here
- **Output** section: what the agent produces and in what format
- All sections are required

#### Guidelines

- Write natural language instructions, not formal SHALL/MUST requirements
- Be specific — "Use openpyxl for Excel files" not "Use the right tool"
- Do NOT include session-specific details (specific file names, URLs, credentials, data values from this run)
- DO generalize patterns — replace specific values with descriptive placeholders like `<input-file>`, `<target-url>`
- Only include steps that succeeded, not failed attempts
- The agent file MUST be self-contained — the subagent needs nothing beyond this prompt and its input

### Step 2: Save the agent file

After generating the agent file content (starting with `---`):

1. Extract the `name` from the YAML frontmatter. Use it as the slug directly (it's already kebab-case).

2. Create the `.claude/agents/` directory if it doesn't exist:
   ```bash
   mkdir -p .claude/agents
   ```

3. Write the agent file content to `.claude/agents/{name}.md` using the Write tool.

### Step 3: Display the result

Tell the user the agent was saved to `.claude/agents/{name}.md`. Let them know they can invoke it with `@{name}` in any conversation, or use `/spec:share` to upload and share it.

---

## Mode B: Fetch from URL

### Step 1: Parse the argument

`$ARGUMENTS` is either:
- A full URL like `https://spec.workers.io/s/abc123` — extract the ID (`abc123`) and use the URL's origin as the API base
- A bare ID like `abc123` — use the default API base (see below)

### Step 2: Fetch the spec

```bash
SPEC_API="${WORKERS_SPEC_API_URL:-https://spec.workers.io}"
curl -s "${SPEC_API}/api/specs/${ID}" | jq -r '.content'
```

If the request fails or returns an error, inform the user and stop.

### Step 3: Prepare the agent file

The output from Step 2 is the raw agent/spec content (the `content` field already extracted via `jq`).

Check the frontmatter format:
- If it already has `name:` in the frontmatter → it's already an agent file, use as-is
- If it has `title:` but no `name:` → it's a legacy spec format. Do a lightweight conversion:
  1. Rename `title:` to `name:` (and slugify the value to kebab-case)
  2. Remove the `tags:` line
  3. Add `tools: Read, Glob, Grep, Bash, Write, Edit` after the description line
  4. Add `model: sonnet` after the tools line

### Step 4: Save the agent file

1. Extract the `name` from the (possibly converted) frontmatter.

2. Create the `.claude/agents/` directory if it doesn't exist:
   ```bash
   mkdir -p .claude/agents
   ```

3. Write the content to `.claude/agents/{name}.md` using the Write tool.

### Step 5: Display the result

Tell the user the agent was saved to `.claude/agents/{name}.md`. Let them know they can invoke it with `@{name}`.
