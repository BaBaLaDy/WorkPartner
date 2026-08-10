---
name: example
description: Use this skill when the user wants to see a demonstration of how WorkPartner skills work, or asks for an example/template skill. Shows the SKILL.md format and the two-level injection mechanism.
license: MIT
---

# Example Skill

This is a template skill demonstrating the WorkPartner skill format.
Use it as a starting point when creating your own skills.

## Skill anatomy

```
skills/
  my-skill/
    SKILL.md          # this file — YAML frontmatter + instructions
    scripts/          # optional: executable helper scripts
    references/       # optional: detailed docs loaded on-demand
```

## Frontmatter fields

| Field | Required | Purpose |
|-------|----------|---------|
| `name` | yes | Must match the folder name |
| `description` | yes | Tells the agent when to load this skill — write it like a trigger condition |
| `license` | no | License of this skill's content |
| `allowed-tools` | no | Tools this skill is allowed to use |
| `user-invocable` | no | Whether users can invoke it directly (default: true) |

## How matching works

1. **L1 — metadata**: skill name + description always live in the system
   prompt, so the agent knows what exists.
2. **L2 — full body**: loaded only on an explicit mention, e.g.
   "use the example skill", "用example这个skill", or "/example".
   Keyword-only messages ("show me an example") do NOT auto-load the body —
   the model decides whether to read it.

## Try it

Ask the agent: *"use the example skill to explain itself"* — the full body
of this file will be injected into the conversation.
