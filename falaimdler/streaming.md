> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Streaming Inference

> Get progressive output as it's generated

Streaming allows you to receive output progressively as the model generates it. Instead of waiting for the full result, you process each chunk as it arrives. This is useful for LLMs that produce tokens incrementally, models that generate intermediate previews, or any situation where you want to show progress to the user.

Under the hood, `stream()` sends a direct HTTP request to `fal.run` using [Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events) (SSE). The SDK wraps the SSE connection into an iterator, so each event arrives as a parsed object. Streaming does not use the [queue](/documentation/model-apis/inference/queue), so there are no automatic retries.

<Note>
  Streaming is only supported by models that have a `/stream` endpoint. Check the model's API page to confirm support before using `stream()`.
</Note>

## Using `stream()`

<CodeGroup>
  ```python Python theme={null}
  import fal_client

  for event in fal_client.stream("fal-ai/flux/schnell", arguments={
      "prompt": "a sunset over mountains"
  }):
      print(event)
  ```

  ```python Python (async) theme={null}
  import asyncio
  import fal_client

  async def main():
      async for event in fal_client.stream_async("fal-ai/flux/schnell", arguments={
          "prompt": "a sunset over mountains"
      }):
          print(event)

  asyncio.run(main())
  ```

  ```javascript JavaScript theme={null}
  import { fal } from "@fal-ai/client";

  const stream = await fal.stream("fal-ai/flux/schnell", {
    input: { prompt: "a sunset over mountains" }
  });

  for await (const event of stream) {
    console.log(event);
  }
  ```

  ```bash cURL theme={null}
  curl -N -X POST "https://fal.run/fal-ai/flux/schnell/stream" \
    -H "Authorization: Key $FAL_KEY" \
    -H "Content-Type: application/json" \
    -d '{"prompt": "a sunset over mountains"}'
  ```
</CodeGroup>

Each event is a dictionary/object whose shape depends on the model. The REST API returns SSE-formatted events (each line prefixed with `data: `). The SDKs parse these automatically into objects. A model might stream progress updates followed by the final result:

```json theme={null}
{"progress": 0.25, "message": "Generating..."}
{"progress": 0.50, "message": "Generating..."}
{"progress": 0.75, "message": "Generating..."}
{"images": [{"url": "https://v3.fal.media/files/..."}], "seed": 42}
```

## `stream()` Parameters

### `path`

Endpoint path appended to the model ID. Defaults to `"/stream"` for streaming endpoints. See [`path` reference](/documentation/model-apis/inference/queue#path).

### `timeout`

Client-side HTTP timeout in seconds -- how long the client waits for the SSE connection. See [`timeout` reference](/documentation/model-apis/inference/synchronous#timeout).

<Note>
  `stream()` does not support `hint`, `priority`, `start_timeout`, `client_timeout`, or `headers` because it bypasses the queue and sends a direct HTTP request. There are no retries. If you need queue-backed reliability, use [`submit()`](/documentation/model-apis/inference/queue) and poll for status with `with_logs=True` to track progress.
</Note>

## When to Use Streaming

Streaming is best for LLMs, chat models, showing real-time progress to users, and reducing perceived latency in interactive applications. It is not needed for models that return a single result with no intermediate output, or backend-to-backend integrations where you just need the final response. In those cases, [`run()`](/documentation/model-apis/inference/synchronous) or [`subscribe()`](/documentation/model-apis/inference/synchronous) is simpler.
