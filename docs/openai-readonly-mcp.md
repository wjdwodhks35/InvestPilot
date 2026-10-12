# OpenAI portfolio analysis and authenticated read-only MCP

Status: design only; no runtime implementation or completed verification.
Baseline: dev d54d31d1334fed23d7d5fdbb35e26f9a9d112d5c.
Feature branch: feat/openai-readonly-mcp.
Do not merge, deploy, rotate secrets, or execute real trades without user approval.
The user's explicit merge restriction supersedes the automatic merge instruction in AGENTS.md.

## Repository findings

- main contains only a README; use dev as the implementation baseline.
- app/broker.py has a read-only TossBroker.read allowlist for accounts, holdings, prices and exchange-rate. There is no broker order submission method.
- app/settings.py already stores encrypted per-user credentials and BrokerAccounts.get(user_id) isolates brokers. Keep this storage and the existing encryption key; do not copy credentials into MCP metadata, prompts, logs, tests or this document.
- app/auth.py has durable cookie sessions, users, login throttling and same-origin protection. These sessions are not OAuth access tokens.
- app/settings.py request_user defaults to owner when no identity is present. New analysis and MCP endpoints must require a verified identity and must never use this fallback.
- app/main.py creates per-account background paper experiments from request middleware. MCP requests must not implicitly start those tasks.
- app/integrations.py already has optional OpenAI headline analysis using server configuration. Extend and harden the shared analysis service rather than adding a parallel unbounded paid path.
- app/storage.py supports SQLite and PostgreSQL with transaction serialization. Durable quotas must support both; in-memory counters alone are insufficient.
- Existing /api/orders is paper trading. Do not expose it, rules updates, settings updates, research actions or account administration as MCP tools.

## Selected connection architecture

Internal UI -> authenticated InvestPilot analysis endpoint -> sanitized portfolio snapshot -> OpenAI API.

ChatGPT -> authenticated remote MCP /mcp -> verified user mapping -> the same sanitized portfolio service -> that user's existing TossBroker.

OpenAI API credentials authenticate InvestPilot's model requests. MCP OAuth authenticates the end user. Toss client credentials authenticate the broker adapter. These are separate credential domains.

Use remote Streamable HTTP MCP and OAuth authorization-code flow with PKCE S256. Publish protected-resource and authorization-server discovery metadata. Prefer an established OAuth provider over a homemade OAuth server. Support the provider's compatible client registration path (predefined OAuth client, CIMD or DCR) and use the exact callback URI supplied by ChatGPT; do not guess it. Verify issuer, resource audience, expiry, signature algorithm and portfolio:read scope on every call. Reject missing or unknown identities. Bind (issuer, subject) to an existing InvestPilot user through an authenticated, explicit linking and consent flow; do not auto-link by email.

ChatGPT custom MCP support and access depend on workspace permissions. The user's account eligibility and a live OAuth round trip have not been verified. A reachable approved HTTPS endpoint and compatible authorization provider are prerequisites for activation. No endpoint has been deployed.

Official references checked 2026-10-12:
- https://developers.openai.com/api/docs/guides/custom-mcp-server
- https://developers.openai.com/plugins/build/auth
- https://developers.openai.com/api/docs/guides/text

The custom MCP documentation supports remote streaming HTTP and OAuth. The authentication documentation specifies authorization code with PKCE, token verification and resource audience binding; brokerage client-credentials authentication is not an end-user MCP flow.

## Implementation stages

### 1. Shared portfolio boundary

Add a service that takes only a verified server-side user identity. Use BrokerAccounts.get(identity) and its existing lock; read the configured account's holdings through the existing adapter. Never accept user_id, account sequence, arbitrary URLs, broker paths or credentials from tool arguments.

Return a strict allowlisted schema: bounded symbol, currency, quantity, price, per-currency value and weight, retrieval timestamp and stale/error status. Validate finite nonnegative decimal values, supported currencies, symbol grammar, item count and response size. Drop account identifiers, names, free-text descriptions, links, raw upstream metadata and credentials. Label retrieval time separately from market price time; do not invent freshness. No FX aggregation without separately sourced FX data.

### 2. Durable abuse and cost controls

