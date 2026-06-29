> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Secrets

> Store API keys, credentials, and other sensitive configuration securely, accessible to your fal App at runtime.

Most AI applications need credentials to call external services -- Hugging Face tokens for gated models, database URLs, third-party API keys, or [private Docker registry](/documentation/development/private-registries) credentials. Secrets let you store these values securely on fal instead of hardcoding them in your code or committing them to version control. Once set, secrets are encrypted and their values are never displayed again.

Secrets are injected into your [runners](/documentation/getting-started/runners-and-caching) as environment variables when they start. You access them via `os.getenv()` just like any other environment variable. Secrets can be scoped to specific [environments](/documentation/deployment/manage-environments) (e.g., different API keys for staging vs production) and are separate from the [platform environment variables](/documentation/development/environment-variables) that fal injects automatically.

## Setting Secrets

You can set secrets from the [Dashboard](https://fal.ai/dashboard/secrets), the CLI, or the Python SDK.

### Dashboard

Navigate to [**Dashboard > Secrets**](https://fal.ai/dashboard/secrets) to create, edit, and delete secrets. Select the environment (e.g., main, staging) from the dropdown, then add your key-value pairs. Values are encrypted and never displayed after creation.

### CLI

```bash theme={null}
fal secrets set HF_TOKEN=hf_abc123 DATABASE_URL=postgres://...
```

You can set multiple secrets in a single command. To target a specific environment, use the `--env` flag:

```bash theme={null}
fal secrets set HF_TOKEN=hf_staging_token --env staging
```

### Python SDK

```python theme={null}
from fal.api import SyncServerlessClient

client = SyncServerlessClient()
client.secrets.set("HF_TOKEN", "hf_abc123")
client.secrets.set("HF_TOKEN", "hf_staging_token", environment_name="staging")
```

## Accessing Secrets at Runtime

Secrets are available as standard environment variables inside your app. Use `os.getenv()` to read them in `setup()`, endpoint handlers, or anywhere else in your runner code.

```python theme={null}
import os
import fal

class MyApp(fal.App):
    def setup(self):
        import huggingface_hub
        huggingface_hub.login(token=os.getenv("HF_TOKEN"))
        self.pipe = load_gated_model()

    @fal.endpoint("/")
    def generate(self, prompt: str) -> dict:
        result = self.pipe(prompt)
        return {"output": result}
```

<Note>
  Secrets are injected when a runner starts. If you update a secret, running runners keep the old value. Only new runners (from a new deploy or scale-up) pick up the updated value. To force all runners to use the new value, redeploy your app with `fal deploy`.
</Note>

## Secrets During Build

For security, secrets are **not** available as environment variables during the image build stage. The built image is cached and may be shared across environments, so injecting secrets into the build would risk leaking them.

Instead, use the `${}` substitution syntax in your `requirements` list. fal replaces `${SECRET_NAME}` with the secret value at build time without exposing it in the cached image.

```python theme={null}
import fal

class MyApp(fal.App):
    requirements = [
        "git+https://${GITHUB_TOKEN}@github.com/myorg/private-package"
    ]
```

This is the only way to use secrets during dependency installation. The substitution happens server-side before pip runs, and the token is not stored in the final image.

### Docker Build Secrets

If you use a [custom container image](/documentation/development/use-custom-container-image), you can pass build-time secrets via the `secrets` parameter on `ContainerImage`. These are mounted as Docker build secrets (via `--mount=type=secret`) and are available inside your Dockerfile during the build but not persisted in the final image.

```python theme={null}
from fal.container import ContainerImage

image = ContainerImage.from_dockerfile_str(
    """
    FROM python:3.11
    RUN --mount=type=secret,id=hf_token cat /run/secrets/hf_token
    """,
    secrets={"hf_token": os.getenv("HF_TOKEN")},
)
```

## Secrets Per Environment

Secrets can be scoped to specific [environments](/documentation/deployment/manage-environments), letting you use different credentials for development, staging, and production. When you deploy to an environment, the runner receives the secrets set for that environment.

```bash theme={null}
fal secrets set DATABASE_URL=postgres://prod-db.example.com/app
fal secrets set DATABASE_URL=postgres://staging-db.example.com/app --env staging
```

If a secret is not set for a specific environment, the runner does not fall back to the main environment's value -- the variable is simply not present.

## Managing Secrets

### Listing

List your secrets to see their names, environments, and creation dates. Values are never displayed.

```bash theme={null}
fal secrets list
```

| Name          | Env  | Created At          |
| ------------- | ---- | ------------------- |
| HF\_TOKEN     | main | 2026-01-15 10:30:00 |
| DATABASE\_URL | main | 2026-01-15 10:31:00 |

To list secrets for a specific environment:

```bash theme={null}
fal secrets list --env staging
```

### Removing

Delete a secret to prevent it from being injected into new runners:

```bash theme={null}
fal secrets unset HF_TOKEN
fal secrets unset HF_TOKEN --env staging
```

Running runners are not affected by deletion. The secret is removed from new runners only.
