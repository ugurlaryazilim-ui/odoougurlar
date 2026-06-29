> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Application Setup

> Prepare your app's runtime environment: load models, download weights, and configure persistent storage.

Once you have defined your [environment](/documentation/development/container-setup) (pip requirements or a Docker container) and written your [app class](/documentation/development/app-lifecycle), the next step is preparing what happens when a runner starts. This section covers the resources your app needs at runtime: where to store model weights, how to download them efficiently, and how to structure your [setup()](/documentation/development/app-lifecycle#runner-startup) method so that cold starts are as fast as possible.

Everything in `setup()` runs once per [runner](/documentation/deployment/runners), not once per request. This is where you load model weights into GPU memory, initialize connections, and prepare any state that your endpoint methods will use. Objects you attach to `self` (like `self.model`) persist for the lifetime of the runner, so expensive operations only happen at startup. The trade-off is that everything in `setup()` contributes to your app's cold start time, which is the delay a request experiences when no idle runner is available and a new one must be provisioned.

```python theme={null}
class MyModel(fal.App):
    machine_type = "GPU-A100"
    requirements = ["torch", "diffusers"]

    def setup(self):
        import torch
        from diffusers import StableDiffusionXLPipeline

        self.pipe = StableDiffusionXLPipeline.from_pretrained(
            "stabilityai/stable-diffusion-xl-base-1.0",
            torch_dtype=torch.float16,
        ).to("cuda")

        self.pipe("warmup")

    @fal.endpoint("/")
    def generate(self, input: dict) -> dict:
        image = self.pipe(input["prompt"]).images[0]
        return {"image": image}
```

In this example, `setup()` downloads SDXL weights (cached to `/data` automatically for HuggingFace models), loads them into GPU memory, and runs a warmup inference to compile any lazy kernels. All of this happens once. Every subsequent request reuses `self.pipe` without any initialization overhead.

## What to Read Next

The pages in this section cover the infrastructure that supports your setup method. [Persistent Storage](/documentation/development/use-persistent-storage) explains the `/data` volume where model weights and datasets are cached across runners, including how the distributed filesystem works, how to upload files outside of your app, and how to handle concurrent writes safely. [Downloading Models and Files](/documentation/development/download-model-weights-and-files) covers the `download_file()` and `download_model_weights()` toolkit utilities, along with detailed Hugging Face optimization techniques for faster initial downloads, parallel file pre-reading, and compiled kernel caching.

For strategies to reduce cold start time beyond what is covered here, see [Optimizing Cold Starts](/documentation/serverless/optimizations/optimize-cold-starts), which covers container image optimization, scaling parameters, and [FlashPack](/documentation/serverless/optimizations/flashpack) for high-throughput tensor loading.
