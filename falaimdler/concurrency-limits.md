> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Concurrency Limits

> Understand and manage how many requests you can run simultaneously on fal.

Concurrency limits control how many requests your account can process at the same time. Every fal account has a global concurrency limit that determines how many requests can be in the [`IN_PROGRESS`](/documentation/model-apis/inference/queue#request-lifecycle) state simultaneously. When you reach your limit, additional requests wait in the [queue](/documentation/model-apis/inference/queue) and are dispatched as soon as a slot frees up. Requests are never rejected due to concurrency limits.

Your concurrency limit is determined by your credit purchase history and scales automatically as you buy more credits. The limit applies at the platform level across all endpoints you call, though fal can also set per-endpoint limits on specific high-demand models. Understanding how these limits work helps you plan capacity for production workloads and avoid unexpected throttling. If you are deploying your own apps on [Serverless](/documentation/serverless), note that concurrency limits do not apply when you call your own endpoints.

## How It Works

When you submit a request, the platform tracks it against your concurrency limit only while a [runner](/documentation/deployment/runners) is actively processing it (the `IN_PROGRESS` state). Requests in the `IN_QUEUE` state do not count toward your limit. This means you can submit as many requests as you want to the queue, but only a limited number will be dispatched to runners at any given time.

The enforcement mechanism depends on how you call the model. For [queue-based requests](/documentation/model-apis/inference) (`subscribe` or `submit`), the platform checks your concurrency before dispatching a queued request to a runner. If you are at capacity, the request stays in the queue and is retried with exponential backoff until a slot opens. There is no maximum retry count for concurrency-related requeues, so your request will eventually be processed regardless of how long it needs to wait. For direct requests (`run`), the gateway checks concurrency at request time and the [fal client](/documentation/model-apis/inference/client-setup) handles retries automatically.

<Note>
  Requests are never dropped due to concurrency limits. For queue-based requests, they wait in the queue and are dispatched when capacity is available. For direct requests, the SDK retries automatically. The only scenario where a request can be dropped while waiting is if you set a [`start_timeout`](/documentation/model-apis/inference/queue#start_timeout) and the deadline expires before a slot opens.
</Note>

## Default Limits

Every new account starts with a concurrency limit of **2** concurrent requests. As you purchase credits, the platform automatically increases your limit based on the total amount of paid invoices from the last four weeks. Self-serve limits scale up to **40** concurrent requests. The adjustment happens when a credit purchase invoice is paid, so the change typically takes effect within a few minutes of purchasing credits.

You can view your current limit and spending tier on the [Concurrency page](https://fal.ai/dashboard/usage-billing/concurrency) in the dashboard.

## Viewing Your Limit

You can view your current concurrency limit, real-time request count, and a 30-day usage history chart on the [Concurrency page](https://fal.ai/dashboard/usage-billing/concurrency) in your dashboard. This page also shows your peak concurrent usage, which is helpful for determining whether you need to upgrade.

## Increasing Your Limit

The most direct way to increase your limit is to purchase credits. You can do this from the [Concurrency page](https://fal.ai/dashboard/usage-billing/concurrency) in your dashboard. Once the payment is processed, your limit is updated automatically based on the thresholds above.

For limits above 40 concurrent requests, or for custom per-endpoint allocations, [contact the sales team](https://fal.ai/enterprise#contact-sales). Enterprise plans can be configured with higher global limits or dedicated per-endpoint limits tailored to your workload.

## Per-Endpoint Limits

In addition to the global account limit, fal may apply additional concurrency limits on certain high-demand models to ensure fair access across all users. If you are experiencing throttling on a specific model and believe you need a higher allocation, [contact sales](https://fal.ai/enterprise#contact-sales).

## Concurrency and the fal Client

Both `fal_client.run()` and `fal_client.subscribe()` handle concurrency limits automatically. The fal client includes built-in retry logic for `429` responses, retrying with exponential backoff up to 10 times. You do not need to implement manual retry logic when using the SDK.

The key difference is how the retry happens. With `subscribe()` (or `submit()`), the retry is handled server-side by the [queue](/documentation/model-apis/inference/queue), which requeues the request with no maximum retry count. With `run()`, the retry is handled client-side by the SDK, which retries the HTTP request up to 10 times. For production workloads, `subscribe()` is the recommended approach because it provides more durable retry behavior.

```python theme={null}
import fal_client

# Recommended: queue-based call handles concurrency limits server-side
result = fal_client.subscribe("fal-ai/flux/schnell", arguments={
    "prompt": "a sunset over mountains"
})
```

If you are making raw HTTP requests without the SDK, a `429` response with the `concurrent_requests_limit` type indicates you have hit your concurrency limit. The response includes an `X-Fal-needs-retry: 1` header. You should retry with exponential backoff:

```bash theme={null}
curl -X POST "https://fal.run/fal-ai/flux/schnell" \
  -H "Authorization: Key $FAL_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "a sunset over mountains"}'

# On 429 with type "concurrent_requests_limit":
# Retry with exponential backoff (1s, 2s, 4s, 8s...)
```

<CardGroup cols={2}>
  <Card title="Reliability & Retries" icon="arrow-right" href="/documentation/model-apis/inference/reliability">
    Learn more about automatic retries and error handling
  </Card>

  <Card title="Error Reference" icon="arrow-right" href="/documentation/model-apis/errors">
    Full list of error types and how to handle them
  </Card>
</CardGroup>
