---
description: Share this session as a reusable agent
disable-model-invocation: true
allowed-tools: Bash(curl *), Bash(jq *), Write(/tmp/spec-upload-*)
---

# Share Session as Agent

Generate a reusable agent file from the current conversation and upload it to the spec server.

## Instructions

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

### Step 2: Upload the agent file

After generating the agent file content (starting with `---`):

1. Write the agent file content to a temp file:
   ```
   /tmp/spec-upload-{timestamp}.md
   ```

2. Upload using curl with proper JSON encoding:
   ```bash
   jq -n --rawfile content /tmp/spec-upload-{timestamp}.md '{"content": $content}' | \
     curl -s -X POST "${WORKERS_SPEC_API_URL:-https://spec.workers.io}/api/specs" \
       -H "Content-Type: application/json" -d @-
   ```

3. Parse the JSON response to extract the URL. The response format is:
   ```json
   {"id": "abc123", "url": "https://spec.workers.io/s/abc123"}
   ```

4. Clean up the temp file.

### Step 3: Display the result

Show the user the share URL. Suggest they can save it locally with `/spec:save <url>` to use it as an agent.
