> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Reliability

> How fal ensures high reliability for your API requests through queueing, automatic retries, and model fallbacks.

fal is designed for production workloads and includes several built-in mechanisms to ensure your requests succeed.

The platform applies three layers of protection automatically: a [queue](/documentation/model-apis/inference) that absorbs traffic spikes, retries that recover from transient failures, and model fallbacks that reroute around unhealthy endpoints. All three are enabled by default and require no configuration.

## Queue-Based Processing

The [queue system](/model-apis/model-endpoints/queue) handles traffic surges gracefully and provides request tracking. When you submit a request, it enters a managed queue that ensures reliable processing even during peak demand.

## Automatic Retries

When using the [queue](/model-apis/model-endpoints/queue), fal automatically retries requests that fail due to:

* **Server errors (503)**: The model endpoint was temporarily unavailable
* **Timeouts (504)**: The request took too long due to transient issues
* **Connection errors**: Network issues between fal infrastructure
* **Rate limits (429)**: Request waits and retries automatically when you temporarily exceed your [concurrent request limit](/model-apis/faq#is-there-a-rate-limit)

Requests are retried up to 10 times with intelligent backoff.

<Tip>
  **Limit retry duration:** Use [start timeout](/model-apis/model-endpoints/queue#start-timeout) to cap the total time a request can spend waiting (including retries). Once the timeout is reached, no further retries occur.
</Tip>

<Tip>
  **No charge for server errors**: Failed requests that return 5xx status codes are not billed.
</Tip>

<Note>
  Automatic retries only apply to queue-based requests. Direct synchronous requests return errors immediately without retry.
</Note>

For per-request control over retries and timeouts, see the Queue page -- including [disabling retries](/model-apis/model-endpoints/queue#disabling-retries) with the `X-Fal-No-Retry` header, setting a [start timeout](/model-apis/model-endpoints/queue#start-timeout) with `X-Fal-Request-Timeout`, and using [client timeout](/model-apis/model-endpoints/queue#client-timeout) to set a client-side deadline.

| Timeout                                         | Enforced by | Effect on retries                                 |
| ----------------------------------------------- | ----------- | ------------------------------------------------- |
| `start_timeout` / `X-Fal-Request-Timeout`       | Server      | Stops retries when total elapsed time is exceeded |
| `client_timeout` (Python SDK, `subscribe` only) | Client      | Client stops polling; server and retries continue |

## Model Fallbacks

For supported models, fal might automatically reroute requests to equivalent alternative endpoints if the primary endpoint is temporarily unavailable. This only occurs after fal retries the request up to five times; if those retries fail, the request is routed to a fallback endpoint. This mechanism improves overall reliability and reduces the likelihood of failed requests.

Fallbacks are enabled by default for all accounts. If you need to disable fallbacks for your account, please let your account team know. If you want to disable it per request, you can pass the `x-app-fal-disable-fallback` header. For any questions, contact our sales team.
