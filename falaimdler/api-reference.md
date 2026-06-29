> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# API Reference

> Essential API reference for fal.distributed: the key methods you need to build multi-GPU applications

This page covers the essential APIs for building multi-GPU applications with `fal.distributed`. We focus on the methods you'll actually use in your code.

## DistributedRunner

The `DistributedRunner` class orchestrates multiple GPU workers for distributed computation. It handles process management, inter-process communication via ZMQ, and coordination between worker processes.

### Constructor

```python theme={null}
DistributedRunner(
    worker_cls: type[DistributedWorker],
    world_size: int,
)
```

**Parameters:**

* **`worker_cls`** (`type[DistributedWorker]`): Your custom worker class that inherits from `DistributedWorker`.
* **`world_size`** (`int`): Total number of worker processes to spawn (typically equals `num_gpus`).

**Example:**

```python theme={null}
from fal.distributed import DistributedRunner, DistributedWorker

class MyWorker(DistributedWorker):
    def setup(self, **kwargs):
        self.model = load_model().to(self.device)
    
    def __call__(self, prompt: str, **kwargs):
        return self.model.generate(prompt)

# Create runner for 4 GPUs
runner = DistributedRunner(
    worker_cls=MyWorker,
    world_size=4,
)
```

***

### start()

Starts all distributed worker processes and initializes them.

```python theme={null}
async def start(
    self,
    timeout: int = 1800,
    **kwargs: Any
) -> None
```

**Parameters:**

* **`timeout`** (`int`): Maximum time (in seconds) to wait for all workers to be ready. Default: `1800` (30 minutes).
* **`**kwargs`**: Additional keyword arguments passed to each worker's `setup()` method.

**Raises:**

* `RuntimeError`: If processes are already running or fail to start.
* `TimeoutError`: If workers don't become ready within the timeout period.

**Example:**

```python theme={null}
class MyApp(fal.App):
    num_gpus = 2
    
    async def setup(self):
        self.runner = DistributedRunner(
            worker_cls=MyWorker,
            world_size=self.num_gpus,
        )
        
        # Start workers and pass model path to their setup()
        await self.runner.start(model_path="/data/models/flux")
        
        # Workers are now ready to process requests
```

**What it does:**

1. Spawns `world_size` worker processes (one per GPU)
2. Each worker runs its `setup()` method with the provided `**kwargs`
3. Waits for all workers to signal "READY"
4. Starts the keepalive timer if configured
5. Returns when all workers are initialized and ready

<Note>
  This method must be called before using `invoke()` or `stream()`. It's typically called once in your app's `setup()` method.
</Note>

***

### invoke()

Executes the worker's `__call__()` method across all GPUs and returns the final result from rank 0.

```python theme={null}
async def invoke(
    self,
    payload: dict[str, Any] = {},
    timeout: int | None = None,
) -> Any
```

**Parameters:**

* **`payload`** (`dict[str, Any]`): Dictionary of arguments to pass to each worker's `__call__()` method. Default: `{}`.
* **`timeout`** (`int | None`): Maximum time (in seconds) to wait for the result. If `None`, uses the runner's default timeout. Default: `None`.

**Returns:**

* `Any`: The result returned by rank 0 worker's `__call__()` method.

**Raises:**

* `RuntimeError`: If workers are not running or encounter an error during execution.
* `TimeoutError`: If the operation exceeds the timeout.

**Example:**

```python theme={null}
@fal.endpoint("/generate")
async def generate(self, request: GenerateRequest) -> GenerateResponse:
    # Invoke workers to generate images
    result = await self.runner.invoke({
        "prompt": request.prompt,
        "num_steps": request.num_steps,
        "width": 1024,
        "height": 1024,
    })
    
    return GenerateResponse(image=result["image"])
```

**How it works:**

