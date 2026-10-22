# TaskFlow MCP Server — Documentation

This folder contains two types of documents:

1. **User / Operator Guides** — from installation to operations. These are the link targets from the README.
2. **Design Documents** (`00~03`) — product-level specs for alignment before implementation.

## User · Operator Guides

| Document | Contents |
|---|---|
| [getting-started.en.md](./getting-started.en.md) | Installation · First job · Step working directory (`cwd`) |
| [artifacts.en.md](./artifacts.en.md) | Upload · Declaring aliases on a Job · `ARTIFACT_*` in steps · Version pinning |
| [artifact-jobs.en.md](./artifact-jobs.en.md) | Authoring Jobs that use artifacts · verdicts/failure handling · anti-patterns |
| [run-params.en.md](./run-params.en.md) | Passing values at trigger time (e.g. a branch) · declaring on a Job · `PARAM_*` in steps |
| [run-outputs.en.md](./run-outputs.en.md) | Steps record values on the run with `::output key=value` · reading the last successful run |
| [mcp-api.en.md](./mcp-api.en.md) | Issue key · JSON-RPC calls · Tool list · Claude Desktop |
| [rest-api.en.md](./rest-api.en.md) | Endpoints · SSE event format · Error codes |
| [operations.en.md](./operations.en.md) | Run modes (A/B/C) · Network binding · Production release · Env vars |
| [security.en.md](./security.en.md) | `shell=False` · Controlled cwd · `SECRET_*`/reserved env vars · hash-chained audit |
| [troubleshooting.en.md](./troubleshooting.en.md) | Common symptoms and solutions |

## Design Documents

Product-level documents for alignment before implementation. Visual UI/UX details and items directly verifiable from the codebase (data models, screen layouts, etc.) are not covered. They describe the target product, so some items are not implemented yet — those are marked "구현 현황 (implementation status)" in place. Where a design doc and the user guides above disagree, the guides (and the code) describe current behaviour.

| # | File | Contents |
|---|---|---|
| 00 | [overview.md](./00-overview.md) | Project mission · Personas · Use cases · Scope / non-goals |
| 01 | [design-goals.md](./01-design-goals.md) | Product design principles (AI Agent First · Deterministic · Audit, etc.) · Success criteria · Trade-offs |
| 02 | [business-rules.md](./02-business-rules.md) | Domain rules · State transitions · §10 AI Agent end-to-end flow |
| 03 | [system-spec.md](./03-system-spec.md) | System architecture · §2 MCP Tools · Execution contract · Response schema · Security/ops |

## Not Covered

| Item | Reference |
|---|---|
| Visual UI/UX · Components · Tokens | Prototype (`TaskFlow Prototype.html` + `proto/theme.css`, `proto/**/*.jsx`) |
| Per-screen layouts | Prototype `proto/screens/*.jsx` |
| Data models · Seed data | Prototype `proto/store.jsx` (actual implementation starts with empty DB) |
| Design history | `chats/chat1.md` (Claude Design handoff bundle) |
