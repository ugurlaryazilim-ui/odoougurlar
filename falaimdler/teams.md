> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Teams

> Create shared workspaces with their own API keys, deployments, and billing. Manage members, roles, and understand how request attribution works.

Teams let multiple people share a single set of API keys, deployed apps, and billing on fal. Instead of each person managing their own [personal account](/documentation/setting-up/accounts-and-identity), a team acts as a shared workspace where everyone operates under the same identity. This is useful whether you are calling [Model APIs](/documentation/model-apis/overview) together or deploying your own models with [Serverless](/documentation/serverless).

Teams can exist on their own (standalone) or as children of an [organization](/documentation/organizations/index). Standalone teams work well for small groups. Organizations add centralized policies, SSO, and cross-team visibility. Each team maintains its own API keys, secrets, deployed apps, and billing, completely separate from any member's personal account. For switching between your personal account and a team, see [Switching Between Accounts](/documentation/setting-up/accounts-and-identity#switching-between-accounts).

## Creating a Team

<Steps>
  <Step title="Open the team menu">
    Click your account name in the top-left of the [Dashboard](https://fal.ai/dashboard) and select **Create Team**.
  </Step>

  <Step title="Name your team">
    Enter a team name. This will be visible to all members.
  </Step>

  <Step title="Start using it">
    You'll be switched to the new team automatically. Create API keys and invite members from here.
  </Step>
</Steps>

## Inviting Members

<Steps>
  <Step title="Go to Members">
    Navigate to [**Dashboard > Members**](https://fal.ai/dashboard/members)
  </Step>

  <Step title="Click Invite">
    Enter the member's email address and select their role.
  </Step>

  <Step title="They accept">
    The invited user receives an email with a link to join your team.
  </Step>
</Steps>

For larger teams, use the bulk invite feature at [**Dashboard > Members > Bulk**](https://fal.ai/dashboard/members/bulk). Upload a CSV with columns:

```
email,role
alice@company.com,admin
bob@company.com,developer
carol@company.com,billing
```

Up to 50 invites can be sent per batch.

## Roles

Each team member is assigned one of three roles that control what they can do in the dashboard. Roles govern dashboard and management access. All team members, regardless of role, can use the team's API keys to call models, deploy apps, and run workloads.

| Role          | What they can do                                                                                                                                |
| ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| **Admin**     | Full team management: create and delete API keys, view billing and invoices, invite members, and change roles.                                  |
| **Developer** | Standard access to team resources. Cannot manage API keys, billing, members, or roles.                                                          |
| **Billing**   | View and manage billing: invoices, payment methods, credit purchases, and usage. Can also view API keys. Cannot invite members or change roles. |

<Tip>
  Start with **Admin** for team leads who need to manage keys and members. Use **Developer** for engineers who only need to deploy and monitor apps. Use **Billing** for finance team members who need usage and invoice access.
</Tip>

## API Keys and Request Attribution

Roles and key scopes are independent concepts. Roles control what a person can do in the dashboard (manage keys, billing, members). Key scopes control what the key itself can do programmatically (call models, deploy apps). A Developer-role member cannot create keys in the dashboard, but they can use the team's ADMIN-scoped key to run `fal deploy`.

API keys are scoped to the team, not to individual members. Any team member can use a team API key, but only Admins can create or delete them. When creating a key, make sure you have the correct team selected in the top-left of the dashboard. See [Get Your API Key](/documentation/setting-up/accounts-and-identity#get-your-api-key) for the available scopes.

How you authenticate affects how requests are attributed and what you see in the dashboard. When you use `fal auth login` and select a team, each request carries your individual identity within the team. This means the dashboard shows which team member made each request. When you use a team API key directly, requests are attributed to the team as a whole rather than to a specific member. Both methods access the same team resources and billing, but login-based authentication provides better per-user visibility in the dashboard and request history.

The fal client SDKs (`fal_client` in Python, `@fal-ai/client` in JavaScript) support both methods automatically. The SDK checks for credentials in this order:

1. `FAL_KEY` environment variable (sends `Authorization: Key ...`)
2. Tokens saved by `fal auth login` (sends `Authorization: Bearer ...`)

Login tokens are stored on disk at `~/.fal/auth0_token`, so they persist across terminal sessions and reboots. You run `fal auth login` once, and any Python script on the same machine picks up the credentials automatically, even from a completely different process or terminal. This works the same way as `gcloud auth login` or `aws sso login`.

```bash theme={null}
# Run once from any terminal -- persists to disk
fal auth login
fal teams set my-team
```

```python theme={null}
# Any Python script, any terminal session, any process
# Automatically uses your login-based identity (no FAL_KEY needed)
import fal_client

result = fal_client.subscribe("fal-ai/flux/schnell", arguments={
    "prompt": "a sunset"
})
```

If `FAL_KEY` is set, it takes priority over login tokens. To force login-based auth even when `FAL_KEY` is present, set `FAL_FORCE_AUTH_BY_USER=1`.

For production apps and CI pipelines, API keys are recommended because they don't expire and don't require interactive login. For development, testing, and any workflow where per-user attribution matters, `fal auth login` is preferred.

## Managing Your Team

Team management happens on the [Members page](https://fal.ai/dashboard/members) and is restricted to Admins. From there you can change a member's role using the dropdown next to their name, remove members to revoke their access, or cancel pending invites that haven't been accepted yet. If a team is no longer needed, Admins can archive it permanently from the same page.

## Next Steps

<CardGroup cols={2}>
  <Card title="Organizations" icon="building" href="/documentation/organizations/index">
    Enterprise policies, SSO, and multi-team management
  </Card>

  <Card title="Access Controls" icon="shield" href="/documentation/organizations/access-controls">
    Control which models your teams can access
  </Card>
</CardGroup>