1. Serializes the payload and sends it to all workers
2. Each worker executes its `__call__()` method with `streaming=False`
3. Workers coordinate using PyTorch distributed operations (e.g., `dist.gather()`)
4. Only rank 0 returns the result
5. Result is deserialized and returned to the caller

<Tip>
  Use `invoke()` for standard (non-streaming) requests where you need the final result only.
</Tip>

***

### stream()

Streams intermediate results from workers during execution, useful for long-running operations like image generation or training.

```python theme={null}
async def stream(
    self,
    payload: dict[str, Any] = {},
    timeout: int | None = None,
    streaming_timeout: int | None = None,
    as_text_events: bool = False,
) -> AsyncIterator[Any]
```

**Parameters:**

* **`payload`** (`dict[str, Any]`): Dictionary of arguments to pass to each worker's `__call__()` method. Default: `{}`.
* **`timeout`** (`int | None`): Maximum total time (in seconds) for the entire operation. Default: `None` (no limit).
* **`streaming_timeout`** (`int | None`): Maximum time (in seconds) between consecutive yields. If no data is received within this period, raises `TimeoutError`. Default: `None`.
* **`as_text_events`** (`bool`): If `True`, yields Server-Sent Events (SSE) formatted as bytes. If `False`, yields deserialized Python objects. Default: `False`.

**Returns:**

* `AsyncIterator[Any]`: Async iterator yielding intermediate results and the final result.

**Raises:**

* `RuntimeError`: If workers are not running, encounter an error, or yield no data.
* `TimeoutError`: If the operation exceeds timeout or streaming\_timeout.

**Example:**

```python theme={null}
@fal.endpoint("/stream")
async def stream_generate(self, request: GenerateRequest) -> StreamingResponse:
    return StreamingResponse(
        self.runner.stream(
            payload={
                "prompt": request.prompt,
                "num_steps": request.num_steps,
            },
            as_text_events=True,
        ),
        media_type="text/event-stream",
    )
```

**How it works:**

1. Serializes the payload and sends it to all workers
2. Each worker executes its `__call__()` method with `streaming=True`
3. Workers can call `self.add_streaming_result()` to send intermediate updates
4. The runner yields each intermediate result as it's received
5. After workers finish, yields the final result
6. Automatically handles serialization based on `as_text_events`

<Tip>
  Set `as_text_events=True` when using with `StreamingResponse` for browser-compatible Server-Sent Events.
</Tip>

***

## DistributedWorker

The `DistributedWorker` class is the base class for your custom GPU workers. Each instance runs on a separate GPU and handles model loading, inference, or training.

Create your own worker by inheriting from `DistributedWorker` and overriding the `setup()` and `__call__()` methods.

```python theme={null}
class MyWorker(DistributedWorker):
    def setup(self, **kwargs):
        # Load model on this GPU
        self.model = load_model().to(self.device)
    
    def __call__(self, prompt: str, **kwargs):
        # Process request
        return self.model.generate(prompt)
```

***

### Properties

#### device

Returns the CUDA device assigned to this worker.

```python theme={null}
@property
def device(self) -> torch.device
```

**Returns:**

* `torch.device`: The PyTorch device for this worker, e.g., `cuda:0`, `cuda:1`, etc.

**Example:**

```python theme={null}
class MyWorker(DistributedWorker):
    def setup(self):
        # Load model on this worker's GPU
        self.model = MyModel().to(self.device)
        print(f"Model loaded on {self.device}")
```

***

#### rank

The rank (ID) of this worker, from 0 to world\_size-1.

```python theme={null}
self.rank: int
```

**Example:**

```python theme={null}
if self.rank == 0:
    print("I'm the master worker!")
    # Only rank 0 saves checkpoints, uploads files, etc.
```

***

#### world\_size

Total number of workers in the distributed setup.

```python theme={null}
self.world_size: int
```

**Example:**

```python theme={null}
print(f"Running with {self.world_size} GPUs")
```

***

### Methods to Override

#### setup()

Called once when the worker is initialized. Use this to load models, download weights, and prepare resources.

