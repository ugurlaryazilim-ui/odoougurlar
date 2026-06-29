> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Inference Methods

> Learn the different ways to call models on fal

Every model on fal can be called through the same set of inference methods, whether it is a pre-trained model from the [gallery](https://fal.ai/models) or your own app running on [Serverless](/documentation/serverless). This page walks through each method, explains when to reach for it, and links to the deeper reference pages. Before calling any model you will need an [API key](/documentation/model-apis/authentication) and the [fal client](/documentation/model-apis/inference/client-setup) installed in your project.

fal provides five calling patterns that cover the spectrum from quick prototyping to high-throughput production pipelines. All of them benefit from fal's autoscaling infrastructure, where [runners](/documentation/deployment/runners) spin up on demand to handle your requests. The key decision is whether you need the [queue](/documentation/model-apis/inference/queue) (recommended for reliability), a direct call (simplest path), [streaming](/documentation/model-apis/inference/streaming) (progressive output), or a [real-time WebSocket](/documentation/model-apis/inference/real-time) connection (lowest latency). Each method is covered below with a code example and guidance on when it is the right fit.

<Tip>
  These calling patterns work identically for your own deployed serverless apps. Use your app's endpoint ID (e.g., `your-username/your-app-name`) instead of a model ID. See [Calling Your Endpoints](/documentation/development/calling-your-endpoints) for serverless-specific examples.
</Tip>

| Method            | How it works                                   |
| ----------------- | ---------------------------------------------- |
| **`run()`**       | Direct HTTP call, no queue                     |
| **`subscribe()`** | Queue-based, blocks until result               |
| **`submit()`**    | Queue-based, returns immediately (recommended) |
| **`stream()`**    | Progressive output via SSE                     |
| **`realtime()`**  | WebSocket, persistent connection               |

***

## Direct (`run`)

The simplest way to call a model. Sends a direct HTTP request to `fal.run` and returns the result. No queue, no retries, no polling.

```python theme={null}
import fal_client

result = fal_client.run("fal-ai/nano-banana-2", arguments={
    "prompt": "a sunset over mountains"
})
print(result["images"][0]["url"])
```

Use `run` for quick scripts, prototyping, or any model with fast response times where you want the lowest overhead. Because there is no queue involved, the call goes straight to a runner and returns the response directly. The tradeoff is that direct calls do not retry on failure. If the runner returns an error or times out, you get the error immediately.

<Warning>
  For production use, prefer `subscribe` or `submit` so you get automatic retries and request durability through the [queue](/documentation/model-apis/inference/queue).
</Warning>

<Card title="Learn more" icon="arrow-right" href="/documentation/model-apis/inference/synchronous">
  Direct and queue-backed synchronous calls
</Card>

***

## Subscribe (Queue-backed synchronous)

Like `run`, but uses the queue under the hood. Submits a request, polls automatically, and blocks until the result is ready. You get automatic retries and reliability with a simple interface.

```python theme={null}
import fal_client

result = fal_client.subscribe("fal-ai/nano-banana-2", arguments={
    "prompt": "a sunset over mountains"
})
print(result["images"][0]["url"])
```

`subscribe` is a good choice when you want the simplicity of a blocking call combined with queue-backed reliability. It handles polling for you, so the code looks almost identical to `run`, but your request is durable and will be retried if a runner fails. Reach for it in simple integrations, backend scripts, or anywhere you do not need to manage the request lifecycle yourself.

<Card title="Learn more" icon="arrow-right" href="/documentation/model-apis/inference/synchronous">
  Direct and queue-backed synchronous calls
</Card>

***

## Asynchronous (`submit`)

The recommended approach for production. Submit a request to the [queue](/documentation/model-apis/inference/queue) and return immediately, then poll for status or receive results via [webhook](/documentation/model-apis/inference/webhooks).

**Polling:**

```python theme={null}
import time
import fal_client

handler = fal_client.submit("fal-ai/nano-banana-2", arguments={
    "prompt": "a sunset over mountains"
})

while True:
    status = handler.status(with_logs=True)

    if isinstance(status, fal_client.Queued):
        print(f"In queue, position: {status.position}")
    elif isinstance(status, fal_client.InProgress):
        for log in status.logs or []:
            print(log["message"])
    elif isinstance(status, fal_client.Completed):
        print(f"Done in {status.metrics.get('inference_time', '?')}s")
        break

    time.sleep(0.5)

result = handler.get()
print(result["images"][0]["url"])
```

### Status types

The `handler.status()` method returns one of three types. Pass `with_logs=True` to include runner logs.

| Type         | Fields                                  | Meaning                                                                           |
| ------------ | --------------------------------------- | --------------------------------------------------------------------------------- |
| `Queued`     | `position` (int)                        | Waiting in queue. `position` is how many requests are ahead.                      |
| `InProgress` | `logs` (list or None)                   | A runner is processing the request. `logs` contains messages if `with_logs=True`. |
| `Completed`  | `logs` (list or None), `metrics` (dict) | Result is ready. `metrics` includes `inference_time` in seconds.                  |

In JavaScript, the equivalent types are `InQueueQueueStatus`, `InProgressQueueStatus`, and `CompletedQueueStatus`. See the full [Python SDK reference](/api-reference/client-libraries/python/fal_client#status) and [JavaScript SDK reference](/api-reference/client-libraries/javascript/types.common) for details.

**Webhook (no polling needed):**

```python theme={null}
import fal_client

handler = fal_client.submit("fal-ai/nano-banana-2",
    arguments={"prompt": "a sunset over mountains"},
    webhook_url="https://your-server.com/api/webhook"
)
```

Async inference is the recommended path for production because it works reliably at any scale. You can submit many requests in parallel and process them as they complete, use webhooks to build event-driven architectures without polling, and get full visibility into queue position and runner logs. The queue handles retries and request persistence automatically through the [reliability layer](/documentation/model-apis/inference/reliability).

<Card title="Learn Async Inference" icon="arrow-right" href="/documentation/model-apis/inference/queue">
  The recommended way to call models at scale
</Card>

***

## Streaming (`stream`)

For models that produce output progressively. Each event arrives as it is generated, so you can display partial results without waiting for the full response. This is useful for showing image generation previews or streaming LLM tokens.

```python theme={null}
import fal_client

for event in fal_client.stream("fal-ai/flux-kontext-lora", arguments={
    "prompt": "a sunset over mountains"
}):
    print(event)
```

<Note>
  The `stream()` method connects to the `/stream` path on the model endpoint. Not all models support streaming. Check the model's API documentation for availability.
</Note>

<Card title="Learn Streaming" icon="arrow-right" href="/documentation/model-apis/inference/streaming">
  Receive output as it's generated
</Card>

***

## Real-time (`realtime`)

For interactive applications that need the lowest possible latency. Opens a persistent WebSocket connection to a warm runner, enabling back-to-back requests without reconnection overhead. Only available for models with an explicit real-time endpoint.

```python theme={null}
import fal_client

with fal_client.realtime("fal-ai/fast-sdxl") as connection:
    connection.send({
        "prompt": "a sunset over mountains",
        "num_inference_steps": 2
    })
    result = connection.recv()
    print(result)
```

<Card title="Learn Real-time" icon="arrow-right" href="/documentation/model-apis/inference/real-time">
  WebSocket connections for interactive apps
</Card>

***

## Getting Started

Before calling any model, install and configure the fal client for your language. If you are building a browser-based app, you will also need a server-side proxy to keep your API key out of client-side code.

<CardGroup cols={2}>
  <Card title="Client Setup" icon="code" href="/documentation/model-apis/inference/client-setup">
    Install and configure the fal client
  </Card>

  <Card title="Proxy Setup" icon="shield" href="/documentation/model-apis/inference/proxy-setup">
    Keep your API key secure in client-side apps
  </Card>
</CardGroup>
