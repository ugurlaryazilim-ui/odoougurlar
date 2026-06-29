> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Migrate from Replicate

> A guide for migrating your Replicate Cog models to fal.

If you have been running models on Replicate using [Cog](https://github.com/replicate/cog), this guide shows how to convert your Cog model to a `fal.App`. The core idea is similar: both platforms package a model with its dependencies and expose a predict/generate interface. The main differences are that fal uses a Python class instead of a `cog.yaml` + `predict.py` pattern, and fal builds containers from a requirements list or Dockerfile rather than relying on Cog's build system.

For a broader overview of deploying existing Docker containers on fal (regardless of where they came from), see [Deploy an Existing Server](/documentation/development/migrate-external-docker-server). If you are comparing fal to other platforms, see [Migrate from Modal](/documentation/development/migrate-from-modal) or [Migrate from RunPod](/documentation/development/migrate-from-runpod).

## Concept Mapping

| Replicate (Cog)                  | fal                                        | Notes                                           |
| -------------------------------- | ------------------------------------------ | ----------------------------------------------- |
| `cog.yaml`                       | `requirements = [...]` or `ContainerImage` | Environment definition                          |
| `class Predictor(BasePredictor)` | `class MyApp(fal.App)`                     | App class                                       |
| `def setup(self)`                | `def setup(self)`                          | One-time model loading                          |
| `def predict(self, ...)`         | `@fal.endpoint("/")`                       | Request handler                                 |
| `cog.Path` (file output)         | `fal.toolkit.Image` / `fal.toolkit.File`   | Media outputs uploaded to CDN automatically     |
| `Input(...)` type hints          | Pydantic `BaseModel`                       | fal uses standard Pydantic for input validation |
| `cog push`                       | `fal deploy`                               | Single CLI command                              |
| Replicate API client             | `fal_client.subscribe(...)`                | HTTP + queue based                              |
| Webhooks                         | `webhook_url` parameter                    | Both support webhook delivery                   |

***

## Migration Path: Cog Predictor to fal.App

The most common Cog pattern is a `Predictor` class with `setup()` and `predict()` methods. On fal, `setup()` stays the same, and `predict()` becomes an `@fal.endpoint` method with Pydantic input/output models.

<Tabs>
  <Tab title="Replicate (Cog)">
    ```yaml theme={null}
    # cog.yaml
    build:
      python_version: "3.11"
      python_packages:
        - torch==2.1.0
        - diffusers==0.30.0
        - transformers
        - accelerate
      gpu: true
    predict: "predict.py:Predictor"
    ```

    ```python theme={null}
    # predict.py
    from cog import BasePredictor, Input, Path
    import torch
    from diffusers import StableDiffusionXLPipeline

    class Predictor(BasePredictor):
        def setup(self):
            self.pipe = StableDiffusionXLPipeline.from_pretrained(
                "stabilityai/stable-diffusion-xl-base-1.0",
                torch_dtype=torch.float16,
            ).to("cuda")

        def predict(self, prompt: str = Input(description="Text prompt")) -> Path:
            image = self.pipe(prompt).images[0]
            output_path = "/tmp/output.png"
            image.save(output_path)
            return Path(output_path)
    ```
  </Tab>

  <Tab title="fal">
    ```python theme={null}
    import fal
    from pydantic import BaseModel, Field
    from fal.toolkit import Image

    class Input(BaseModel):
        prompt: str = Field(description="Text prompt")

    class Output(BaseModel):
        image: Image

    class MyApp(fal.App):
        machine_type = "GPU-A100"
        requirements = ["torch==2.1.0", "diffusers==0.30.0", "transformers", "accelerate"]

        def setup(self):
            import torch
            from diffusers import StableDiffusionXLPipeline

            self.pipe = StableDiffusionXLPipeline.from_pretrained(
                "stabilityai/stable-diffusion-xl-base-1.0",
                torch_dtype=torch.float16,
            ).to("cuda")

        @fal.endpoint("/")
        def predict(self, input: Input) -> Output:
            image = self.pipe(input.prompt).images[0]
            return Output(image=Image.from_pil(image))
    ```
  </Tab>
</Tabs>

Key differences in the fal version:

The `cog.yaml` is replaced by class attributes (`machine_type`, `requirements`). The `cog.Path` output is replaced by `fal.toolkit.Image`, which automatically uploads the image to the [fal CDN](/documentation/model-apis/fal-cdn) and returns a URL. Inputs use standard Pydantic models instead of Cog's `Input()` type hints. Imports happen inside `setup()` so they run on the remote runner, not on your local machine (see [Serialization and Build](/documentation/development/app-lifecycle#serialization-and-build) for why).

## Using Your Existing Cog Dockerfile

If you have a complex `cog.yaml` with system packages, CUDA configuration, or custom build steps, you can extract the Dockerfile that Cog generates and use it directly with fal. Run `cog debug` to output the generated Dockerfile:

```bash theme={null}
cog debug > Dockerfile
```

You will need to make a few modifications to the generated Dockerfile:

1. Remove the `COPY . /src`, `EXPOSE`, and `CMD` lines at the end - fal handles these
2. Remove the Cog wheel installation (`cog-0.0.1.dev-py3-none-any.whl`) since fal does not use the Cog runtime
3. Replace the Cog requirements with your actual pip packages

Then reference the Dockerfile in your fal app:

```python theme={null}
import fal
from fal.container import ContainerImage

class MyApp(fal.App):
    machine_type = "GPU-A100"
    image = ContainerImage.from_dockerfile("Dockerfile")

    def setup(self):
        import torch
        from diffusers import StableDiffusionXLPipeline

        self.pipe = StableDiffusionXLPipeline.from_pretrained(
            "stabilityai/stable-diffusion-xl-base-1.0",
            torch_dtype=torch.float16,
        ).to("cuda")

    @fal.endpoint("/")
    def predict(self, input: dict) -> dict:
        image = self.pipe(input["prompt"]).images[0]
        return {"image": image}
```

For most migrations, the `requirements` list approach is simpler and avoids dealing with Cog's generated Dockerfile. Use the Dockerfile approach only when you have system-level dependencies or a specific CUDA version that cannot be expressed through pip packages. See [Custom Container Images](/documentation/development/use-custom-container-image) for the full guide.

<Note>
  `cog debug` is a hidden debugging command with no stability guarantees from the Cog team. The generated Dockerfile format may change between Cog versions.
</Note>

## Deploying and Calling

```bash theme={null}
# Deploy
fal deploy my_app.py::MyApp
```

```python theme={null}
# Call your deployed app
import fal_client

result = fal_client.subscribe("your-username/my-app", arguments={
    "prompt": "a sunset over mountains"
})
print(result["image"]["url"])
```

For the full range of calling patterns including async queue, streaming, and webhooks, see [Calling Your Endpoints](/documentation/development/calling-your-endpoints).

## Next Steps

Once you have migrated your model, the [App Lifecycle](/documentation/development/app-lifecycle) page explains how the full lifecycle works on fal, from code serialization to runner shutdown. For scaling configuration, see [Scale Your Application](/documentation/deployment/scale-your-application). For monitoring your deployed app, see [App Analytics](/documentation/serverless/observability/app-analytics).
