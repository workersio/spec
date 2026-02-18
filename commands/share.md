---
description: Share this session as a replayable spec
allowed-tools: Bash(workers-spec *), Read(/tmp/workers-spec-result.txt)
---

Share the current Claude Code session as a replayable specification.

Pipe the output to a file (takes about 60 seconds):

```
workers-spec share ${CLAUDE_SESSION_ID} > /tmp/workers-spec-result.txt 2>/dev/null
```

Then read `/tmp/workers-spec-result.txt` to get the URL.

Display the URL to the user. Suggest they can share it with others using `/run <url>`.
