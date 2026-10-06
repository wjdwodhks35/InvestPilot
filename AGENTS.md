# InvestPilot development workflow

- Start each feature or fix on a new `feat/*` or `fix/*` branch based on `dev`.
- Do not commit feature changes directly to `dev` or `main`.
- Run relevant tests and the complete test suite. For UI changes, also check the changed screen at desktop and mobile widths and exercise its interactions.
- If verification fails, fix the issue before merging. After checks pass, open a PR targeting `dev` and merge it; the user has authorized this development workflow.
- Keep results and private configuration under the Git-ignored `data/` directory. Never commit credentials, account identifiers, or private Drive folder IDs.
- Historical and Ollama tests are paper experiments. Do not connect research actions to broker order submission.
