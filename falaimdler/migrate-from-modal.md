> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Migrate from Modal

> A guide for migrating your Modal applications to fal.

If you have been running AI models on Modal, this guide maps Modal concepts to their fal equivalents and shows how to convert your code. The core patterns are similar: both platforms use Python classes with lifecycle hooks and GPU configuration. The main differences are that fal uses HTTP endpoints instead of RPC, and fal manages container builds from a requirements list or Dockerfile rather than chaining image methods.

For a broader overview of deploying existing Docker containers on fal (regardless of where they came from), see [Deploy an Existing Server](/documentation/development/migrate-external-docker-server). If you are comparing fal to other platforms, see [Migrate from Replicate](/documentation/development/migrate-from-replicate) or [Migrate from RunPod](/documentation/development/migrate-from-runpod).

## Concept Mapping

| Modal                                        | fal                                   | Notes                                   |
| -------------------------------------------- | ------------------------------------- | --------------------------------------- |
| `@app.function()`                            | `@fal.function()`                     | Standalone serverless functions         |
| `@app.cls()`                                 | `class MyApp(fal.App)`                | Class-based apps (recommended)          |
| `@modal.method()`                            | `@fal.endpoint("/")`                  | fal uses HTTP endpoints, not RPC        |
| `@modal.enter()`                             | `def setup(self)`                     | Container startup hook                  |
| `@modal.exit()`                              | `def teardown(self)`                  | Container shutdown hook                 |
| `modal.Image.debian_slim().pip_install(...)` | `requirements = [...]`                | Or use `ContainerImage` for Dockerfiles |
| `modal.Image.from_dockerfile(...)`           | `ContainerImage.from_dockerfile(...)` | Custom container support                |
| `gpu="A100"`                                 | `machine_type = "GPU-A100"`           | GPU selection                           |
| `modal.Volume`                               | `/data` persistent storage            | Mounted automatically on all runners    |
| `modal.Secret`                               | `fal secrets set`                     | Secrets exposed as env vars             |
| `modal deploy`                               | `fal deploy`                          | CLI deployment                          |
| `Cls().method.remote(x=123)`                 | `fal_client.subscribe(...)`           | fal uses HTTP + queue, not RPC          |

***

## Migration Path 1: Standalone Functions

If you use `@app.function()` in Modal, the closest fal equivalent is `@fal.function()`.

<Tabs>
  <Tab title="Modal">
    ```python theme={null}
    import modal

    app = modal.App()
    image = modal.Image.debian_slim().pip_install("torch", "transformers")

    @app.function(image=image, gpu="A100")
    def generate(prompt: str):
        from transformers import pipeline
        pipe = pipeline("text-generation", model="gpt2", device="cuda")
        return pipe(prompt)[0]["generated_text"]

    @app.local_entrypoint()
    def main():
        result = generate.remote(prompt="Hello world")
        print(result)
    ```
  </Tab>

  <Tab title="fal">
    ```python theme={null}
    import fal

    @fal.function(
        requirements=["torch", "transformers"],
        machine_type="GPU-A100",
    )
    def generate(prompt: str):
        from transformers import pipeline
        pipe = pipeline("text-generation", model="gpt2", device="cuda")
        return pipe(prompt)[0]["generated_text"]
    ```
  </Tab>
</Tabs>

***

## Migration Path 2: Class-Based Apps (Recommended)

If you use `@app.cls()` with `@modal.enter()` and `@modal.method()`, convert to a `fal.App` class.

