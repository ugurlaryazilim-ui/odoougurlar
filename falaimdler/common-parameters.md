> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Platform Headers

> HTTP headers that control request behavior across all inference methods on fal.

When you call a model or your own deployed app on fal, you can pass platform-level HTTP headers that control how the request is handled. These headers are separate from the model's input arguments (like `prompt` or `image_size`) and from SDK method parameters (like `start_timeout` or `client_timeout`). They apply at the infrastructure level -- controlling retries, payload storage, media expiration, and routing.

Some of these headers have dedicated SDK parameters that set them automatically. For example, passing `start_timeout=30` in the SDK sets `X-Fal-Request-Timeout: 30` under the hood. Others, like `X-Fal-Store-IO`, can only be set via the `headers` dict. This page documents all platform headers in one place. For headers that have SDK parameters, the corresponding method pages are linked.

***

## X-Fal-Request-Timeout (`start_timeout`)

Server-side **time-to-start** deadline in seconds. Despite the header name, this does not limit total request time. The clock starts when the request is submitted and covers queue wait, runner acquisition, and failed retry attempts. Once a runner successfully begins processing, the timeout stops and inference can run as long as it needs. If the deadline is reached before any runner starts processing, the server returns `504 Gateway Timeout` with `X-Fal-Request-Timeout-Type: user`. To limit total client-side wait time (including processing), use `client_timeout` on [`subscribe()`](/documentation/model-apis/inference/queue#client_timeout-subscribe-only) instead.

|                   |                                                                                                                                                                                                                                                  |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Header**        | `X-Fal-Request-Timeout`                                                                                                                                                                                                                          |
| **Default**       | No timeout                                                                                                                                                                                                                                       |
| **Minimum**       | > 0.1 seconds                                                                                                                                                                                                                                    |
| **SDK parameter** | `start_timeout` on [`submit()`](/documentation/model-apis/inference/queue#start-timeout), [`subscribe()`](/documentation/model-apis/inference/queue#start-timeout), and [`run()`](/documentation/model-apis/inference/synchronous#start-timeout) |

***

## X-Fal-Runner-Hint (`hint`)

Routing hint that tells fal to try to route the request to a specific runner. Useful for session affinity -- for example, keeping requests pinned to a runner that already has a LoRA adapter or conversation state loaded in memory. If the hinted runner is unavailable, fal routes to any available runner.

|                   |                                                                                                                                                                                                              |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Header**        | `X-Fal-Runner-Hint`                                                                                                                                                                                          |
| **Default**       | Automatic routing                                                                                                                                                                                            |
| **SDK parameter** | `hint` on [`submit()`](/documentation/model-apis/inference/queue#hint), [`subscribe()`](/documentation/model-apis/inference/queue#hint), and [`run()`](/documentation/model-apis/inference/synchronous#hint) |

***

## X-Fal-Queue-Priority (`priority`)

Queue priority for the request. Priority applies to the per-endpoint queue -- every request to the same endpoint shares one queue, regardless of who sent it. A low-priority request sits behind all normal-priority requests. This means setting `"low"` on a shared model API deprioritizes your request relative to all other users of that model.

|                   |                                                                                                                                                        |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Header**        | `X-Fal-Queue-Priority`                                                                                                                                 |
| **Default**       | `"normal"`                                                                                                                                             |
| **Values**        | `"normal"`, `"low"`                                                                                                                                    |
| **SDK parameter** | `priority` on [`submit()`](/documentation/model-apis/inference/queue#priority) and [`subscribe()`](/documentation/model-apis/inference/queue#priority) |

***

## X-Fal-Object-Lifecycle-Preference

Control how long generated files (images, videos, audio) are stored on fal's CDN.

|             |                                                    |
| ----------- | -------------------------------------------------- |
| **Header**  | `X-Fal-Object-Lifecycle-Preference`                |
| **Default** | Your account setting (forever if not configured)   |
| **Format**  | JSON: `{"expiration_duration_seconds": <seconds>}` |

<CodeGroup>
  ```python Python theme={null}
  import json

  result = fal_client.subscribe(
      "fal-ai/nano-banana-2",
      arguments={"prompt": "a sunset"},
      headers={
          "X-Fal-Object-Lifecycle-Preference": json.dumps({
              "expiration_duration_seconds": 3600
          })
      }
  )
  ```

  ```javascript JavaScript theme={null}
  const result = await fal.subscribe("fal-ai/nano-banana-2", {
    input: { prompt: "a sunset" },
    headers: {
      "X-Fal-Object-Lifecycle-Preference": JSON.stringify({
        expiration_duration_seconds: 3600
      })
    }
  });
  ```

  ```bash cURL theme={null}
  curl -X POST "https://queue.fal.run/fal-ai/nano-banana-2" \
    -H "Authorization: Key $FAL_KEY" \
    -H 'X-Fal-Object-Lifecycle-Preference: {"expiration_duration_seconds": 3600}' \
    -H "Content-Type: application/json" \
    -d '{"prompt": "a sunset"}'
  ```
</CodeGroup>

<Card title="Data Retention & Storage" icon="arrow-right" href="/documentation/model-apis/media-expiration">
  Full guide to media expiration, payload retention, and the delete API
</Card>

***

## X-Fal-Store-IO

Prevent fal from storing request payloads (JSON inputs and outputs). Payloads are stored for 30 days by default and power the request history in your dashboard.

|             |                            |
| ----------- | -------------------------- |
| **Header**  | `X-Fal-Store-IO`           |
| **Default** | `"1"` (stored for 30 days) |
| **Values**  | `"0"` to disable storage   |

<CodeGroup>
  ```python Python theme={null}
  result = fal_client.subscribe(
      "fal-ai/nano-banana-2",
      arguments={"prompt": "a sunset"},
      headers={"X-Fal-Store-IO": "0"}
  )
  ```

  ```javascript JavaScript theme={null}
  const result = await fal.subscribe("fal-ai/nano-banana-2", {
    input: { prompt: "a sunset" },
    headers: { "X-Fal-Store-IO": "0" }
  });
  ```

  ```bash cURL theme={null}
  curl -X POST "https://queue.fal.run/fal-ai/nano-banana-2" \
    -H "Authorization: Key $FAL_KEY" \
    -H "X-Fal-Store-IO: 0" \
    -H "Content-Type: application/json" \
    -d '{"prompt": "a sunset"}'
  ```
</CodeGroup>

<Note>
  This only prevents storage of the JSON payloads. CDN files generated during processing are still accessible (subject to [media expiration](/documentation/model-apis/media-expiration) settings).
</Note>

***

## X-Fal-No-Retry

Disable automatic retries for this request. By default, queue-based requests are retried for up to 10 total attempts on server errors (503, 504, connection errors).

|             |                                     |
| ----------- | ----------------------------------- |
| **Header**  | `X-Fal-No-Retry`                    |
| **Default** | Retries enabled                     |
| **Values**  | `"1"`, `"true"`, `"yes"` to disable |

<CodeGroup>
  ```python Python theme={null}
  result = fal_client.subscribe(
      "fal-ai/nano-banana-2",
      arguments={"prompt": "a sunset"},
      headers={"X-Fal-No-Retry": "1"}
  )
  ```

  ```javascript JavaScript theme={null}
  const result = await fal.subscribe("fal-ai/nano-banana-2", {
    input: { prompt: "a sunset" },
    headers: { "X-Fal-No-Retry": "1" }
  });
  ```

  ```bash cURL theme={null}
  curl -X POST "https://queue.fal.run/fal-ai/nano-banana-2" \
    -H "Authorization: Key $FAL_KEY" \
    -H "X-Fal-No-Retry: 1" \
    -H "Content-Type: application/json" \
    -d '{"prompt": "a sunset"}'
  ```
</CodeGroup>

<Card title="Reliability & Retries" icon="arrow-right" href="/documentation/model-apis/inference/reliability">
  Learn more about automatic retries, fallbacks, and error handling
</Card>

***

## X-Fal-Retry-Config

Set a separate retry limit for each retry condition, instead of the all-or-nothing `X-Fal-No-Retry` switch. The value is a JSON object that maps a retry condition (`server_error`, `timeout`, or `connection_error`) to an object with a `retries` count. `retries` is the number of **additional** attempts after the first, so `retries: 3` allows up to 4 total attempts for that condition. This header only works on your own apps -- it is ignored on shared or public model APIs.

|             |                                                                                 |
| ----------- | ------------------------------------------------------------------------------- |
| **Header**  | `X-Fal-Retry-Config`                                                            |
| **Default** | Platform default retries per condition                                          |
| **Values**  | JSON object, e.g. `{"timeout": {"retries": 0}, "server_error": {"retries": 3}}` |

<CodeGroup>
  ```python Python theme={null}
  import json

  result = fal_client.subscribe(
      "your-username/your-app-name",
      arguments={"prompt": "a sunset"},
      headers={
          "X-Fal-Retry-Config": json.dumps(
              {"timeout": {"retries": 0}, "server_error": {"retries": 3}}
          )
      }
  )
  ```

  ```javascript JavaScript theme={null}
  const result = await fal.subscribe("your-username/your-app-name", {
    input: { prompt: "a sunset" },
    headers: {
      "X-Fal-Retry-Config": JSON.stringify({
        timeout: { retries: 0 },
        server_error: { retries: 3 },
      }),
    }
  });
  ```

  ```bash cURL theme={null}
  curl -X POST "https://queue.fal.run/your-username/your-app-name" \
    -H "Authorization: Key $FAL_KEY" \
    -H 'X-Fal-Retry-Config: {"timeout": {"retries": 0}, "server_error": {"retries": 3}}' \
    -H "Content-Type: application/json" \
    -d '{"prompt": "a sunset"}'
  ```
</CodeGroup>

<Card title="Reliability & Retries" icon="arrow-right" href="/documentation/serverless/reliability/retries#per-request-client-side-control">
  Per-condition budgets, the overall attempt ceiling, and precedence rules
</Card>

***

## x-app-fal-disable-fallback

Disable automatic model fallbacks for this request. By default, fal may reroute requests to equivalent alternative endpoints if the primary is unavailable.

|             |                              |
| ----------- | ---------------------------- |
| **Header**  | `x-app-fal-disable-fallback` |
| **Default** | Fallbacks enabled            |

<CodeGroup>
  ```python Python theme={null}
  result = fal_client.subscribe(
      "fal-ai/nano-banana-2",
      arguments={"prompt": "a sunset"},
      headers={"x-app-fal-disable-fallback": "true"}
  )
  ```

  ```javascript JavaScript theme={null}
  const result = await fal.subscribe("fal-ai/nano-banana-2", {
    input: { prompt: "a sunset" },
    headers: { "x-app-fal-disable-fallback": "true" }
  });
  ```

  ```bash cURL theme={null}
  curl -X POST "https://queue.fal.run/fal-ai/nano-banana-2" \
    -H "Authorization: Key $FAL_KEY" \
    -H "x-app-fal-disable-fallback: true" \
    -H "Content-Type: application/json" \
    -d '{"prompt": "a sunset"}'
  ```
</CodeGroup>

<Card title="Reliability & Retries" icon="arrow-right" href="/documentation/model-apis/inference/reliability">
  Learn more about model fallbacks
</Card>

***

## fal\_max\_queue\_length

Reject the request with `429` if the endpoint's queue already has more than this many requests waiting (across all callers). Useful for latency-sensitive applications that prefer to fail fast rather than wait in a long queue.

|                 |                        |
| --------------- | ---------------------- |
| **Query param** | `fal_max_queue_length` |
| **Default**     | No limit               |
| **Type**        | Integer                |

<Note>
  This parameter is passed as a query parameter on the URL, not as a header. The SDKs do not currently expose it as a named parameter; use the raw URL approach or pass it via `headers`.
</Note>

```bash cURL theme={null}
curl -X POST "https://queue.fal.run/fal-ai/nano-banana-2?fal_max_queue_length=10" \
  -H "Authorization: Key $FAL_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "a sunset"}'
```

***

## Response Headers

These headers are returned by fal in the response. They are informational; you don't set them.

<Warning>
  The total size of all response headers is limited to **16 KB**. This includes both platform headers (listed below) and any custom headers set by the app. If the combined headers exceed 16 KB, the response will fail. This is most relevant when apps set large custom headers — for example, verbose routing hints via [`provide_hints()`](/documentation/development/advanced/optimize-routing-behavior).
</Warning>

| Header                       | Description                                                                                                                                                                                                 |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `x-fal-request-id`           | Unique identifier for the request. Use this when contacting [support](/documentation/model-apis/support) or correlating logs.                                                                               |
| `X-Fal-Billable-Units`       | Billing units charged for this request. See [Pricing](/documentation/model-apis/pricing) for how units map to cost.                                                                                         |
| `X-Fal-Served-From`          | Internal identifier of the runner that served the request.                                                                                                                                                  |
| `X-Fal-Request-Timeout-Type` | Set to `user` when your [`start_timeout`](#x-fal-request-timeout-start_timeout) deadline triggered the 504. See [Timeouts and Retries](/documentation/serverless/reliability/retries#timeouts-and-retries). |
| `X-Fal-Error-Type`           | Error category on failure responses (e.g., `request_timeout`, `startup_timeout`, `runner_disconnected`). See [Request Error Types](/documentation/model-apis/request-errors).                               |
| `x-fal-runner-hints`         | Routing hints returned by the runner for sticky session routing. See [Optimize Routing Behavior](/documentation/serverless/optimizations/optimize-routing-behavior).                                        |

<Card title="Common Model Arguments" icon="arrow-right" href="/documentation/model-apis/model-arguments">
  Common input parameters like seed, image\_size, and safety checker that appear across many models
</Card>
