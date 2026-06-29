> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Real-Time Inference

> WebSocket-based inference for ultra-low latency applications

Real-time inference uses WebSockets for persistent connections, enabling sub-100ms image generation. This is ideal for interactive applications like real-time creativity tools and camera-based inputs.

Unlike [queue-based inference](/documentation/model-apis/inference), real-time connections bypass the queue entirely and route inputs directly to a runner. This eliminates queue wait time, and because the WebSocket maintains a persistent connection, the runner stays warm for all subsequent messages after the initial connection. The first connection may still incur a cold start if no runner is already available. Only models with an explicit real-time endpoint are supported.

<Warning>
  Only models that explicitly support real-time inference can be used with the realtime client. Standard queue-based models do not have a realtime endpoint.
</Warning>

## Supported Models

<CardGroup cols={2}>
  <Card title="fast-lcm-diffusion" href="https://fal.ai/models/fal-ai/fast-lcm-diffusion">
    SDXL with Latent Consistency Models
  </Card>

  <Card title="fast-turbo-diffusion" href="https://fal.ai/models/fal-ai/fast-turbo-diffusion">
    Optimized SDXL Turbo
  </Card>
</CardGroup>

***

## Quick Start

<CodeGroup>
  ```javascript JavaScript theme={null}
  import { fal } from "@fal-ai/client";

  const connection = fal.realtime.connect("fal-ai/fast-lcm-diffusion", {
    onResult: (result) => {
      console.log(result);
    },
    onError: (error) => {
      console.error(error);
    },
  });

  connection.send({
    prompt: "a sunset over mountains",
    sync_mode: true,
    image_url: "data:image/png;base64,..."
  });
  ```

  ```python Python theme={null}
  import fal_client

  with fal_client.realtime("fal-ai/fast-lcm-diffusion") as connection:
      connection.send({
          "prompt": "a sunset over mountains",
          "sync_mode": True,
          "image_url": "data:image/png;base64,..."
      })
      result = connection.recv()
      print(result)
  ```

  ```python Python (async) theme={null}
  import asyncio
  import fal_client

  async def realtime():
      async with fal_client.realtime_async("fal-ai/fast-lcm-diffusion") as connection:
          await connection.send({
              "prompt": "a sunset over mountains",
              "sync_mode": True,
              "image_url": "data:image/png;base64,..."
          })
          result = await connection.recv()
          print(result)

  asyncio.run(realtime())
  ```
</CodeGroup>

***

## Performance Tips

For the fastest inference:

* Use **512x512** input dimensions (fastest)
* Provide images as base64 encoded data URLs
* Set `sync_mode: true` to receive base64 encoded responses
* 768x768 and 1024x1024 also work well, but 512x512 is optimal

***

## Keeping API Keys Secure

WebSocket connections from browsers cannot safely embed API keys. There are two approaches for client-side authentication: a proxy URL or a token provider.

### Proxy URL

The simplest approach. Point the client at a server-side proxy that adds your API key:

<CodeGroup>
  ```javascript JavaScript theme={null}
  import { fal } from "@fal-ai/client";

  fal.config({
    proxyUrl: "/api/fal/proxy",
  });

  const connection = fal.realtime.connect("fal-ai/fast-lcm-diffusion", {
    connectionKey: "realtime-demo",
    throttleInterval: 128,
    onResult(result) {
      // handle result
    },
  });
  ```

  ```swift Swift theme={null}
  import FalClient

  let fal = FalClient.withProxy("http://localhost:3333/api/fal/proxy")

  let connection = try fal.realtime.connect(
      to: "fal-ai/fast-lcm-diffusion",
      connectionKey: "realtime-demo",
      throttleInterval: .milliseconds(128)
  ) { result in
      // handle result
  }
  ```
</CodeGroup>

<Card title="Proxy Setup" icon="shield" href="/documentation/model-apis/inference/proxy-setup">
  Learn how to set up a server-side proxy
</Card>

### Token Provider

For more control, use a `tokenProvider` function that fetches short-lived JWT tokens from your backend. This is useful when you need per-user authentication or want to restrict which apps a token can access.

<Warning>
  **Protect your token endpoint with authentication.** The endpoint that generates fal tokens should verify that the request comes from an authenticated user in your application. Without proper authentication, anyone could use your endpoint to generate tokens and consume your fal credits.
</Warning>

**Client-side example:**

```typescript theme={null}
import { fal, type TokenProvider } from "@fal-ai/client";

// app includes the full endpoint path, e.g. "fal-ai/fast-lcm-diffusion/realtime"
const myTokenProvider: TokenProvider = async (app) => {
  const response = await fetch(`/api/fal/token?app=${encodeURIComponent(app)}`);
  const { token } = await response.json();
  return token;
};

const connection = fal.realtime.connect("fal-ai/fast-lcm-diffusion", {
  tokenProvider: myTokenProvider,
  tokenExpirationSeconds: 120, // match the duration from your backend
  onResult: (result) => {
    console.log(result);
  },
});

connection.send({
  prompt: "a cat",
  sync_mode: true,
});
```