<Tabs>
  <Tab title="Modal">
    ```python theme={null}
    import modal

    app = modal.App()
    image = (
        modal.Image.debian_slim()
        .pip_install("torch", "diffusers", "transformers", "accelerate")
    )

    @app.cls(image=image, gpu="A100")
    class TextToImage:
        @modal.enter()
        def load_model(self):
            import torch
            from diffusers import StableDiffusionXLPipeline

            self.pipe = StableDiffusionXLPipeline.from_pretrained(
                "stabilityai/stable-diffusion-xl-base-1.0",
                torch_dtype=torch.float16,
            ).to("cuda")

        @modal.method()
        def generate(self, prompt: str):
            image = self.pipe(prompt).images[0]
            return image

        @modal.exit()
        def cleanup(self):
            del self.pipe

    @app.local_entrypoint()
    def main():
        result = TextToImage().generate.remote(prompt="a sunset")
    ```
  </Tab>

  <Tab title="fal">
    ```python theme={null}
    import fal
    from fal.toolkit import Image

    class TextToImage(fal.App):
        machine_type = "GPU-A100"
        requirements = ["torch", "diffusers", "transformers", "accelerate"]

        def setup(self):
            import torch
            from diffusers import StableDiffusionXLPipeline

            self.pipe = StableDiffusionXLPipeline.from_pretrained(
                "stabilityai/stable-diffusion-xl-base-1.0",
                torch_dtype=torch.float16,
            ).to("cuda")

        @fal.endpoint("/")
        def generate(self, prompt: str) -> dict:
            image = self.pipe(prompt).images[0]
            return {"image": Image.from_pil(image)}

        def teardown(self):
            del self.pipe
    ```
  </Tab>
</Tabs>

### Deploying

```bash theme={null}
# Modal
modal deploy my_app.py

# fal
fal deploy my_app.py::TextToImage
```

### Calling Your App

```python theme={null}
# Modal
TextToImage().generate.remote(prompt="a sunset")

# fal
import fal_client
result = fal_client.subscribe("your-username/text-to-image", arguments={
    "prompt": "a sunset"
})
```

***

## Key Differences

### HTTP Endpoints vs RPC

Modal uses `.remote()` to invoke functions as Python-to-Python RPC calls. fal uses **HTTP endpoints** that any language or tool can call. Your fal App exposes a REST API automatically.

This means:

* No `.remote()` calls - clients use `fal_client.subscribe()` or raw HTTP
* Your endpoints accept and return JSON (use Pydantic models for validation)
* The same endpoint works from Python, JavaScript, cURL, or any HTTP client

### Queue-Based by Default

fal provides a persistent queue that handles retries, scaling, and load balancing automatically. When callers use `subscribe` or `submit`, requests go through this queue by default. Direct calls via `run` bypass the queue for lower overhead.

### Container Images

Modal chains image methods (`Image.debian_slim().pip_install(...).apt_install(...)`). fal offers two approaches:

* **`requirements` list** (simpler): Just list your pip packages
* **`ContainerImage`** (full control): Bring your own Dockerfile

```python theme={null}
# Modal
image = (
    modal.Image.debian_slim()
    .apt_install("ffmpeg")
    .pip_install("torch", "diffusers")
)

# fal (simple)
class MyApp(fal.App):
    requirements = ["torch", "diffusers"]

# fal (Dockerfile)
from fal.container import ContainerImage

class MyApp(fal.App):
    image = ContainerImage.from_dockerfile_str("""
        FROM python:3.11
        RUN apt-get update && apt-get install -y ffmpeg
        RUN pip install torch diffusers
    """)
```

### Volumes and Storage

Modal uses named `Volume` objects mounted at specific paths. fal provides `/data` -- a persistent filesystem automatically mounted on every runner, shared across all your apps.

```python theme={null}
# Modal
volume = modal.Volume.from_name("model-cache")

@app.cls(volumes={"/cache": volume})
class MyModel:
    ...

# fal -- /data is always available, no configuration needed
class MyModel(fal.App):
    def setup(self):
        model_path = "/data/models/my-model.pt"
        if os.path.exists(model_path):
            self.model = torch.load(model_path)
```

### Secrets

Modal uses `modal.Secret.from_name(...)` and attaches secrets to functions. fal exposes secrets as environment variables:

```bash theme={null}
# Modal
modal secret create my-secret HF_TOKEN=hf_xxx

# fal
fal secrets set HF_TOKEN=hf_xxx
```

Both make secrets available via `os.environ["HF_TOKEN"]` in your code.

## Next Steps

Once you have migrated your app, the [App Lifecycle](/documentation/development/app-lifecycle) page explains how the full lifecycle works on fal, from code serialization to runner shutdown. For scaling configuration, see [Scale Your Application](/documentation/deployment/scale-your-application). For monitoring your deployed app, see [App Analytics](/documentation/serverless/observability/app-analytics).
