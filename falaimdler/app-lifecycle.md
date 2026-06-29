> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# App Lifecycle

> The complete lifecycle of a fal app, from writing code to runner shutdown.

Every fal app follows the same lifecycle, whether it is a simple Hello World or a production image generation pipeline. Understanding this sequence helps you write more efficient apps, debug startup issues, and handle shutdown gracefully.

This page walks through each stage in order using `fal.App`, the class-based approach. If you are migrating an existing Docker server and do not need `fal.App` lifecycle hooks, see [Direct Server Mode](/documentation/development/migrate-external-docker-server#option-1-direct-server-mode), which supports the same scaling parameters. For how to define your app's environment (pip packages vs Docker containers), see [Defining Your Environment](/documentation/development/container-setup). For how runners scale up and down based on demand, see [Runners and Caching](/documentation/getting-started/runners-and-caching).

## Defining Your App

You write a Python class that inherits from `fal.App`. This class declares what hardware it needs, what packages to install, how to initialize your model, and what endpoints are available. At this stage, nothing runs remotely. You are just defining the blueprint.

```python theme={null}
import fal
from pydantic import BaseModel

class Input(BaseModel):
    prompt: str

class Output(BaseModel):
    result: str

class MyApp(fal.App):
    machine_type = "GPU-H100"
    requirements = ["torch", "transformers"]

    def setup(self):
        from transformers import pipeline
        self.pipe = pipeline("text-generation", model="gpt2", device="cuda")

    @fal.endpoint("/")
    def generate(self, input: Input) -> Output:
        result = self.pipe(input.prompt, max_length=50)[0]["generated_text"]
        return Output(result=result)

    def teardown(self):
        del self.pipe
```

## Serialization and Build

When you run `fal run` or `fal deploy`, fal pickles your app class on your local machine and ships it to the cloud. All top-level code in your file (module imports, constants, helper functions) executes locally during this step. fal then builds a container from your [requirements](/documentation/development/fal-runtime) list or [custom Dockerfile](/documentation/development/use-custom-container-image), installing your dependencies into the remote environment.

This serialization step creates a boundary between what runs locally and what runs remotely. Understanding this boundary is essential for debugging, managing secrets, and controlling what gets shipped.

### What runs locally

When Python imports your app file, all top-level code executes on your machine: class bodies are evaluated, module-level variables are assigned, and helper functions are defined. If you reference an environment variable at the top level, it reads from your local environment, not the remote runner's. If you construct a large object at module scope, it will be serialized (pickled) and shipped as part of the app payload.

```python theme={null}
import os
import fal

CONFIG = {"api_key": os.environ["MY_API_KEY"]}

def helper(x):
    import torch
    return torch.tensor(x)
```

In this example, `CONFIG` is evaluated locally and pickled into the app payload. The `helper` function is defined locally but its body only executes remotely when called. The `import torch` inside the function runs on the remote runner, not on your machine.

### What runs remotely

Your `fal.App` subclass is pickled locally, then unpickled and instantiated on the remote runner in the environment you configured. All methods on the class, including `setup()`, your `@fal.endpoint` handlers, and `teardown()`, execute on the remote machine.

Symbols referenced by your app are handled in one of two ways. Small objects (closures, constants, simple data structures) are pickled and shipped as part of the payload. Importable packages that are installed in the remote environment are imported there rather than being serialized. This is why you often see imports inside methods rather than at the top of the file: it ensures the import happens in the remote environment where the package is installed.

```python theme={null}
import fal

CONFIG = {"model_name": "stabilityai/sdxl-base"}

class MyApp(fal.App):
    machine_type = "GPU-A100"
    requirements = ["torch", "diffusers"]

    def setup(self):
        from diffusers import StableDiffusionXLPipeline
        self.pipe = StableDiffusionXLPipeline.from_pretrained(
            CONFIG["model_name"]
        ).to("cuda")

    @fal.endpoint("/")
    def generate(self, input: dict) -> dict:
        result = self.pipe(input["prompt"]).images[0]
        return {"image": result}
```

In this example, `CONFIG` is a small dictionary that gets pickled and shipped to the runner. The `diffusers` import happens inside `setup()`, so it runs remotely where the package is installed via `requirements`. The `StableDiffusionXLPipeline` is loaded into GPU memory on the runner, not on your laptop.

### The serialization boundary

Objects that pickle well (strings, numbers, dicts, lists, simple dataclasses) can be freely referenced from top-level code. Objects that do not pickle well (database connections, file handles, GPU tensors, large numpy arrays) should be created inside `setup()` or endpoint methods, where they run on the remote machine.

If you need to pass secrets to your app, avoid putting them in top-level code where they would be pickled into the payload. Instead, use fal's [secrets management](/documentation/development/manage-secrets-securely) to store them securely and access them via [environment variables](/documentation/development/environment-variables) on the runner.

## Runner Startup

New [runners](/documentation/deployment/runners) are created in several situations: when incoming requests exceed the capacity of existing runners, when [min\_concurrency](/documentation/deployment/scale-your-application) requires runners to be warm even without traffic, or when [concurrency\_buffer](/documentation/deployment/scale-your-application) maintains spare runners ahead of demand so new requests hit a warm runner instead of triggering a cold start. If a request arrives and an idle runner is already available, it is routed there immediately with no startup needed. Only when no idle runner is available does fal provision a new machine, pull the container image, and start your app. The platform calls `setup()` before routing any requests to the new runner.

`setup()` is the right place for expensive one-time work: downloading model weights, loading them into GPU memory, compiling kernels, or running a warmup inference. The runner is not considered ready until `setup()` completes successfully. If it fails or exceeds the [startup\_timeout](/documentation/deployment/scale-your-application), the runner is terminated and replaced. Requests that were waiting for this runner stay in the queue and are routed to the next available runner.

Because `setup()` runs once per runner (not once per request), expensive operations only happen at startup. Subsequent requests reuse the loaded model. For strategies to speed up this step, see [Optimizing Cold Starts](/documentation/serverless/optimizations/optimize-cold-starts).

```python theme={null}
def setup(self):
    import torch
    from diffusers import StableDiffusionXLPipeline

    self.pipe = StableDiffusionXLPipeline.from_pretrained(
        "stabilityai/stable-diffusion-xl-base-1.0",
        torch_dtype=torch.float16,
    ).to("cuda")

    self.pipe("warmup")  # first inference compiles kernels
```

## Serving Requests

Once `setup()` completes, the runner enters the IDLE state and starts accepting requests. Each incoming request is routed to an available runner and dispatched to the matching `@fal.endpoint` method. If [max\_multiplexing](/documentation/deployment/scale-your-application) is greater than 1, a single runner can handle multiple requests concurrently.

Your endpoint methods run on the remote machine with full access to `self` (including anything you loaded in `setup()`). Inputs and outputs are validated through your Pydantic models. For details on defining schemas and how they map to the Playground UI, see [Handle Inputs and Outputs](/documentation/development/handle-inputs-and-outputs).

Between requests, the runner stays alive for the duration of the [keep\_alive](/documentation/deployment/scale-your-application) period. If no new requests arrive before keep\_alive expires, the runner begins shutting down.

## Shutdown

Runners shut down when they reach their keep\_alive expiration, when you manually stop them via the CLI or dashboard, or when fal scales down due to reduced demand. The shutdown sequence follows a strict order, bounded by the grace period (**5 seconds** by default):

1. The runner receives `SIGTERM`. No new requests are routed to it.
2. `handle_exit()` is called immediately.
3. In-flight requests finish processing (or stop early if `handle_exit()` signaled them).
4. `teardown()` is called after all requests complete.
5. When the grace period, counted from `SIGTERM`, expires (5 seconds by default), the runner is forcefully terminated with `SIGKILL`.

The grace period defaults to **5 seconds** but is configurable up to a maximum of **1 hour** via the [`termination_grace_period_seconds`](/documentation/deployment/scale-your-application#termination_grace_period_seconds) property on your app. This window is a shared budget between finishing in-flight requests and running `teardown()`, so increase it if your cleanup needs more time.

```python theme={null}
class MyApp(fal.App):
    termination_grace_period_seconds = 60  # total seconds for requests + teardown
```

### handle\_exit

`handle_exit()` is called the moment `SIGTERM` arrives. Use it to signal long-running request handlers to stop processing early, so there is time left for cleanup in `teardown()`. Without `handle_exit()`, a long-running request may consume the entire grace period, causing `teardown()` to be skipped when `SIGKILL` arrives.

### teardown

`teardown()` is called after all in-flight requests have finished. Use it to close database connections, release resources, flush logs, or perform any final cleanup before the runner is terminated.

Because `teardown()` only runs once in-flight requests complete, it may be skipped entirely if those requests consume the whole grace period before it can start. To avoid this, use `handle_exit()` to stop request processing early and leave enough of the grace period for cleanup, or increase [`termination_grace_period_seconds`](/documentation/deployment/scale-your-application#termination_grace_period_seconds).

### Example

```python theme={null}
import threading
import fal

class MyApp(fal.App):
    machine_type = "GPU-A100"

    def setup(self):
        self.model = load_model()
        self.db = connect_to_database()
        self.exit = threading.Event()

    @fal.endpoint("/")
    def run(self, input: dict) -> dict:
        for i in range(30):
            if self.exit.is_set():
                break
            result = self.model.process_step(i)
        return {"result": result}

    def handle_exit(self):
        self.exit.set()

    def teardown(self):
        self.db.close()
```

In this example, `setup()` loads a model and opens a database connection. The endpoint checks `self.exit` on each iteration so it can stop early when `SIGTERM` arrives. `handle_exit()` sets the flag, and `teardown()` closes the database connection after the request finishes.

<Warning>
  If you are using `fal` versions before 1.61.0, runners are terminated immediately without a grace period.
</Warning>

<Note>
  While it is possible to add your own signal handlers, we recommend using `handle_exit()` instead. The `setup()`, `handle_exit()`, and `teardown()` methods provide a clean and predictable lifecycle without the complexity of custom signal handling.
</Note>

## Next Steps

From here, [Defining Your Environment](/documentation/development/container-setup) covers how to choose between pip requirements and custom Docker containers. [Runners and Caching](/documentation/getting-started/runners-and-caching) explains runner states, scaling behavior, and the multi-layer caching system. For handling graceful cancellation of in-flight requests from the caller side, see [Handle Cancellations](/documentation/development/handle-cancellations).
