---
description: Save this session as a local spec in .spec/
allowed-tools: Bash(workers-spec *), Read(/tmp/workers-spec-result.txt)
---

Save the current Claude Code session as a local specification file in `.spec/`.

Pipe the output to a file (takes about 60 seconds):

```
workers-spec save ${CLAUDE_SESSION_ID} > /tmp/workers-spec-result.txt 2>&1
```

Then read `/tmp/workers-spec-result.txt` to get the saved file path.

Display the result to the user. Let them know the spec was saved locally and suggest they can use `/share` to upload it instead.