```python theme={null}
def setup(self, **kwargs: Any) -> None
```

**Parameters:**

* **`**kwargs`**: Any keyword arguments passed to `runner.start()`.

**Example:**

```python theme={null}
class FluxWorker(DistributedWorker):
    def setup(self, model_path: str = "/data/flux", **kwargs):
        """Initialize the Flux model on this GPU"""
        import torch
        from diffusers import FluxPipeline
        
        self.rank_print(f"Loading Flux on {self.device}")
        
        self.pipeline = FluxPipeline.from_pretrained(
            model_path,
            torch_dtype=torch.bfloat16,
        ).to(self.device)
        
        # Disable progress bar for non-main workers
        if self.rank != 0:
            self.pipeline.set_progress_bar_config(disable=True)
        
        self.rank_print("Model loaded successfully")
```

<Tip>
  Heavy operations like model loading should go in `setup()`, not `__call__()`, so they only happen once per worker.
</Tip>

***

#### **call**()

Called for each request. Implement your main processing logic here.

```python theme={null}
def __call__(self, streaming: bool = False, **kwargs: Any) -> Any
```

**Parameters:**

* **`streaming`** (`bool`): `True` if called via `runner.stream()`, `False` if called via `runner.invoke()`.
* **`**kwargs`**: Arguments from the `payload` dict passed to `runner.invoke()` or `runner.stream()`.

**Returns:**

* `Any`: The result to return. Only rank 0's return value is sent back to the caller.

**Example:**

```python theme={null}
class FluxWorker(DistributedWorker):
    def __call__(
        self,
        prompt: str,
        num_steps: int = 20,
        streaming: bool = False,
        **kwargs
    ) -> dict:
        """Generate an image on this GPU"""
        import torch.distributed as dist
        
        # Each GPU generates independently
        image = self.pipeline(
            prompt=prompt,
            num_inference_steps=num_steps,
            output_type="pt",
        ).images[0]
        
        # Gather all images to rank 0
        if self.rank == 0:
            gather_list = [
                torch.zeros_like(image, device=self.device)
                for _ in range(self.world_size)
            ]
        else:
            gather_list = None
        
        dist.gather(image, gather_list, dst=0)
        
        # Only rank 0 returns the result
        if self.rank == 0:
            combined_image = create_grid(gather_list)
            return {"image": combined_image}
        
        return {}  # Other ranks return empty dict
```

***

### Utility Methods

#### add\_streaming\_result()

Sends an intermediate result to the client during streaming.

```python theme={null}
def add_streaming_result(
    self,
    result: Any,
    image_format: str = "jpeg",
    as_text_event: bool = False,
) -> None
```

**Parameters:**

* **`result`** (`Any`): The data to stream. Can be a dict, PIL image, or any serializable object.
* **`image_format`** (`str`): Image format for PIL images (`"jpeg"` or `"png"`). Default: `"jpeg"`.
* **`as_text_event`** (`bool`): If `True`, formats as Server-Sent Event. Must match the `as_text_events` parameter in `runner.stream()`. Default: `False`.

**Example:**

```python theme={null}
def __call__(self, prompt: str, num_steps: int = 20, streaming: bool = False):
    for step in range(num_steps):
        # Generate intermediate result
        latent = self.model.step(prompt)
        
        # Stream progress (only rank 0)
        if streaming and self.rank == 0 and step % 5 == 0:
            preview_image = self.decode_latent(latent)
            self.add_streaming_result({
                "step": step,
                "progress": (step + 1) / num_steps,
                "preview": preview_image,
            }, as_text_event=True)
    
    # Return final result
    return {"image": final_image}
```

<Note>
  Only call `add_streaming_result()` from rank 0 to avoid duplicate messages to the client.
</Note>

***

#### rank\_print()

Prints a message with the worker's rank prefix for easy debugging.

```python theme={null}
def rank_print(self, message: str, debug: bool = False) -> None
```

