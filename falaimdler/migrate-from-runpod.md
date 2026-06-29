> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Migrate from RunPod

> A guide for migrating your RunPod Serverless workers to fal.

If you have been running serverless GPU workloads on RunPod, this guide maps RunPod concepts to their fal equivalents and shows how to convert your code. The core ideas are similar: both platforms run your code on GPU machines that scale based on demand. The main difference is that RunPod uses a handler function pattern with explicit Docker builds, while fal uses a class-based `fal.App` with automatic container builds.

For a broader overview of deploying existing Docker containers on fal (regardless of where they came from), see [Deploy an Existing Server](/documentation/development/migrate-external-docker-server). If you are comparing fal to other platforms, see [Migrate from Replicate](/documentation/development/migrate-from-replicate) or [Migrate from Modal](/documentation/development/migrate-from-modal).

## Concept Mapping

| RunPod                                          | fal                                                                        | Notes                                                                           |
| ----------------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `handler(job)`                                  | `@fal.endpoint("/")`                                                       | Request handler function                                                        |
| `runpod.serverless.start({"handler": handler})` | `class MyApp(fal.App)`                                                     | App entrypoint                                                                  |
| `job["input"]`                                  | Pydantic `Input` model                                                     | fal validates and types inputs automatically                                    |
| `return result`                                 | `return Output(...)`                                                       | fal validates outputs with Pydantic                                             |
| `yield result` (streaming)                      | `StreamingResponse` or `@fal.realtime()`                                   | See [Streaming](/documentation/development/streaming)                           |
| Model loading at module level                   | `def setup(self)`                                                          | Runs once per runner, not per request                                           |
| `refresh_worker: True`                          | Return HTTP 503                                                            | Terminates the runner and spins up a fresh one                                  |
| `runpod.serverless.progress_update()`           | `print()` (logs visible via SDK)                                           | Or use [streaming](/documentation/development/streaming) for real-time updates  |
| Dockerfile + Docker Hub                         | `requirements = [...]`, `ContainerImage`, or `pyproject.toml` image config | Handler migrations can let fal build; HTTP server images can be reused directly |
| Docker Hub deployment                           | `fal deploy`                                                               | Single CLI command                                                              |
| `/run` (async)                                  | `fal_client.submit()`                                                      | Queue-based async                                                               |
| `/runsync` (sync)                               | `fal_client.subscribe()`                                                   | Blocks until result                                                             |
| `/stream`                                       | `fal_client.stream()`                                                      | Progressive output                                                              |
| Max workers                                     | `max_concurrency`                                                          | Maximum runners to scale to                                                     |
| Min workers                                     | `min_concurrency`                                                          | Minimum runners kept warm                                                       |
| Idle timeout                                    | `keep_alive`                                                               | Seconds before idle runner shuts down                                           |
| Concurrency per worker                          | `max_multiplexing`                                                         | Concurrent requests per runner                                                  |
| Network volumes                                 | `/data` persistent storage                                                 | Mounted automatically on all runners                                            |
| Environment variables                           | `fal secrets set`                                                          | Secrets exposed as env vars                                                     |

***

## Migration Path: Handler to fal.App

The most common pattern on RunPod is a handler function that loads a model at module level and processes requests. On fal, this maps to a `fal.App` class where model loading moves into `setup()` and the handler becomes an endpoint method.

<Tabs>
  <Tab title="RunPod">
    ```python theme={null}
    import runpod
    import torch
    from diffusers import StableDiffusionXLPipeline

    model = StableDiffusionXLPipeline.from_pretrained(
        "stabilityai/stable-diffusion-xl-base-1.0",
        torch_dtype=torch.float16,
    ).to("cuda")

    def handler(job):
        prompt = job["input"]["prompt"]
        image = model(prompt).images[0]
        image.save("/tmp/output.png")
        return {"image_path": "/tmp/output.png"}

    runpod.serverless.start({"handler": handler})
    ```
  </Tab>

  <Tab title="fal">
    ```python theme={null}
    import fal
    from pydantic import BaseModel
    from fal.toolkit import Image

    class Input(BaseModel):
        prompt: str

    class Output(BaseModel):
        image: Image

    class MyApp(fal.App):
        machine_type = "GPU-A100"
        requirements = ["torch", "diffusers"]
        keep_alive = 300
        max_concurrency = 5

        def setup(self):
            import torch
            from diffusers import StableDiffusionXLPipeline

            self.model = StableDiffusionXLPipeline.from_pretrained(
                "stabilityai/stable-diffusion-xl-base-1.0",
                torch_dtype=torch.float16,
            ).to("cuda")

        @fal.endpoint("/")
        def generate(self, input: Input) -> Output:
            image = self.model(input.prompt).images[0]
            return Output(image=Image.from_pil(image))
    ```
  </Tab>
</Tabs>

Key differences in the fal version:

The model loading moves from module-level into `setup()`, which runs once per [runner](/documentation/getting-started/runners-and-caching) rather than once per container build. Inputs are validated through a Pydantic model instead of manually extracting from `job["input"]`. Outputs are also typed, and images are automatically uploaded to the [fal CDN](/documentation/model-apis/fal-cdn) rather than saved to a local path. You do not need to write a Dockerfile or push to Docker Hub since fal builds the container from your `requirements` list.

## Calling Your Deployed App

RunPod exposes `/run` (async), `/runsync` (sync), and `/stream` endpoints. fal provides equivalent patterns through the client SDK.

