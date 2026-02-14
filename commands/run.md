---
description: Run a shared spec from a URL
argument-hint: <url>
allowed-tools: Bash(workers-spec:*)
---

Fetch and execute a shared specification.

1. Run `workers-spec run $ARGUMENTS` to get a preview of the spec
2. Show the preview output to the user (title, description, sections)
3. Ask the user: "Run this spec? (y/n)"
4. If confirmed, run `workers-spec run $ARGUMENTS --full` to get the complete spec content
5. Take the full output and execute it as instructions in this session