**Parameters:**

* **`message`** (`str`): The message to print.
* **`debug`** (`bool`): If `True`, prefixes with `[debug]`. Default: `False`.

**Example:**

```python theme={null}
self.rank_print("Starting generation...")
# Output: [rank 0] Starting generation...

self.rank_print("Model loaded", debug=True)
# Output: [debug] [rank 0] Model loaded
```

***

## Common Patterns

### Pattern 1: Data Parallelism (Inference)

Each GPU processes different data independently:

```python theme={null}
class ParallelWorker(DistributedWorker):
    def __call__(self, prompt: str, **kwargs):
        import torch.distributed as dist
        
        # Each GPU generates independently with different seed
        result = self.model.generate(prompt)
        
        # Gather all results to rank 0
        if self.rank == 0:
            gather_list = [torch.zeros_like(result) for _ in range(self.world_size)]
        else:
            gather_list = None
        
        dist.gather(result, gather_list, dst=0)
        
        # Only rank 0 returns combined result
        if self.rank == 0:
            return {"outputs": gather_list}
        return {}
```

***

### Pattern 2: Distributed Data Parallel (Training)

All GPUs have the same model, process different batches, and sync gradients:

```python theme={null}
class DDPWorker(DistributedWorker):
    def setup(self, **kwargs):
        from torch.nn.parallel import DistributedDataParallel as DDP
        
        self.model = MyModel().to(self.device)
        
        # Wrap with DDP for gradient synchronization
        self.model = DDP(
            self.model,
            device_ids=[self.rank],
            output_device=self.rank,
        )
        
        self.optimizer = torch.optim.Adam(self.model.parameters())
    
    def __call__(self, data_path: str, **kwargs):
        import torch.distributed as dist
        
        # Load and distribute data
        if self.rank == 0:
            data = load_data(data_path)
        else:
            data = None
        
        # Broadcast to all ranks
        data = dist.broadcast_object_list([data], src=0)[0]
        
        # Each GPU processes different batch
        local_batch = data[self.rank::self.world_size]
        
        # Training loop
        for batch in local_batch:
            loss = self.model(batch)
            loss.backward()  # DDP syncs gradients automatically
            self.optimizer.step()
            self.optimizer.zero_grad()
        
        # Only rank 0 saves checkpoint
        if self.rank == 0:
            torch.save(self.model.state_dict(), "checkpoint.pt")
            return {"checkpoint": "checkpoint.pt"}
        
        return {}
```

***

### Pattern 3: Streaming with Progress Updates

Stream intermediate results during long-running operations:

```python theme={null}
class StreamingWorker(DistributedWorker):
    def __call__(self, prompt: str, steps: int = 50, streaming: bool = False):
        import torch.distributed as dist
        
        for step in range(steps):
            result = self.model.step(prompt)
            
            # Stream progress every 5 steps
            if streaming and self.rank == 0 and step % 5 == 0:
                self.add_streaming_result({
                    "step": step,
                    "progress": step / steps,
                }, as_text_event=True)
            
            # Sync all workers
            dist.barrier()
        
        # Return final result
        if self.rank == 0:
            return {"output": result}
        return {}
```

***

## Next Steps

<CardGroup cols={2}>
  <Card title="Multi-GPU Inference Tutorial" icon="bolt" href="/serverless/tutorials/deploy-multi-gpu-inference">
    Complete example with data parallelism
  </Card>

  <Card title="Multi-GPU Training Tutorial" icon="graduation-cap" href="/serverless/tutorials/deploy-multi-gpu-training">
    Complete example with DDP training
  </Card>

  <Card title="Event Streaming" icon="signal-stream" href="/serverless/distributed/streaming">
    Learn about streaming intermediate results
  </Card>

  <Card title="Overview" icon="book" href="/serverless/distributed/overview">
    High-level overview of multi-GPU workloads
  </Card>
</CardGroup>