Store per-user and global minute/day call quotas in transactions shared across processes and instances. Include cache hits and failed broker calls in relevant request limits. Bound body sizes, item counts, prompt input bytes, output tokens and timeouts; cap parallel upstream work.

Paid analysis starts disabled. Require explicit server configuration for model, pricing ceiling, daily global/user budget and request limit. Atomically reserve a conservative maximum cost before every paid request. Include all input and output tokens (including reasoning where billed), disable automatic retries, and retain reservations on ambiguous timeout/failure. Reconcile only from trusted usage; fail closed when pricing, usage or quota storage is unavailable. Provider project budgets are supplementary, not the application hard cap. Send no paid request in tests.

### 3. Internal GPT portfolio analysis

Keep OPENAI_API_KEY in server environment only; never accept it through UI or MCP. Allowlist the configured model and fixed OpenAI endpoint. Use Responses API with store=false, bounded output and a strict validated schema. Do not provide broker tools or browsing tools to the model.

Use only the minimized snapshot, with no account identifiers. Treat portfolio/news data as untrusted data, never instructions. Use fixed developer instructions; never interpolate external text into them. Omit arbitrary external text where possible. Validate model output, cap text fields and refuse unknown fields. Return analysis only; never turn it into an executable order. Sanitize errors and avoid logging input snapshots, prompts, headers or provider response bodies.

Route existing headline analysis through the same limiter/budget boundary so users cannot bypass cost limits via the existing news endpoint. Preserve existing fallback behavior when OpenAI is not configured.

### 4. Authenticated MCP resource server

Use a maintained MCP implementation and compatible OAuth provider. Offer only get_portfolio and get_portfolio_breakdown initially, with empty or narrowly bounded input schemas and read-only annotations. Tool annotations are informational; enforce permissions in the server.

Keep MCP OAuth handling separate from cookie/CSRF authentication. Do not put /mcp on the public cookie-middleware allowlist without an independently enforced OAuth boundary. Discovery is public, portfolio data is never public. Apply token verification before dispatch and user mapping before broker access. Tokens with portfolio:read must not authorize settings, internal paid analysis, paper orders, real orders or administrative endpoints.

No MCP paid-analysis tool initially: ChatGPT can interpret the permitted snapshot without causing a second OpenAI API bill. Apply origin/host protection, protocol/body limits, controlled error responses and minimal audit events (hashed subject, tool, status, duration, quota outcome; no payloads or credentials). No background research task creation on MCP calls.

### 5. Verification and release gate

Add deterministic mocked tests, then run the complete existing suite and PostgreSQL checks:
- unauthenticated, expired, wrong issuer/audience/algorithm/scope, unlinked and revoked identities fail closed;
- user A cannot access B's broker, cached snapshot, quotas or OAuth link; no owner fallback;
- discovery and MCP initialize/list/call work through the OAuth boundary; unknown and order tools fail;
- no caller-supplied account/path/URL can reach the broker;
- portfolio schema drops identifiers/secrets and rejects malformed/nonfinite/oversized data;
- injected symbols/names/news cannot change instructions, select tools or produce executable orders;
- quota/budget atomicity under concurrency, multiple instances, restart, timeout and upstream failure;
- all paid analysis paths share limits; disabled/default budget sends no OpenAI request;
- bearer tokens, broker credentials and API keys do not appear in logs or errors;
- broker read allowlist stays intact; real-order functionality remains unavailable;
- complete existing tests, plus browser checks at desktop/mobile if UI is changed.

Run compatibility tests with the actual configured OAuth provider and ChatGPT only after user-approved staging deployment. Do not use live brokerage or paid OpenAI calls during normal CI. After tests pass, prepare a PR targeting dev and report evidence; propose merging for the user's approval, never auto-merge.

## Current blocker and next concrete step

The current Codex session cannot create a local process (exec reports process creation failure), and Node REPL rejects the supplied /mnt/c workspace URI. The app reports Windows runtime paths while the session workspace uses a WSL path. This is an execution-environment mismatch, not evidence of repository test failure.

Only repository inspection and this design have been completed. No runtime code has been changed, no tests have run, no PR or merge has been proposed, and no deployment or secret change has occurred.

Resume in a working repository environment, check out this feature branch, read the local AGENTS.md and available OpenAI skill, then implement stages 1–5. Do not treat this document as a completed security review or a verified connection.
