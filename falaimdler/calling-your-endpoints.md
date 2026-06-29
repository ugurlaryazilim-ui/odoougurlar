> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Calling Your Endpoints

> How to call your deployed serverless endpoints using the fal client SDKs.

Once your app is deployed, you can call it using the same client SDKs and patterns used for any model on fal. Your app's endpoint ID is `your-username/your-app-name`, and all of the [inference methods](/documentation/model-apis/inference) work identically whether you are calling a marketplace model or your own deployed app.

This page shows quick examples of each calling pattern. `subscribe` is the simplest option since it handles polling for you and blocks until the result is ready. For production workloads where you need to manage many requests in parallel, `submit` gives you full control over the request lifecycle. For full details on parameters, response shapes, status polling, and cancellation, see the [Inference documentation](/documentation/model-apis/inference).

## Subscribe

Submits a request to the queue, polls automatically, and returns the result when ready. This is the simplest calling pattern since it handles the request lifecycle for you. Optionally receive progress updates via callbacks.

<Tabs>
  <Tab title="Python">
    ```python theme={null}
    import fal_client

    result = fal_client.subscribe("your-username/your-app-name", arguments={
        "prompt": "a sunset over mountains"
    })
    print(result)
    ```

    With progress updates:

    ```python theme={null}
    import fal_client

    def on_queue_update(update):
        if isinstance(update, fal_client.InProgress):
            for log in update.logs:
                print(log["message"])

    result = fal_client.subscribe(
        "your-username/your-app-name",
        arguments={"prompt": "a sunset over mountains"},
        with_logs=True,
        on_queue_update=on_queue_update,
    )
    ```
  </Tab>

  <Tab title="JavaScript">
    ```javascript theme={null}
    import { fal } from "@fal-ai/client";

    const result = await fal.subscribe("your-username/your-app-name", {
      input: { prompt: "a sunset over mountains" },
    });
    console.log(result.data);
    ```

    With progress updates:

    ```javascript theme={null}
    import { fal } from "@fal-ai/client";

    const result = await fal.subscribe("your-username/your-app-name", {
      input: { prompt: "a sunset over mountains" },
      logs: true,
      onQueueUpdate: (update) => {
        if (update.status === "IN_PROGRESS") {
          update.logs?.map((log) => console.log(log.message));
        }
      },
    });
    ```
  </Tab>
</Tabs>

<Card title="Synchronous Inference" href="/documentation/model-apis/inference/synchronous">
  Full details on subscribe, progress updates, and timeout handling
</Card>

## Queue (Async)

For fire-and-forget workflows. Submit a request, get a request ID, and retrieve the result later by polling or webhook.

<Tabs>
  <Tab title="Python">
    ```python theme={null}
    import fal_client

    handler = fal_client.submit("your-username/your-app-name", arguments={
        "prompt": "a sunset over mountains"
    })

    print(f"Request ID: {handler.request_id}")

    # Check status
    status = handler.status()
    print(status)

    # Get result when ready
    result = handler.get()
    print(result)
    ```
  </Tab>

  <Tab title="JavaScript">
    ```javascript theme={null}
    import { fal } from "@fal-ai/client";

    const { request_id } = await fal.queue.submit("your-username/your-app-name", {
      input: { prompt: "a sunset over mountains" },
    });

    console.log(`Request ID: ${request_id}`);

    // Check status
    const status = await fal.queue.status("your-username/your-app-name", {
      requestId: request_id,
      logs: true,
    });

    // Get result when ready
    const result = await fal.queue.result("your-username/your-app-name", {
      requestId: request_id,
    });
    ```
  </Tab>
</Tabs>

<Card title="Asynchronous Inference" href="/documentation/model-apis/inference/queue">
  Full details on the queue system, status polling, and REST API reference
</Card>

## Streaming

For apps that produce progressive output via Server-Sent Events (SSE). Your app must define a streaming endpoint at `/stream` using `@fal.endpoint("/stream")`.

<Tabs>
  <Tab title="Python">
    ```python theme={null}
    import fal_client

    for event in fal_client.stream("your-username/your-app-name", arguments={
        "prompt": "a sunset over mountains"
    }):
        print(event)
    ```
  </Tab>

  <Tab title="JavaScript">
    ```javascript theme={null}
    import { fal } from "@fal-ai/client";

    const stream = await fal.stream("your-username/your-app-name", {
      input: { prompt: "a sunset over mountains" },
    });

    for await (const event of stream) {
      console.log(event);
    }

    const finalResult = await stream.done();
    ```
  </Tab>
</Tabs>

