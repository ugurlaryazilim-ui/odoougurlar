> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Accounts and Identity

> Set up your fal account, choose between personal and team workspaces, and understand how identity works on the platform.

The first step to using fal is setting up your account. When you sign up, you get a personal account that comes with its own [API keys](/documentation/model-apis/authentication), deployed apps, and billing. If you're working with others, you can create a [team](/documentation/setting-up/teams) so everyone shares a single set of API keys, deployments, and billing instead of managing their own. This is useful whether you are consuming [Model APIs](/documentation/model-apis/overview) together or deploying your own models with [Serverless](/documentation/serverless).

Your identity on fal is separate from the accounts you operate under. You log in as yourself, then choose which account context to work in, whether that's your personal account or a team you belong to. This means one person can switch between multiple accounts without logging out.

## Account Types

| Account type     | What it is                                                                                           |
| ---------------- | ---------------------------------------------------------------------------------------------------- |
| **Personal**     | Created when you sign up. Your individual account.                                                   |
| **Team**         | A shared workspace with its own API keys, apps, and billing. Members are invited and assigned roles. |
| **Organization** | An enterprise parent that manages multiple teams with centralized policies and SSO.                  |

Teams can exist on their own (standalone) or as children of an [organization](/documentation/organizations/index). Standalone teams work well for small groups. Organizations add centralized policies, SSO, and cross-team visibility. Each team maintains its own API keys, secrets, deployed apps, and billing, completely separate from your personal account.

## Sign In

fal supports GitHub OAuth, Google OAuth, and SSO/SAML. If your company has SSO configured, you'll use that automatically. Otherwise, sign in with GitHub or Google. All methods are browser-based and take you straight to the [dashboard](https://fal.ai/dashboard).

<Warning>
  **Each login method creates a separate account.** If you sign in with Google and later sign in with SSO using the same email, you will have two separate personal accounts with separate API keys, credits, and deployed apps. Social logins (Google + GitHub) with the same email are merged into one account, but SSO and social logins are always kept separate. If you have SSO enabled for your organization, use SSO consistently to avoid duplicate accounts.
</Warning>

## Get Your API Key

All requests to fal require authentication. Create an API key in the [dashboard](https://fal.ai/dashboard/keys), then set it as an environment variable:

```bash theme={null}
export FAL_KEY="your-api-key-here"
```

When creating a key, you'll choose a scope:

| Scope     | Use case                                                                                                                                                                                                                           |
| --------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **API**   | Calling any model on fal, including [Model APIs](/documentation/model-apis/overview) and your own deployed endpoints.                                                                                                              |
| **ADMIN** | Everything in API, plus CLI operations (`fal deploy`, `fal run`), managing apps, and accessing admin-scoped [Platform APIs](/api-reference/platform-apis/index). Use this for [Serverless](/documentation/serverless) deployments. |

<Warning>
  API keys belong to **accounts**, not people. A team's API key is shared by all team members and accesses that team's resources. When creating a key, make sure the correct account is selected in the top-left corner of the dashboard.
</Warning>

## Switching Between Accounts

All operations, including API calls, deployments, and billing, happen under whichever account is active. You can switch accounts in two ways depending on how you interact with fal.

In the [dashboard](https://fal.ai/dashboard), select the account in the top-left corner. This controls which account's resources you see and which account new API keys are scoped to.

If you're using the fal CLI, you have two options. The recommended approach is [`fal auth login`](/api-reference/cli/auth), which opens a browser-based login flow and lets you select your team account interactively. Alternatively, use [`fal teams set`](/api-reference/cli/teams) to switch the active account for all subsequent commands, or pass `--team` on any command.

```bash theme={null}
# Browser-based login (recommended for SSO users)
fal auth login

# Switch your CLI context to a team
fal teams set my-company

# Or target a team for a single command
fal deploy my_app.py::MyApp --team my-company
```

You can also use [`fal profile`](/api-reference/cli/profile) to manage multiple named profiles, each with its own API key and host. This is useful if you work across multiple accounts or environments and want to switch between them without re-authenticating.

```bash theme={null}
fal profile create staging
fal profile key  # set API key for this profile
fal profile set staging  # switch to this profile
fal profile unset  # go back to default
```

## Next Steps

<CardGroup cols={2}>
  <Card title="Teams" icon="users" href="/documentation/setting-up/teams">
    Create shared workspaces with roles, API keys, and request attribution
  </Card>

  <Card title="Organizations" icon="building" href="/documentation/organizations/index">
    Enterprise policies, SSO, and multi-team management
  </Card>

  <Card title="Data Retention & Storage" icon="clock" href="/documentation/model-apis/media-expiration">
    How generated media is stored and how to control file expiration
  </Card>

  <Card title="Resources" icon="book" href="/documentation/setting-up/resources">
    Client libraries, API references, and community links
  </Card>
</CardGroup>