<Tabs>
  <Tab title="RunPod">
    ```python theme={null}
    import runpod

    runpod.api_key = "your_api_key"
    endpoint = runpod.Endpoint("your_endpoint_id")

    # Sync
    result = endpoint.run_sync({"prompt": "a sunset"})

    # Async
    run = endpoint.run({"prompt": "a sunset"})
    status = run.status()
    result = run.output()
    ```
  </Tab>

  <Tab title="fal">
    ```python theme={null}
    import fal_client

    # Sync (subscribe polls automatically)
    result = fal_client.subscribe("your-username/your-app", arguments={
        "prompt": "a sunset"
    })

    # Async
    handler = fal_client.submit("your-username/your-app", arguments={
        "prompt": "a sunset"
    })
    status = handler.status()
    result = handler.get()
    ```
  </Tab>
</Tabs>

For the full range of calling patterns including streaming, real-time WebSockets, and webhooks, see [Calling Your Endpoints](/documentation/development/calling-your-endpoints).

## Deployment Workflow

On RunPod, the deployment unit is a Docker image. Your handler code lives inside the image, and the workflow requires several manual steps: write a Dockerfile that copies your handler and installs dependencies, build the image locally, push it to Docker Hub, then deploy through RunPod's console by pointing it at the image URL.

<Tabs>
  <Tab title="RunPod workflow">
    ```dockerfile theme={null}
    # 1. Write a Dockerfile
    FROM pytorch/pytorch:2.1.0-cuda12.1-cudnn8-runtime
    RUN pip install runpod diffusers transformers
    COPY handler.py /handler.py
    CMD ["python", "/handler.py"]
    ```

    ```bash theme={null}
    # 2. Build locally
    docker build -t myuser/my-model:latest .

    # 3. Push to Docker Hub
    docker push myuser/my-model:latest

    # 4. Deploy via RunPod console (manual step in the UI)
    ```
  </Tab>

  <Tab title="fal workflow">
    ```python theme={null}
    # 1. Write your app (no Dockerfile needed)
    class MyApp(fal.App):
        machine_type = "GPU-A100"
        requirements = ["torch", "diffusers", "transformers"]

        def setup(self):
            ...
    ```

    ```bash theme={null}
    # 2. Deploy (one command, fal builds the container for you)
    fal deploy my_app.py::MyApp
    ```
  </Tab>
</Tabs>

On fal, the normal RunPod queue-handler migration does not require a manual Docker build, Docker Hub, or console-based deployment. You run `fal deploy` and fal handles the container build, image storage, and deployment. Your code and your environment definition live in the same Python file.

### Reusing an HTTP server image

RunPod always deploys a container image, but not every RunPod Serverless image is an HTTP server. Queue endpoints typically run a handler with `runpod.serverless.start(...)`; those still need the migration path above. If your RunPod image already exposes an HTTP server, you can reference the existing image directly from `pyproject.toml` instead of converting it to `fal.App`.

```toml theme={null}
[tool.fal.apps.my-server]
auth = "private"
machine_type = "GPU-A100"
exposed_port = 8000
keep_alive = 300

[tool.fal.apps.my-server.image]
image = "my-org/my-server:latest"
cmd = ["your-server", "--host", "0.0.0.0", "--port", "8000"]
```

If the image itself is private, configure registry credentials under the app's `image` configuration. See [Private Docker Registries](/documentation/development/private-registries) for Docker Hub, Google Artifact Registry, and Amazon ECR examples.

Deploy it by app name:

```bash theme={null}
fal deploy my-server
```

For the full direct-server flow, including private registry setup and OpenAPI notes, see [Deploy an Existing Server](/documentation/development/migrate-external-docker-server).

## Environment and Dependencies

Because fal eliminates the Docker build step for most use cases, you have two options for defining your environment:

**Option 1: pip requirements (recommended).** List your packages in the `requirements` attribute. fal builds the container automatically. This is the simplest migration path since you can copy the `pip install` lines from your RunPod Dockerfile directly into the list.

```python theme={null}
class MyApp(fal.App):
    requirements = ["torch==2.1.0", "diffusers==0.30.0", "transformers"]
```

**Option 2: Custom Docker container.** If you need system packages, a specific CUDA version, or want to reuse your existing RunPod Dockerfile with minimal changes, use [ContainerImage](/documentation/development/use-custom-container-image). You can paste your RunPod Dockerfile almost as-is, just remove the `COPY handler.py` and `CMD` lines since fal handles those.

```python theme={null}
from fal.container import ContainerImage

class MyApp(fal.App):
    image = ContainerImage.from_dockerfile_str("""
        FROM pytorch/pytorch:2.1.0-cuda12.1-cudnn8-runtime
        RUN apt-get update && apt-get install -y ffmpeg
        RUN pip install diffusers transformers
    """)
```

## Model Storage

RunPod offers three approaches for model weights: Hugging Face cache, baked into the Docker image, or network volumes. fal's equivalent is [persistent storage](/documentation/development/use-persistent-storage) at `/data`, which is mounted on every runner and shared across your account. Models downloaded to `/data` are cached automatically and survive runner restarts, similar to RunPod's network volumes but without explicit volume configuration.

```python theme={null}
def setup(self):
    import os
    os.environ["HF_HOME"] = "/data/.cache/huggingface"

    from diffusers import StableDiffusionXLPipeline
    self.model = StableDiffusionXLPipeline.from_pretrained(
        "stabilityai/stable-diffusion-xl-base-1.0"
    ).to("cuda")
```

## Next Steps

Once you have migrated your handler, the [App Lifecycle](/documentation/development/app-lifecycle) page explains how the full lifecycle works on fal, from code serialization to runner shutdown. For scaling configuration, see [Scale Your Application](/documentation/deployment/scale-your-application). For monitoring your deployed app, see [App Analytics](/documentation/serverless/observability/app-analytics).
