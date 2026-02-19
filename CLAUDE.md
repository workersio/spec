# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository

https://github.com/workersio/spec

## What This Project Does

A collection of Claude Code plugins by workers.io. Each plugin is a self-contained directory under `plugins/` with a manifest and one or more skills. The root `.claude-plugin/marketplace.json` catalogs all plugins for marketplace discovery.

## Plugins

### save-spec (`plugins/save-spec/`)

Converts Claude Code conversations into reusable agents. Analyzes the current session and distills it into an agent file saved to `.claude/agents/{name}.md`, invocable via `@{name}`.

- **Skill**: `skills/save/SKILL.md` (`/save-spec:save`)
- **Manifest**: `plugins/save-spec/.claude-plugin/plugin.json`

The skill embeds the prompt template directly in SKILL.md. It runs inline in Claude Code -- no binary, no subprocess.

## Architecture

```
.claude-plugin/marketplace.json    # Root marketplace catalog (all plugins)
plugins/
  <plugin-name>/
    .claude-plugin/plugin.json     # Plugin manifest
    skills/
      <skill-name>/SKILL.md        # Skill definition
```

Each plugin is independent. To add a new plugin, create its directory under `plugins/`, add a manifest, define its skills, and register it in the root `marketplace.json`.
