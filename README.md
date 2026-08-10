<p align="center">
  <img src="readmeAsset/logo.png" alt="WorkPartner Logo" width="100" />
</p>

<h1 align="center">WorkPartner</h1>

<p align="center">
  Your Personal AI Assistant Team — A "Managed Office" running entirely on your own machine.
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.11+-blue.svg?style=flat-square" alt="Python" /></a>
  <a href="https://github.com/langchain-ai/langgraph"><img src="https://img.shields.io/badge/LangGraph-1.0%2B-green.svg?style=flat-square" alt="LangGraph" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square" alt="License" /></a>
  <a href="https://github.com/BaBaLaDy/WorkPartner/stargazers"><img src="https://img.shields.io/github/stars/BaBaLaDy/WorkPartner?style=flat-square&label=Stars" alt="Stars" /></a>
</p>

<p align="center">
  <a href="readmeAsset/README-zh.md">简体中文</a>
</p>

---

## 🎯 What is WorkPartner?

<p align="center">
  <img src="readmeAsset/img1.png" alt="WorkPartner Banner" width="80%" />
</p>

WorkPartner is **not just a chatbot** — it's a **private AI assistant team** orchestrated by a "Supervisor," running entirely on your own machine. You only need to state the result. The rest — task decomposition, scheduling, execution, and final delivery — is handled entirely by your team.