Pass `tokenExpirationSeconds` to enable automatic token refresh before expiry. Set it to the same value as the `duration` in your backend's token request. If omitted, auto-refresh is disabled and your `tokenProvider` is called once at connection time.

**Next.js API Route example (`app/api/fal/token/route.ts`):**

```typescript theme={null}
import { NextRequest, NextResponse } from "next/server";

export async function GET(request: NextRequest) {
  // IMPORTANT: Add your own authentication logic here
  // const session = await getServerSession();
  // if (!session) {
  //   return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  // }

  const { searchParams } = new URL(request.url);
  const app = searchParams.get("app");

  if (!app) {
    return NextResponse.json({ error: "Missing app parameter" }, { status: 400 });
  }

  const response = await fetch("https://rest.fal.ai/tokens/realtime", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Key ${process.env.FAL_KEY}`,
    },
    // app includes the full path (e.g. "fal-ai/fast-lcm-diffusion/realtime")
    body: JSON.stringify({
      allowed_apps: [app],
      duration: 120,
    }),
  });

  const data = await response.json();
  return NextResponse.json({ token: data.token });
}
```

<Note>
  The `tokenProvider` also works for streaming with `connectionMode: "client"`:

  ```typescript theme={null}
  const stream = await fal.stream("fal-ai/flux/dev", {
    connectionMode: "client",
    tokenProvider: myTokenProvider,
    input: { prompt: "a cat" },
  });
  ```
</Note>

***

## Differences from Queue-Based Inference

Real-time WebSocket connections bypass the queue and connect directly to a runner. Several request parameters that work with queue-based inference do not apply:

| Parameter         | Behavior with Real-Time                                        |
| ----------------- | -------------------------------------------------------------- |
| `start_timeout`   | No effect. There is no queue wait                              |
| `priority`        | No effect. No queue ordering                                   |
| `webhook_url`     | Not supported. Results stream back over the WebSocket          |
| Automatic retries | Not available. Failed messages return errors on the connection |
| `X-Fal-No-Retry`  | No effect. No retry mechanism to disable                       |

## Custom WebSocket Path

By default, the realtime client connects to the `/realtime` path on the app (e.g., `wss://fal.run/fal-ai/my-app/realtime`). If your app exposes a realtime endpoint at a different path, use the `path` option:

```typescript theme={null}
const connection = fal.realtime.connect("fal-ai/my-app", {
  path: "/my-custom-ws",
  onResult: (result) => console.log(result),
});
```

In Python, pass the `path` parameter to `realtime()`:

```python theme={null}
connection = fal_client.realtime("fal-ai/my-app", path="/my-custom-ws", on_result=handle_result)
```

***

## Realtime vs Streaming

Both realtime and [streaming](/documentation/model-apis/inference/streaming) give you faster feedback than polling, but they serve different use cases.

| Feature        | Realtime (WebSocket)                    | Streaming (SSE)                   |
| -------------- | --------------------------------------- | --------------------------------- |
| **Direction**  | Bidirectional (client and server)       | One-way (server to client)        |
| **Connection** | Persistent, reusable                    | New connection per request        |
| **Latency**    | Lower (connection reuse)                | Higher (new connection each time) |
| **Best for**   | Interactive apps, back-to-back requests | Progressive output, previews      |
| **Protocol**   | Binary msgpack (default, customizable)  | JSON over SSE                     |

Use realtime when clients send multiple requests in quick succession over a persistent connection, like interactive image editing or camera-based inputs. Use streaming when you want to show progressive output from a single request, like image generation previews or LLM tokens.

## Protocol Details

The realtime client uses [msgpack](https://msgpack.org/) for binary serialization by default across all SDKs, which is more efficient than JSON for transmitting image data. In Python, `realtime()` and `realtime_async()` provide a `RealtimeConnection` with `send()` and `recv()` methods. In JavaScript, `fal.realtime.connect()` uses callback-based `onResult` and `onError` handlers.

In the JavaScript client, you can customize the message encoding by passing `encodeMessage` and `decodeMessage` options. For example, to use JSON instead of msgpack:

```typescript theme={null}
const connection = fal.realtime.connect("fal-ai/my-app", {
  encodeMessage: (input) => JSON.stringify(input),
  decodeMessage: (data) => JSON.parse(data),
  onResult: (result) => console.log(result),
});
```

## Video Tutorial

Build a Real-Time AI Image App with WebSockets, Next.js, and fal.ai:

<Frame>
  <iframe className="w-full aspect-video rounded-lg" srcdoc="<style>*{padding:0;margin:0;overflow:hidden}html,body{height:100%}img,span{position:absolute;width:100%;top:0;bottom:0;margin:auto}span{height:1.5em;text-align:center;font:48px/1.5 sans-serif;color:white;text-shadow:0 0 0.5em black}</style><a href='https://www.youtube.com/embed/freyCo3pcz4?si=OFfGsi0xwJVe__Yt&autoplay=1'><img src='/docs/images/video-thumbs/realtime.jpg' alt='YouTube video player'><span>▶</span></a>" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen />
</Frame>
