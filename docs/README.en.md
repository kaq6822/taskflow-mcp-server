# TaskFlow MCP Server — Documentation

This folder contains two types of documents:

1. **User / Operator Guides** — from installation to operations. These are the link targets from the README.
2. **Design Documents** (`00~03`) — product-level specs for alignment before implementation.

## User · Operator Guides

| Document | Contents |
|---|---|
| [getting-started.en.md](./getting-started.en.md) | Installation · First job · argv allowlist |
| [mcp-api.en.md](./mcp-api.en.md) | Issue key · JSON-RPC calls · Tool list · Claude Desktop |
| [rest-api.en.md](./rest-api.en.md) | Endpoints · SSE event format · Error codes |
| [operations.en.md](./operations.en.md) | Run modes (A/B/C) · Network binding · Production release · Env vars |
| [security.en.md](./security.en.md) | `shell=False` · allowlist · Secret masking · hash-chained audit |
| [troubleshooting.en.md](./troubleshooting.en.md) | Common symptoms and solutions |

## Design Documents

Product-level documents for alignment before implementation. Visual UI/UX details and items directly verifiable from the codebase (data models, screen layouts, etc.) are not covered.

| # | File | Contents |
|---|---|---|
| 00 | [overview.md](./00-overview.md) | Project mission · Personas · Use cases · Scope / non-goals |
| 01 | [design-goals.md](./01-design-goals.md) | Product design principles (AI Agent First · Deterministic · Audit, etc.) · Success criteria · Trade-offs |
| 02 | [business-rules.md](./02-business-rules.md) | Domain rules · State transitions · §10 AI Agent end-to-end flow |
| 03 | [system-spec.md](./03-system-spec.md) | System architecture · §5 MCP Tools · Execution contract · Response schema · Security/ops |

## Not Covered

| Item | Reference |
|---|---|
| Visual UI/UX · Components · Tokens | Prototype (`TaskFlow Prototype.html` + `proto/theme.css`, `proto/**/*.jsx`) |
| Per-screen layouts | Prototype `proto/screens/*.jsx` |
| Data models · Seed data | Prototype `proto/store.jsx` (actual implementation starts with empty DB) |
| Design history | `chats/chat1.md` (Claude Design handoff bundle) |
