# Agent tooling and MCP policy

> The single source of truth for what the agent may reach in this engagement.

## Client consent
- AI-assisted development permitted: yes — recorded 2026-10-29, by volodymyr, during `/setup-project`.
- Restrictions the client asked for: none. This is an internal starter base, not a client engagement; revisit once a POC is forked for a client.

## Active MCP servers
| Server | Purpose | Data it can reach | Scope/permissions | Approved by | Rotate/expire |
|--------|---------|-------------------|-------------------|-------------|---------------|
| context7 | library docs | none (library names only) | read | internal | — |
| serena | code navigation | this repo, locally | read | internal | — |

## Not installed (recommended, needs a human to add)
| Server / plugin | Purpose | Why not on by default |
|-----------------|---------|------------------------|
| `github@claude-plugins-official` | PRs, issues, CI | Recommended for `/review-pr`; install with `claude plugin install github@claude-plugins-official`, then add it to the table above. |

There is no Jira or other tracker server: the plan is the "Scope Breakdown" doc, read through the Claude Docs connector in the user's own session.

## Forbidden here
- Production databases, production credentials, production deploys (rule C5) — none exist.
- Any server not listed above.
- Shared service accounts for OAuth servers — each developer authenticates as themselves.

## Notes
- Keep ≤5 active servers per session; disable what the current task does not need.
- Prefer an already-installed CLI over an MCP server when both do the job.
- Secrets only via `${ENV_VAR}` in `.mcp.json`. Never inline.