<CardGroup cols={2}>
  <Card title="Building Streaming Endpoints" href="/documentation/development/streaming">
    How to implement SSE streaming in your fal.App
  </Card>

  <Card title="Streaming Inference" href="/documentation/model-apis/inference/streaming">
    Client-side streaming details and REST API
  </Card>
</CardGroup>

## Real-Time (WebSocket)

For bidirectional, low-latency communication over a persistent connection. Your app must define a `@fal.realtime("/realtime")` endpoint.

<Tabs>
  <Tab title="Python">
    ```python theme={null}
    import fal_client

    with fal_client.realtime("your-username/your-app-name") as connection:
        connection.send({"prompt": "Hello, world!"})
        result = connection.recv()
        print(result)
    ```

    Async version:

    ```python theme={null}
    import asyncio
    import fal_client

    async def main():
        async with fal_client.realtime_async("your-username/your-app-name") as connection:
            await connection.send({"prompt": "Hello, world!"})
            result = await connection.recv()
            print(result)

    asyncio.run(main())
    ```
  </Tab>

  <Tab title="JavaScript">
    ```javascript theme={null}
    import { fal } from "@fal-ai/client";

    const connection = fal.realtime.connect("your-username/your-app-name", {
      onResult: (result) => {
        console.log(result);
      },
    });

    connection.send({ prompt: "Hello, world!" });
    ```
  </Tab>
</Tabs>

<CardGroup cols={2}>
  <Card title="Building Realtime Endpoints" href="/documentation/development/realtime">
    How to implement WebSocket endpoints in your fal.App
  </Card>

  <Card title="Real-Time Inference" href="/documentation/model-apis/inference/real-time">
    Client-side real-time details and proxy setup
  </Card>
</CardGroup>

## Webhooks

Submit a request and receive the result at a URL you specify, instead of polling.

<Tabs>
  <Tab title="Python">
    ```python theme={null}
    import fal_client

    handler = fal_client.submit(
        "your-username/your-app-name",
        arguments={"prompt": "a sunset over mountains"},
        webhook_url="https://your-server.com/api/webhook",
    )

    print(f"Request ID: {handler.request_id}")
    ```
  </Tab>

  <Tab title="JavaScript">
    ```javascript theme={null}
    import { fal } from "@fal-ai/client";

    const { request_id } = await fal.queue.submit("your-username/your-app-name", {
      input: { prompt: "a sunset over mountains" },
      webhookUrl: "https://your-server.com/api/webhook",
    });
    ```
  </Tab>

  <Tab title="cURL">
    ```bash theme={null}
    curl -X POST "https://queue.fal.run/your-username/your-app-name?fal_webhook=https://your-server.com/api/webhook" \
      -H "Authorization: Key $FAL_KEY" \
      -H "Content-Type: application/json" \
      -d '{"prompt": "a sunset over mountains"}'
    ```
  </Tab>
</Tabs>

When the request completes, fal sends a `POST` to your webhook URL with the result:

```json theme={null}
{
  "request_id": "abc-123",
  "status": "OK",
  "payload": { ... }
}
```

<Card title="Webhooks API" href="/documentation/model-apis/inference/webhooks">
  Full details on webhook payloads, retries, verification, and IP allowlisting
</Card>

## Passing Headers

You can pass custom headers with any calling method to control platform behavior:

<Tabs>
  <Tab title="Python">
    ```python theme={null}
    import fal_client

    result = fal_client.subscribe(
        "your-username/your-app-name",
        arguments={"prompt": "a sunset"},
        headers={
            "x-fal-no-retry": "1",
        },
    )
    ```
  </Tab>

  <Tab title="JavaScript">
    ```javascript theme={null}
    import { fal } from "@fal-ai/client";

    const result = await fal.subscribe("your-username/your-app-name", {
      input: { prompt: "a sunset" },
      headers: {
        "x-fal-no-retry": "1",
      },
    });
    ```
  </Tab>
</Tabs>

See [Platform Headers](/documentation/model-apis/common-parameters) for all available headers, and [Retries](/documentation/serverless/reliability/retries) for retry control. Each inference method page also documents its available SDK parameters.

## Next Steps

<CardGroup cols={2}>
  <Card title="Inference Documentation" href="/documentation/model-apis/inference">
    Full details on all calling methods, parameters, status polling, and the request handle
  </Card>

  <Card title="Async Inference (Queue)" href="/documentation/model-apis/inference/queue">
    Submit, status, result, cancel, webhooks, and streaming status updates
  </Card>

  <Card title="Client Setup" href="/documentation/model-apis/inference/client-setup">
    Install and configure the fal client SDK
  </Card>

  <Card title="Handle Inputs & Outputs" href="/documentation/development/handle-inputs-and-outputs">
    Define the input/output schema for your endpoints
  </Card>
</CardGroup>
