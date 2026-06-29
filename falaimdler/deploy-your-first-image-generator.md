> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Deploy Your First Image Generator

> Deploy a text-to-image AI model in under 5 minutes. This tutorial walks you through creating your own image generation API using Stable Diffusion XL.

This tutorial builds on the [Quick Start](/documentation/development/getting-started/quick-start) by deploying a real AI model. You will create a text-to-image API powered by Stable Diffusion XL that runs on GPU infrastructure, loads model weights from Hugging Face, and returns generated images through a typed Pydantic schema. The result is a production-ready endpoint with a [Playground](/documentation/model-apis/playground) for browser-based testing.

Along the way, you will encounter several concepts that are central to building Serverless apps: the [setup()](/documentation/development/app-lifecycle) hook for one-time model loading, the [keep\_alive](/documentation/deployment/scale-your-application) parameter for controlling runner lifetime, pip [requirements](/documentation/development/fal-runtime) for environment setup, and the [fal.toolkit.Image](/documentation/development/handle-inputs-and-outputs#image-output) class for returning media outputs. If any of these are new to you, the [Serverless Introduction](/documentation/serverless) provides a quick overview.

## Before You Start

You'll need:

* Python - we recommend 3.11
* A [fal account](https://fal.ai/dashboard) (sign up is free)
* Basic familiarity with Python and AI models

## Step 1: Install the CLI

If you haven't already:

```bash theme={null}
pip install fal
```

## Step 2: Authenticate

Get your API key from the [fal dashboard](https://fal.ai/dashboard) and authenticate:

```bash theme={null}
fal auth login
```

This opens your browser to authenticate with fal. Once complete, your credentials are saved locally.

## Step 3: Create Your Image Generator

Create a file called `image_generator.py` with this Stable Diffusion XL text-to-image model:

```python theme={null}
import fal
from pydantic import BaseModel, Field
from fal.toolkit import Image

class Input(BaseModel):
    prompt: str = Field(
        description="The prompt to generate an image from",
        examples=["A beautiful image of a cat"],
    )

class Output(BaseModel):
    image: Image

class MyApp(fal.App):
    keep_alive = 300
    app_name = "my-demo-app"
    machine_type = "GPU-H100"
    requirements = [
        "hf-transfer==0.1.9",
        "diffusers[torch]==0.32.2",
        "transformers[sentencepiece]==4.51.0",
        "accelerate==1.6.0",
    ]

    def setup(self):
        # Enable HF Transfer for faster downloads
        import os

        os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"

        import torch
        from diffusers import StableDiffusionXLPipeline

        # Load any model you want, we'll use stabilityai/stable-diffusion-xl-base-1.0
        # Huggingface models will be automatically downloaded to
        # the persistent storage of your account (/data)
        self.pipe = StableDiffusionXLPipeline.from_pretrained(
            "stabilityai/stable-diffusion-xl-base-1.0",
            torch_dtype=torch.float16,
            variant="fp16",
            use_safetensors=True,
        ).to("cuda")

        # Warmup the model before the first request
        self.warmup()

    def warmup(self):
        self.pipe("A beautiful image of a cat")

    @fal.endpoint("/")
    def run(self, request: Input) -> Output:
        result = self.pipe(request.prompt)
        image = Image.from_pil(result.images[0])
        return Output(image=image)
```

## Step 4: Test Your Image Generator

Run your model to test it:

```bash theme={null}
fal run image_generator.py::MyApp
```

This starts your app, downloads the Stable Diffusion XL model weights (cached after the first run), and prints two URLs: a direct HTTP endpoint and a web playground. The first run takes a couple of minutes for the model download. Subsequent runs are faster.

Once you see `Application startup complete`, test it with curl using the URL from the output:

```bash theme={null}
curl $FAL_RUN_URL -H 'Content-Type: application/json' \
  -d '{"prompt":"A cyberpunk cityscape at night with neon lights"}'
```

You can also use the playground URL to test through a browser interface.

## Step 5: Deploy Your Model

Once you are satisfied with the results, deploy your app to create a persistent URL. Deployed apps scale automatically, with [runners](/documentation/deployment/runners) managed by fal's infrastructure. You can configure scaling behavior through parameters like `keep_alive`, `min_concurrency`, and `max_concurrency`. See [Scale Your Application](/documentation/deployment/scale-your-application) to learn more.

```bash theme={null}
fal deploy image_generator.py::MyApp
```

## Step 6: Call Your Deployed App

Once deployed, call your image generator from any Python or JavaScript application using the fal client SDK.

<Tabs>
  <Tab title="Python">
    ```bash theme={null}
    pip install fal-client
    ```

    ```python theme={null}
    import fal_client

    result = fal_client.subscribe(
        "your-username/my-demo-app",
        arguments={"prompt": "A cyberpunk cityscape at night with neon lights"},
    )
    print(result["image"]["url"])
    ```
  </Tab>

  <Tab title="JavaScript">
    ```bash theme={null}
    npm install @fal-ai/client
    ```

    ```javascript theme={null}
    import { fal } from "@fal-ai/client";

    const result = await fal.subscribe("your-username/my-demo-app", {
      input: { prompt: "A cyberpunk cityscape at night with neon lights" },
    });
    console.log(result.data.image.url);
    ```
  </Tab>
</Tabs>

Replace `your-username/my-demo-app` with the endpoint ID shown after deploying. See [Calling Your Endpoints](/documentation/development/calling-your-endpoints) for all calling patterns including async queue, streaming, real-time, and webhooks.

## Next Steps

The [App Lifecycle](/documentation/development/app-lifecycle) page explains how apps are structured, where code runs, and how runners start up and shut down. To define richer input and output schemas (sliders, image uploads, multiple outputs), see [Handle Inputs and Outputs](/documentation/development/handle-inputs-and-outputs). For all the ways to call your deployed app from client code, including async queue, streaming, and real-time patterns, see [Calling Your Endpoints](/documentation/development/calling-your-endpoints).
