> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Installation & Setup

> Complete setup guide for the fal CLI and development environment. This guide covers all platforms and authentication methods.

The fal CLI is the primary tool for developing, testing, and deploying Serverless applications. This page covers installing the CLI, authenticating with your account, and switching between team contexts. By the end, you will have a working development environment ready for the [Quick Start](/documentation/development/getting-started/quick-start).

If you are only using [Model APIs](/documentation/model-apis/overview) to call pre-trained models, you do not need the CLI. You only need an [API key](/documentation/model-apis/authentication/index) and the client SDK (`fal-client` for Python or `@fal-ai/client` for JavaScript). The CLI is specifically for the Serverless workflow: writing, testing, and deploying your own apps. For an overview of how accounts, keys, and profiles relate to each other, see [Accounts and Identity](/documentation/setting-up/accounts-and-identity).

## System Requirements

* **Python**: 3.8 or later
* **Operating System**: macOS, Linux, or Windows

## Install the CLI

### Using pip

```bash theme={null}
pip install fal
```

### Verify Installation

Check that the CLI installed correctly:

```bash theme={null}
fal --version
```

You should see the version number printed.

## Authentication

### Option 1: Interactive Login (Recommended)

```bash theme={null}
fal auth login
```

This opens your browser to authenticate with fal. Once complete, your credentials are saved locally.

<Tip>
  If you are a member of multiple teams, the login process will prompt you to select which team account you want to use as your default. This affects which resources you can access and deploy to.
</Tip>

### Option 2: API Key

Create an API key at [API Keys](https://fal.ai/dashboard/keys) with the `ADMIN` scope. If creating a key for a team, make sure to select your team on the top left corner.

Set it as an environment variable:

```bash theme={null}
export FAL_KEY="your-api-key-here"
```

Or add it to your shell profile (`~/.bashrc`, `~/.zshrc`, etc.) to persist across sessions.

If you work with multiple API keys (for example, personal and team accounts), you can use `fal profile` to save keys and switch between them. See the [Accounts and Identity](/documentation/setting-up/accounts-and-identity#switching-accounts) page for details on profiles versus team switching.

## Team Accounts

After authentication, you can switch between different teams or your personal account using the `fal team` command.

### View Available Teams

To list teams that you are a member of:

```bash theme={null}
fal team list
```

| Default | Team      | Full Name  | ID                               |
| ------- | --------- | ---------- | -------------------------------- |
| \*      | myteam    | My Team    | github\|1kbr8zjkk377xfs5tl2erl4x |
|         | otherteam | Other Team | github\|v11vo11w2kqakm99ke00258q |

The `*` indicates your currently active team.

### Switch Teams

To switch to a different team:

```bash theme={null}
fal team set otherteam
```

To switch back to your personal account:

```bash theme={null}
fal team unset
```

## Verify Authentication

Test your authentication setup:

```bash theme={null}
fal auth whoami
```

This should display your account information, including your current team (if any). Example output:

```
User: john@example.com
Team: myteam (My Team)
```

If you see an error, double-check your authentication method and API key configuration.

## Upgrading

Keep your CLI up to date:

```bash theme={null}
pip install --upgrade fal
```

Check for breaking changes in the [changelog](https://github.com/fal-ai/fal/releases).

## Getting Help

If you run into issues, `fal --help` and `fal COMMAND --help` provide inline documentation for every command. For community support, join the [fal Discord](https://discord.gg/fal-ai). To report bugs or request features, open an issue on [GitHub](https://github.com/fal-ai/fal/issues).
