> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Realtime Endpoints

> Build low-latency, bidirectional WebSocket endpoints for interactive applications that require persistent connections and back-to-back requests.

Realtime endpoints use WebSockets for bidirectional communication over a persistent connection. Once a client connects, it can send multiple inputs and receive results without the overhead of establishing new connections for each request. This makes them ideal for interactive applications like real-time image editing, live camera filters, or game-like experiences where latency between requests needs to be minimal.

You define a realtime endpoint using the `@fal.realtime("/realtime")` decorator, which uses fal's binary msgpack protocol for efficient serialization. Callers connect using the [`realtime()` method](/documentation/model-apis/inference/real-time) in the fal client SDKs. For one-way progressive output from a single request (like showing diffusion steps), use [Streaming Endpoints](/documentation/development/streaming) instead -- they use SSE and are simpler when you don't need bidirectional communication.

<Warning>
  WebSocket endpoints are not currently testable on the fal Playground. You can monitor your WebSocket endpoint activity through the **Logs** page in the fal dashboard.
</Warning>

## How Realtime Works

Under a `fal.App`, the `@fal.realtime()` decorator makes your endpoint compatible with [fal's real-time clients](/documentation/model-apis/inference/real-time). It uses fal's binary msgpack protocol for efficient serialization and eliminates connection establishing overhead for repeated requests.

<Info>
  **Important:** The `fal_client.realtime()` method automatically connects to the `/realtime` path on your app. If you use `@fal.realtime()`, you **must** set the path to `/realtime` (e.g., `@fal.realtime("/realtime")`) for the client to connect successfully.
</Info>

For power users who want to build stateful applications with their own real-time protocol, a `@fal.endpoint` can
be initialized with `is_websocket=True` flag and the underlying function will receive the raw WebSocket connection and
can choose to use it however it wants.

## Server-Side Implementation

Here's an example of a fal app with both a regular HTTP endpoint and a WebSocket endpoint:

```python theme={null}
import fal
from pydantic import BaseModel
from fastapi import WebSocket


class Input(BaseModel):
    prompt: str


class Output(BaseModel):
    output: str


class RealtimeApp(fal.App):
    keep_alive = 60

    @fal.endpoint("/")
    def generate(self, input: Input) -> Output:
        return Output(output=input.prompt)

    @fal.realtime("/realtime")
    def generate_rt(self, input: Input) -> Output:
        return Output(output=input.prompt)

    @fal.endpoint("/echo", is_websocket=True)
    async def generate_ws(self, websocket: WebSocket) -> None:
        await websocket.accept()
        msg = await websocket.receive_text()
        for idx in range(3):
            print(f"Sending message {idx}")
            await websocket.send_text(msg + f"-{idx}")
        await websocket.close()
```

## Client-Side Connection

### Connecting to `@fal.realtime()` Endpoints

For endpoints decorated with `@fal.realtime()`, use `fal_client.realtime()` or `fal_client.realtime_async()`. These methods handle serialization automatically using fal's binary protocol:

```python theme={null}
import fal_client

# Connect to a @fal.realtime() endpoint
with fal_client.realtime("your-username/your-app-name") as connection:
    connection.send({"prompt": "Hello, world!"})
    result = connection.recv()
    print(result)
```

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

### Connecting to Raw WebSocket Endpoints

For endpoints using `is_websocket=True`, use `fal_client.ws_connect()` or `fal_client.ws_connect_async()` for direct WebSocket access:

```python theme={null}
import fal_client

# Connect to a raw WebSocket endpoint
# The path parameter specifies the endpoint path (e.g., "/echo")
with fal_client.ws_connect("your-username/your-app-name", path="/echo") as ws:
    ws.send("Hello, world!")
    for _ in range(3):
        message = ws.recv()
        print(message)
```

```python theme={null}
import asyncio
import fal_client

async def main():
    async with fal_client.ws_connect_async("your-username/your-app-name", path="/echo") as ws:
        await ws.send("Hello, world!")
        for _ in range(3):
            message = await ws.recv()
            print(message)

asyncio.run(main())
```

<Note>
  * For `@fal.realtime()` endpoints: Use `fal_client.realtime()` - serialization is handled automatically.
  * For raw `is_websocket=True` endpoints: Use `fal_client.ws_connect()` with the `path` parameter to specify the endpoint path.
</Note>

## WebRTC Transport

For applications that need direct video/audio streaming (webcam feeds, live game rendering), you can use WebRTC as the transport layer on top of fal's WebSocket infrastructure. WebRTC provides lower latency for media streams compared to sending frames over msgpack.

The pattern uses `@fal.endpoint("/webrtc", is_websocket=True)` to handle WebRTC signaling, while the actual media flows peer-to-peer between the browser and your runner. For a higher-level wrapper that handles the signaling, tracks, and frame batching for you, see the experimental [World Model Accelerator (WMA)](/documentation/development/wma).

<CardGroup cols={2}>
  <Card title="Real-time World Model" icon="globe" href="/examples/video-generation/deploy-realtime-world-model">
    Deploy a live world model with WebRTC video streaming
  </Card>

  <Card title="Real-time Video-to-Video" icon="video" href="/examples/video-generation/deploy-realtime-video-to-video-model">
    Run YOLO detections on a live webcam feed via WebRTC
  </Card>
</CardGroup>

## Next Steps

<CardGroup cols={2}>
  <Card title="Streaming Endpoints" icon="water" href="/documentation/development/streaming">
    Stream progressive results (image previews, video updates) using SSE
  </Card>

  <Card title="Real-time Client Docs" icon="book" href="/documentation/model-apis/inference/real-time">
    Client library documentation for realtime connections
  </Card>
</CardGroup>
