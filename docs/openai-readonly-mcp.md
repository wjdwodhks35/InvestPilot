# ChatGPT read-only portfolio integration

Scope updated by user: ChatGPT queries InvestPilot through MCP and performs analysis in ChatGPT. No OpenAI API analysis is added; no OPENAI_API_KEY or API credit is required by this server. ChatGPT plan limits and custom MCP access eligibility still apply. Existing internal news-analysis code is outside this new MCP service and may still use API billing if separately configured.

Branch: feat/openai-readonly-mcp, based on dev d54d31d1334fed23d7d5fdbb35e26f9a9d112d5c. Do not auto-merge despite AGENTS.md: the user's explicit approval restriction takes precedence.

## Implementation

- Separate ASGI process in app/mcp_server.py. Uses pinned official MCP Python SDK with stateless Streamable HTTP, OAuth resource metadata and required portfolio:read scope.
- JWT verification through PyJWT and operator-configured HTTPS JWKS: RS256 only, issuer/audience/expiry/issued-at/subject checks and approved OAuth client IDs. Unknown, missing and unlinked identities fail closed. No owner fallback or automatic email matching.
- Durable account consent links and quotas in the existing auth database, supporting SQLite/PostgreSQL transactions. Immediate unlink prevents subsequent tool access without rotating any secret.
- Reuses SettingsStore and BrokerAccounts/TossBroker.read for the authenticated user's saved broker connection. Does not import app.main, start experiments or change broker settings.
- Tools: get_portfolio and get_portfolio_breakdown only. No user/account/path/URL arguments; nonempty tool arguments rejected. No orders, settings, administration or paid-model tools.
- Portfolio output allowlist contains numeric positions, bounded symbols, KRW/USD currency totals and retrieval time. No account identifiers, names, arbitrary descriptions, links or upstream metadata. Retrieval time is explicitly not market price time.
- Limits: 32 KiB request bodies, 2 MB upstream response streams, 200 positions, fixed timeouts, no retries, per-user 20 authenticated requests/minute and 500/day, plus global quota. Global reservation occurs at both gateway and authenticated verification, so authenticated traffic uses two global units. Failed attempts also consume applicable limits.
- No OpenAI request is made by this feature, so its server-side OpenAI API cost cap is zero. No API key is used.
- Tests cover data minimization, malicious text/symbols, malformed amounts, durable concurrent quotas, identity linking/revocation, JWT rejection, SDK initialize/list/call and forbidden arguments/order tools.
- Feature-branch CI runs targeted MCP tests plus existing full-suite, PostgreSQL, browser and Windows jobs. Live ChatGPT/OAuth compatibility remains a separate staging acceptance gate.

## OAuth setup (requires operator configuration; not performed)

Use an established authorization service supporting authorization code + PKCE S256. No OAuth tenant has been created. Verify its discovery metadata, exact issuer, resource audience support and client-registration path in ChatGPT before activation. A predefined client is supported; CIMD/DCR depends on provider support. Use the exact redirect URI supplied by ChatGPT and grant only portfolio:read. Do not share Toss credentials with the OAuth provider or ChatGPT.

Official references checked 2026-10-12:
- https://developers.openai.com/plugins/build/auth
- https://developers.openai.com/api/docs/guides/custom-mcp-server
- https://github.com/modelcontextprotocol/python-sdk/tree/v1.26.0

User authentication and explicit consent occur at the OAuth provider. Before provisioning a link, the operator must verify that the provider subject belongs to the requesting InvestPilot user. Never use user-supplied email as identity proof. Current provisioning is operator-mediated; there is no self-service linking UI or OAuth callback implemented inside InvestPilot.

## Deployment preparation (not authorization to deploy)

Install requirements-mcp.txt in a separate service built from the feature branch after review. Set:
- INVESTPILOT_MCP_ENABLED=true (default disabled)
- INVESTPILOT_MCP_ISSUER: exact HTTPS authorization issuer, including its significant trailing slash
- INVESTPILOT_MCP_JWKS_URL: trusted fixed HTTPS provider JWKS URL
- INVESTPILOT_MCP_RESOURCE: approved HTTPS service URL ending in /mcp
- INVESTPILOT_MCP_CLIENT_IDS: comma-separated approved OAuth client IDs
- Existing INVESTPILOT_AUTH_DB, INVESTPILOT_DATABASE_URL, INVESTPILOT_SETTINGS_KEY and broker environment settings as needed, without altering their values.

Start with: uvicorn app.mcp_server:create_app --factory --host 0.0.0.0 --port $PORT

The MCP process must have access to the same durable auth/settings database as InvestPilot. Separate cloud services cannot share an ephemeral SQLite filesystem. Use the existing PostgreSQL configuration or a reviewed durable storage arrangement. Do not deploy a second service with empty/new user or broker databases and assume it is linked.

For operator provisioning, execute locally on the trusted server after verified consent:
python -m scripts.mcp_access link --username <existing-user> --subject <verified-provider-subject> --consent-confirmed
Revoke immediately with:
python -m scripts.mcp_access revoke --username <existing-user>
Subjects are identity data, not broker account numbers; keep them out of public issues and logs. Avoid putting them in shared shell history. Stored principal keys are hashed; no bearer token is persisted.

Connect ChatGPT to the approved /mcp URL with OAuth after user-approved staging deployment. Confirm discovery, consent, initialize/list, user isolation and revocation from the actual ChatGPT account. HTTPS hostname and Origin are constrained; no anonymous holdings endpoint exists.

## Remaining release gates

Local execution is unavailable in the current Codex environment. GitHub Actions is used for mocked verification; report the actual outcomes before any merge proposal. No real brokerage/OpenAI calls, secret rotation or deployment is authorized. Even after CI passes, provider setup, verified user link, approved deployment and live ChatGPT acceptance are required before calling the integration usable.