Built on [LangGraph](https://github.com/langchain-ai/langgraph), it features personified personalities, specialized team members, and a complete memory + emotional awareness system.

---

## ✨ Highlights

### 👥 Personified Team Collaboration

No longer fighting alone. WorkPartner brings you a complete "Office":

| Role | Persona | Responsibility |
|------|---------|---------------|
| **Supervisor** | Your Chief of Staff | Status reporting, quality review, learning, IM notifications |
| **Task Agent** | Your Personal Butler | Understands intent, decomposes tasks, dispatches experts |
| **Lin Che** | Researcher | Information search, fact-checking, competitive analysis |
| **Zhou Jian** | Reporter | Organizing reports, writing summaries, risk assessment |
| **Shen Heng** | Executor | File operations, code execution, data processing |

### 💡 Emotional & Memory System

- **Emotional Awareness** — Reads your fatigue or joy and adjusts its tone accordingly
- **Long-term Memory** — Remembers your preferences, project context, and habits
- **"Thinking Out Loud"** — See every step of the agent's workflow in real-time via `<thinking>` protocol
- **Auto Quality Check** — Supervisor reviews completed tasks; auto-retries if quality fails

### 🏢 Office Semantic Layer

- **Office State API** — Real-time awareness of "who's busy, what needs attention, office mood"
- **Event Narrative** — Transforms raw events into natural-language "hallway messages"
- **Collaboration Visibility** — Task flow, role handovers, and process feedback all observable
- **Task Pin Board** — Completed tasks automatically generate pins with AI summaries, displayed on the homepage for at-a-glance review. Click into any pin to continue the conversation or view the full session timeline.

### 🛠️ 30+ Built-in Tools

Desktop control · Code execution · Web search · Task & cron management · Sub-agent dispatch · IM notifications · And more

### 🌐 Multiple Access Channels

| Channel | Description |
|---------|-------------|
| **Web UI** | Warm "Office-style" interface with real-time team status |
| **CLI** | Terminal-based interactive chat with session management |
| **IM Bridge** | Feishu & Telegram integration — command your team from anywhere |
| **Daemon Mode** | Background task execution with auto-retry and concurrency control |

---

## 🖼️ Interface Preview

<p align="center">
  <img src="readmeAsset/img2.png" alt="WorkPartner Web UI" width="90%" />
</p>

<p align="center"><em>The "Office at a glance" — monitor your team members' status in real-time.</em></p>

---

## 🏗️ Architecture

WorkPartner uses a layered architecture to ensure stability and scalability:

```
┌──────────────────────────────────────────────────────────┐
│                    Entry Layer                            │
│   Web UI  │  CLI  │  IM Bridge  │  Daemon                │
├──────────────────────┬───────────────────────────────────┤
│              WorkPartnerEngine (Facade)                   │
│  Session │ Model Router │ Tool Registry │ Memory Manager  │
│  MCP │ Skill Manager │ EventBus │ Supervisor              │
├──────────────────────┬───────────────────────────────────┤
│         LangGraph State Graph                             │
│  pre → chat → tools → END                                │
└──────────────────────┬───────────────────────────────────┘
                       │
         ┌─────────────┴─────────────┐
         │   PromptAssembler          │
         │  interactive / managed /    │
         │  subagent / supervisor      │
         └─────────────────────────────┘
```

### State Graph

```
START → pre → should_compress? ──yes──→ compress → chat
                    │                               ↑
                    no                              │
                    │                               │
                    ▼                               │
                  chat → has_tool_calls ──tools──→ pre
                            │
                            no tool calls
                            │
                            ▼
                         respond → END
```

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+ (for frontend development)
- API Keys (DashScope, Ark, etc.)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/BaBaLaDy/WorkPartner.git
cd WorkPartner

# 2. Create environment and install dependencies
conda create -n workpartner python=3.11
conda activate workpartner
pip install -r requirements.txt

# 3. Configure environment variables
cp .env.example .env
# Edit .env to fill in your API Keys
```

### Configuration

**Step 1 — Set API Keys in `.env`:**

```env
# DashScope (Qwen models) — required
DASHSCOPE_API_KEY=your_dashscope_key_here

# Ark (ByteDance Doubao vision model) — required for desktop control
ARK_API_KEY=your_ark_key_here

# Feishu (optional, for IM bridge)
FEISHU_APP_ID=your_app_id
FEISHU_APP_SECRET=your_app_secret
FEISHU_MY_OPEN_ID=your_feishu_open_id

# Telegram (optional, for IM bridge)
TELEGRAM_BOT_TOKEN=your_bot_token
```

**Step 2 — Configure models in `config.yaml`:**

```yaml
providers:
  default: "openai"
  openai:
    api_key: "${DASHSCOPE_API_KEY}"
    model: "qwen3.6-plus"
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"

models:
  chat:
    provider: "openai"
    model: "qwen3.6-plus"
  vision:
    provider: "openai"
    model: "doubao-seed-2-0-lite-260215"
    base_url: "https://ark.cn-beijing.volces.com/api/v3"
    api_key: "${ARK_API_KEY}"
```

> `config.yaml` supports `${ENV_VAR}` syntax — values are resolved from `.env` at startup.

### Running

Start the backend and frontend (two terminals):

```bash
# Terminal 1 — Backend (FastAPI on port 8000)
conda run -n workpartner python -m src.api.dev
```

```bash
# Terminal 2 — Frontend (Vite on port 5173)
cd src/frontend/web && npm run dev
```

Then open http://localhost:5173 in your browser.

---

## 📖 Documentation

| Section | Description |
|---------|-------------|
| [Features](#features) | Core agent, 30+ tools, desktop control, skill system |
| [Configuration](#configuration) | Environment variables, config.yaml reference |
| [Skill System](#skill-system) | Create and extend capabilities with SKILL.md |
| [Memory System](#memory-system) | Layered memory injection by session type |
| [Development](#development) | Running tests, adding tools/skills, frontend dev |

---

## Features

### Core Agent

- **LangGraph State Graph** — Typed state machine with condition edges for tool routing and context compression
- **Streaming Responses** — Real-time token streaming with `<thinking>` protocol for reasoning visibility
- **Session Persistence** — All conversations persisted via `SqliteSaver`, auto-resume on restart
- **Multi-Model Routing** — Routes tasks to purpose-specific models (chat/utility/vision) for cost optimization
- **Session Types** — `interactive`, `managed`, `subagent`, `supervisor` — each with tailored system prompts and memory injection
- **Unified Prompt Assembly** — `PromptAssembler` module shares a single assembly pipeline across all 4 session profiles with cache-aware section ordering

### Tool Categories

| Category | Examples |
|----------|----------|
| File | `file_read`, `file_write`, `file_patch` |
| Code | `code_run` — Execute Python/Shell with timeout |
| Web | `web_search`, `web_extract` |
| Task | `todo_add`, `todo_list`, `todo_update`, `todo_delete` |
| Schedule | `cron_add`, `cron_list`, `cron_pause`, `cron_resume` |
| Desktop | Screenshot, click, move, drag, scroll, type, window management |
| Sub-Agent | `subagent_batch` — Parallel dispatch with independent context |
| IM | `im_notify` — Send to Feishu/Telegram |

### Desktop Control (Windows)

- Full-screen or region screenshot with coordinate grid overlay
- Precise mouse click, move, drag, scroll
- Keyboard input (ASCII char-by-char, non-ASCII via clipboard paste)
- Key combinations (e.g., `ctrl+c`, `win+e`)
- Window management — list all windows, focus by title
- **Vision Model Integration** — Dedicated vision model reads UI element coordinates from screenshots
- **FAILSAFE** — Move mouse to (0,0) corner to abort any operation

### Multi-Model Routing

| Route | Purpose | Default Model |
|-------|---------|---------------|
| `chat` | Main dialogue, complex reasoning | qwen3.6-plus |
| `utility` | Lightweight tasks (cheap & fast) | qwen3.6-plus |
| `utility_large` | Summaries, memory distillation | qwen3.6-plus |
| `vision` | Image understanding (desktop control) | doubao-seed-2-0-lite |

Each route can use a different provider, routing lightweight tasks to cheaper models to significantly reduce cost.

### Skill System

Skills extend the agent's domain-specific capabilities via simple Markdown files:

```
skills/
  my-skill/
    SKILL.md          # YAML frontmatter + instructions
    scripts/          # Optional: executable scripts
    references/       # Optional: detailed documentation
```

- **SKILL.md Standard** — YAML frontmatter with name, description, allowed-tools
- **Two-Level Injection** — L1 metadata always in system prompt, L2 full instructions on explicit trigger
- **Bilingual Matching** — Supports Chinese and English skill name recognition

### Memory System

**Principle: "No Execution, No Memory"** — only verified information via tool execution is persisted.

| File | Purpose | Update Trigger |
|------|---------|----------------|
| `execution_log.jsonl` | Append-only task completions/failures | Auto (no LLM) |
| `patterns.md` | Cross-day distilled SOPs | LLM (utility_large) |
| `user_prefs.md` | User preferences | Manual edit |
| `today.md` | Interactive session summaries | On session close |

**Layered Injection by Session Type:**

| Layer | Interactive | Managed |
|-------|:-----------:|:-------:|
| `user_prefs.md` | ✅ | ❌ |
| `today.md` | ✅ | ❌ |
| `patterns.md` | ❌ | ✅ |
| `execution_log` | ❌ | ✅ |

### Background Execution (Daemon)

- `--daemon` flag starts background task polling, no UI required
- Polls for pending tasks every 30 minutes (configurable)
- **Concurrency Control** — Up to N parallel tasks
- **Auto-Retry** — Failed tasks retry up to 3 times with exponential backoff
- **Event Bus** — Task lifecycle events for cross-component communication

### IM Bridge

| Platform | Features |
|----------|----------|
| **Feishu/Lark** | WebSocket or HTTP Webhook, rich text/image/file/voice, group @mention |
| **Telegram** | Long polling or Webhook, MarkdownV2, media download, bot commands |

- **Per-Session Thread Routing** — Each IM chat maps to an independent LangGraph thread
- **Message Deduplication** — TTL-based dedup to prevent double processing
- **Policy Control** — DM/group access policies (open / allowlist / disabled)

### Supervisor Agent

- **Daily Reports** — Scheduled daily summary of work completed and pending items
- **Quality Checks** — Heuristic-based review of completed task outputs
- **Auto-Retry** — Auto-retries up to 2 times on quality failure
- **Experience Learning** — Distills scheduling patterns from successful sessions
- **Action Item Tracking** — Extract and surface follow-up actions
- **Chat Capability** — Chat directly with the Supervisor; ask "what did we do today" or "how's the team doing"
- **Pin Summaries** — On task completion, asynchronously generates a concise summary and writes it as a "pin" for at-a-glance review on the homepage

### MCP Integration

- **Dynamic Tool Injection** — Connect to MCP servers at runtime for additional capabilities
- **Auto-Connect** — Configurable MCP servers auto-connect on startup
- **Tool Prefixing** — MCP tools namespaced with `mcp_` prefix to avoid conflicts

---

## Project Structure

```
├── src/
│   ├── main.py                    # CLI entry point
│   ├── agent/                     # LangGraph session, graph, nodes, edges
│   │   ├── prompt/                # PromptAssembler — unified prompt assembly
│   │   ├── nodes/                 # Graph nodes (chat, tools, compress)
│   │   └── edges/                 # Conditional edge logic
│   ├── core/                      # Engine, background executor, supervisor, pin summarizer
│   ├── hub/                       # Event bus (pub/sub)
│   ├── memory/                    # Memory manager — layered injection
│   ├── narrative/                 # Event narrative — raw events → hallway messages
│   ├── providers/                 # LLM provider factory and router
│   ├── roles/                     # Role definition loader
│   ├── services/                  # Thread-safe service wrappers
│   ├── skills/                    # Skill loader and injector
│   ├── tasks/                     # Task and scheduler manager
│   ├── tools/                     # Tool registry and implementations
│   ├── mcp/                       # MCP client — dynamic tool injection
│   ├── api/                       # FastAPI REST + WebSocket API
│   │   └── routes/                # Routes (chat, office_state, roles, pins...)
│   ├── im_bridge/                 # Feishu & Telegram adapters
│   └── frontend/web/              # React + TypeScript Web UI
├── skills/                        # Installed skill directories
├── memory/                        # Persistent memory files
├── history/                       # Session checkpoints (SqliteSaver)
├── roles/                         # Role definitions (YAML frontmatter + Markdown)
├── config.yaml                    # Agent configuration
├── .env.example                   # Environment variable template
└── requirements.txt               # Python dependencies
```

---

## Configuration

### Environment Variables

| Variable | Description |
|----------|-------------|
| `DASHSCOPE_API_KEY` | DashScope (Qwen) API key |
| `ARK_API_KEY` | Ark (ByteDance Doubao) vision model API key |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token |
| `FEISHU_APP_ID` | Feishu App ID |
| `FEISHU_APP_SECRET` | Feishu App Secret |

### config.yaml Sections

| Section | Description |
|---------|-------------|
| `agent` | Name, max turns, compression threshold |
| `providers` | LLM providers (API key, base_url, model, max_tokens, temperature) |
| `models` | Per-purpose model routing (chat / utility / utility_large / vision) |
| `desktop` | Grid spacing, fail_safe, DPI awareness, vision model |
| `skills` | Skill directory, auto-load toggle |
| `tools` | Enabled tool list |
| `executor` | Poll interval, max concurrent tasks, max retries |
| `supervisor` | Daily report time, quality check mode |
| `im_bridge` | IM adapter config (Feishu, Telegram) |
| `mcp` | MCP client settings (auto-connect, tool prefix) |

See `config.yaml` for full reference.

---

## Usage

### Web Interface

| Tab | Function |
|-----|----------|
| **Chat** | Interactive dialogue — streaming responses, tool call visualization. Split into Free Chat and Task Chat tabs. |
| **Tasks** | Create/update/delete tasks, track execution status |
| **Schedule** | Create/pause/resume/delete cron jobs |
| **Timeline** | Visual timeline of scheduled task executions |
| **Sessions** | Browse past conversations |
| **Settings** | Model selection, tool toggles, IM channels |
| **Team** | Homepage with task pin board — AI-generated summaries at a glance, click to review details or continue chatting. Toggle between animation and pin board views. |

### CLI Commands

| Command | Description |
|---------|-------------|
| `/sessions` | List all sessions |
| `/switch <name>` | Switch to a session |
| `/new <name>` | Create a new session |
| `/delete <name>` | Delete a session |
| `/clear-reset` | Reset agent graph (history preserved) |
| `/exit` | Exit |

---

## Development

### Running Tests

```bash
pip install -r requirements-dev.txt
conda run -n workpartner pytest tests/
conda run -n workpartner pytest tests/ --cov=src --cov-report=term-missing
```

### Adding a New Tool

```python
from src.tools.registry import ToolRegistry

registry = ToolRegistry()

@registry.register(
    name="my_tool",
    description="Description of what this tool does.",
)
def my_tool(param: str) -> str:
    """Tool implementation."""
    return f"Result: {param}"
```

Then add `my_tool` to `tools.enabled` in `config.yaml`.

### Frontend Development

```bash
cd src/frontend/web
npm run dev     # Vite dev server with hot reload
npm run build   # Build production static files
npm run lint    # Run ESLint
```

---

## Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| 1-4 | ✅ | Core state, session types, background execution kernel |
| 5 | ✅ | Multi-model routing, pytest, tool schema |
| 6 | ✅ | React Web frontend (Chat / Tasks / Schedule / Timeline) |
| 7 | ✅ | SubAgent parallel execution |
| 8 | ✅ | Memory system (execution_log + patterns + user_prefs) |
| 9 | ✅ | Desktop control + MCP integration |
| 10 | ✅ | IM bridge (Feishu / Telegram) |
| 11 | ✅ | Supervisor agent + daily reports + quality checks |
| 12 | ✅ | Unified prompt assembly (PromptAssembler) + cache optimization |
| 13 | ✅ | Office semantic layer (state API + event narrative) |
| 14+ | 📋 | Role persona contract, emotional memory, plugin system |
| 15 | ✅ | Task pin board — auto-generated summaries, at-a-glance review, inline follow-up |

---

## ⚠️ Security Notice — Please Read Before Deploying

WorkPartner is a **personal assistant that acts with your own permissions**. By design it can:

- **Execute arbitrary code** on your machine (`code_run` tool)
- **Control your desktop** — mouse, keyboard, screenshots (`desktop_*` tools)
- **Read and write any file** your user account can access (`file_*` tools)

This is the whole point of the project, but it also means you should:

1. **Run it only on machines you trust**, and think twice before letting IM channels trigger tasks unattended.
2. **Keep the API server local.** It has no authentication and binds to `127.0.0.1` by default — do not expose port 8000 to the network.
3. **Never commit your `.env`.** Copy `.env.example` and keep real keys local.
4. **Configure IM access policies.** If you enable the Feishu/Telegram bridge, DMs default to `allowlist` — add your own user ID to `allow_from` in `config.yaml` first. An "open" group policy lets anyone who @mentions the bot give it commands.
5. **Feishu webhook mode:** if the webhook endpoint must be publicly reachable, put it behind a reverse proxy with HTTPS and set `FEISHU_VERIFY_TOKEN` so forged events are rejected.

---

## License

[MIT](LICENSE)
