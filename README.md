# workers.io plugins

A collection of Claude Code plugins by [workers.io](https://workers.io). Each plugin is self-contained, zero-dependency, and installs natively into Claude Code.

---

## Plugins

### save-spec

Converts Claude Code conversations into reusable agents. The plugin analyzes your session -- the original task, every correction you made, tool calls, and the final output -- and distills it into an agent file saved to `.claude/agents/`. Agents are invocable with `@agent-name` in any future conversation and shared through version control. No server, no API, no accounts.

**Skill**: `/save-spec:save`

#### Install from the marketplace

```
/plugin marketplace add workersio/spec
/plugin install save-spec@workers-spec
```

#### Install from a local clone

```bash
git clone https://github.com/workersio/spec.git
```

Then in Claude Code:

```
/plugin install /path/to/spec/plugins/save-spec
```

---

## Repository structure

```
plugins/
  save-spec/                     # Convert sessions into reusable agents
    .claude-plugin/plugin.json
    skills/
      save/SKILL.md              # /save-spec:save
```

Each plugin lives under `plugins/` with its own `.claude-plugin/plugin.json` manifest and `skills/` directory. The root `.claude-plugin/marketplace.json` catalogs all plugins for marketplace discovery.

---

## License

MIT
