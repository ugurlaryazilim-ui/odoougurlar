> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Environment Variables

> Built-in environment variables that fal injects into every runner, covering authentication, app identity, region, lifecycle state, and storage.

fal automatically injects several environment variables into every [runner](/documentation/deployment/runners) when it starts. These provide your app with authentication credentials, identity information, lifecycle state, and storage paths without any configuration. You access them via `os.getenv()` just like any other environment variable.

These platform variables are separate from your own [secrets](/documentation/development/manage-secrets-securely), which you configure manually and which are also injected as environment variables. Platform variables are always present on every runner; secrets are specific to what you've set. Both are available at runtime (in `setup()` and endpoint handlers) but not during the image build stage.

```python theme={null}
import os
import fal

class MyApp(fal.App):
    def setup(self):
        app_name = os.getenv("FAL_APP_NAME")
        job_id = os.getenv("FAL_JOB_ID")
        print(f"Setting up {app_name} on runner {job_id}")
```

***

## Authentication

| Variable  | Description                                                                                                                                                                |
| --------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `FAL_KEY` | An auto-generated API key scoped to your account, formatted as `key_id:key_secret`. Use this to call other fal models from within your app without hardcoding credentials. |

The `FAL_KEY` variable is set automatically when your app runs with privileged access (the default for deployed apps). The fal client SDKs read it automatically, so you can call other fal endpoints without any additional configuration.

```python theme={null}
import fal_client

class MyApp(fal.App):
    @fal.endpoint("/")
    def run(self, prompt: str):
        result = fal_client.subscribe("fal-ai/flux/schnell", arguments={
            "prompt": prompt
        })
        return result
```

<Warning>
  `FAL_KEY` is scoped to **your account** (the app owner). Any fal API calls made with this key are billed to you, not to the end user calling your app. If your app chains calls to marketplace models, you pay for those calls on top of your own runner costs.
</Warning>

<Note>
  `FAL_KEY` is not available during the image build stage. It is only injected at runtime.
</Note>

***

## App Identity

| Variable            | Description                                                |
| ------------------- | ---------------------------------------------------------- |
| `FAL_APP_NAME`      | Your application's full alias (e.g., `your-user/my-model`) |
| `FAL_APP_ID`        | Your application's unique identifier                       |
| `FAL_USER_NICKNAME` | Your account username                                      |
| `FAL_JOB_ID`        | The current runner's unique job ID                         |
| `FAL_HOST`          | The fal API host (e.g., `api.fal.ai`)                      |
| `FAL_REGION`        | The region where the runner is executing (e.g., `us-east`) |

These are useful for structured logging, metrics tagging, and conditional logic. For example, you might log the runner ID and region with every request so you can correlate issues in the [dashboard](/documentation/serverless/observability/monitor-performance).

```python theme={null}
import os
import logging

class MyApp(fal.App):
    def setup(self):
        self.logger = logging.getLogger(os.getenv("FAL_APP_NAME", "app"))
        self.logger.info(
            f"Runner {os.getenv('FAL_JOB_ID')} starting in {os.getenv('FAL_REGION')}"
        )
```

***

## Lifecycle

| Variable           | Values                            | Description                                 |
| ------------------ | --------------------------------- | ------------------------------------------- |
| `FAL_RUNNER_STATE` | `SETUP`, `RUNNING`, `TERMINATING` | The current phase of the runner's lifecycle |

fal sets this variable at each stage of the [runner lifecycle](/documentation/development/app-lifecycle): `SETUP` during `setup()`, `RUNNING` while serving requests, and `TERMINATING` after a shutdown signal is received. You can read it to make decisions in shared code paths, but for handling shutdown gracefully, use the [`handle_exit()` and `teardown()` methods](/documentation/development/app-lifecycle) on your App class instead of raw signal handlers.

```python theme={null}
import os

class MyApp(fal.App):
    @fal.endpoint("/")
    def run(self) -> dict:
        state = os.getenv("FAL_RUNNER_STATE")
        return {"runner_state": state}

    def handle_exit(self):
        print("Shutdown signal received, stopping early")

    def teardown(self):
        print("Cleaning up resources")
```

***

## Storage

| Variable  | Value                      | Description                                                                                                                   |
| --------- | -------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `HF_HOME` | `/data/.cache/huggingface` | Hugging Face cache directory, persisted across runners via [/data storage](/documentation/development/use-persistent-storage) |

fal sets `HF_HOME` to a path on the [persistent /data filesystem](/documentation/development/use-persistent-storage) so that Hugging Face models are automatically cached across runner restarts. The first runner downloads the model weights, and subsequent runners reuse the cached files without re-downloading.

```python theme={null}
from transformers import AutoModel

class MyApp(fal.App):
    def setup(self):
        self.model = AutoModel.from_pretrained("bert-base-uncased")
```

***

## User Secrets

Any [secrets](/documentation/development/manage-secrets-securely) you configure are also injected as environment variables alongside the platform variables listed above.

<Card title="Managing Secrets" href="/documentation/development/manage-secrets-securely">
  Set, update, and scope secrets per environment via CLI, Dashboard, or Python SDK
</Card>
