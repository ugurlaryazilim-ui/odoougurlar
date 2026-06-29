> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Optimize Routing Behavior

> Use routing hints to direct requests to runners that already have the right model or state loaded in memory.

When you scale to multiple runners, fal normally treats them as interchangeable and routes requests to any available runner. This works well when every runner is identical, but falls short when runners hold different state. For example, an app that serves multiple diffusion models but can only keep a few loaded in GPU memory at once. Routing a request for FLUX.1 to a runner that already has FLUX.1 loaded avoids a costly model swap, while routing it to a runner with a different model loaded means waiting for a full model load.

Routing hints solve this with a two-sided mechanism. On the caller side, you pass a [`hint` parameter](/documentation/model-apis/inference/queue#hint) (sent as the `X-Fal-Runner-Hint` header) that describes what the request needs. On the server side, your app implements a `provide_hints()` method that tells fal what each runner is currently specialized for. When both are present, fal's router tries to match requests to runners with compatible hints. If no matching runner is available or all matching runners are busy, the request goes to any available runner without waiting. Hints are best-effort: they improve cache hit rates but never block a request from being processed.

## How It Works

The router matches the hint string from the caller against the list of strings each runner reports via `provide_hints()`. The matching is exact: if the caller sends `hint="flux-schnell"` and a runner's `provide_hints()` returns `["flux-schnell", "sd-xl"]`, that runner is preferred. If no runner has a matching hint, the request goes to any available runner.

`provide_hints()` is called after every response and the result is sent back to the platform as a response header. This means hints update dynamically as the runner loads and unloads models. A runner that starts empty will initially match any request, and as it loads models, it becomes specialized for those models.

## Example

This app serves any Hugging Face diffusion model by name. Each runner maintains a cache of loaded models. The hint is the model name, which matches what `provide_hints()` reports.

### Application

```python theme={null}
from typing import Any

import fal
from fal.toolkit import Image
from pydantic import BaseModel, Field


class Input(BaseModel):
    model: str = Field(description="Hugging Face model ID")
    prompt: str = Field(description="Text prompt")


class Output(BaseModel):
    image: Image


class AnyModelRunner(fal.App):
    machine_type = "GPU-A100"

    def setup(self) -> None:
        self.models = {}

    def provide_hints(self) -> list[str]:
        return list(self.models.keys())

    def load_model(self, name: str) -> Any:
        from diffusers import DiffusionPipeline

        if name in self.models:
            return self.models[name]

        pipeline = DiffusionPipeline.from_pretrained(name)
        pipeline.to("cuda")

        self.models[name] = pipeline
        return pipeline

    @fal.endpoint("/")
    def run_model(self, input: Input) -> Output:
        model = self.load_model(input.model)
        result = model(input.prompt)
        return Output(image=Image.from_pil(result.images[0]))
```

When a runner starts, `provide_hints()` returns an empty list, so it matches any request. As it loads models, the hints update to include the loaded model names. Over time, the router naturally specializes runners by directing repeat requests for the same model to the same runner.

### Client

The caller passes the model name as both an argument (for the app logic) and a hint (for the router). The hint is processed at the gateway before the request reaches your app, so it cannot be extracted from the request body automatically.

```python theme={null}
import fal_client

model = "black-forest-labs/FLUX.1-schnell"

handler = fal_client.submit(
    "myuser/myapp",
    arguments={
        "model": model,
        "prompt": "a cat",
    },
    hint=model,
)

result = handler.get()
```

## When to Use Hints

Hints are most valuable when your app serves multiple models or configurations that are expensive to swap. Common patterns include multi-model serving (as shown above), per-user LoRA adapters where each user's adapter is cached on a specific runner, and pipeline configurations with different preprocessing states.

If every runner in your app is identical (same model, same state), you do not need hints. The default round-robin routing is sufficient.

<Warning>
  Hints are sent as a response header, which counts toward the **16 KB total response header limit**. If `provide_hints()` returns many values or long strings, the combined headers can exceed this limit and cause the response to fail. Keep hint values short and limit the number of hints per runner.
</Warning>
