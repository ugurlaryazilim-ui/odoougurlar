> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Request Headers

> Access request headers in your fal App for logging, tracing, and per-request logic.

Every request to your [fal App](/documentation/getting-started/apps-and-execution) passes through the fal gateway before reaching your runner. The gateway injects headers like the request ID and caller identity, and forwards any custom headers the caller included. You can read all of these inside your endpoint handler via `self.current_request.headers.get()`.

Request headers are per-request context, complementing [environment variables](/documentation/development/environment-variables) which are per-runner context. Use headers when you need to identify the specific request or caller (for logging, tracing, or per-user logic), and environment variables for runner-wide information like `FAL_APP_NAME` or `FAL_KEY`.

```python theme={null}
import fal

class MyApp(fal.App):
    machine_type = "GPU-A100"

    @fal.endpoint("/")
    def generate(self, prompt: str) -> dict:
        request_id = self.current_request.headers.get("x-fal-request-id")
        caller_id = self.current_request.headers.get("x-fal-caller-user-id")

        print(f"Request {request_id} from {caller_id}")
        return {"result": "..."}
```

***

## Available Headers

| Header                 | Description                                                                    |
| ---------------------- | ------------------------------------------------------------------------------ |
| `x-fal-request-id`     | Unique identifier for this request. Use for log correlation and debugging.     |
| `x-fal-caller-user-id` | The caller's user ID (hashed for third-party apps). Useful for per-user logic. |
| `x-fal-endpoint`       | The full endpoint path being called (e.g., `your-user/your-app/`).             |

Custom headers passed by the caller are also forwarded to your app. Headers starting with `x-fal-` are reserved for the gateway and cannot be set by callers.

***

## Correlating with External Tools

### Sentry

Attach the request ID to Sentry events so you can find the exact fal request that caused an error:

```python theme={null}
import fal

class MyApp(fal.App):
    machine_type = "GPU-A100"
    requirements = ["sentry-sdk"]

    def setup(self):
        import sentry_sdk
        sentry_sdk.init(dsn="https://your-sentry-dsn")
        self.model = load_model()

    @fal.endpoint("/")
    def generate(self, prompt: str) -> dict:
        import sentry_sdk
        sentry_sdk.set_tag("fal_request_id", self.current_request.headers.get("x-fal-request-id"))
        return {"image": self.model(prompt)}
```

### Structured Logging

Include the request ID in your log output for correlation with fal's built-in [logs](/documentation/development/logging):

```python theme={null}
import fal
import logging

logger = logging.getLogger(__name__)

class MyApp(fal.App):
    machine_type = "GPU-A100"

    @fal.endpoint("/")
    def generate(self, prompt: str) -> dict:
        rid = self.current_request.headers.get("x-fal-request-id")
        logger.info("Processing request", extra={"request_id": rid})

        result = self.model(prompt)

        logger.info("Request complete", extra={"request_id": rid})
        return {"image": result}
```

***

## Custom Headers

Callers can pass custom headers that are forwarded to your app:

```python theme={null}
# Caller passes a custom header
result = fal_client.subscribe("your-user/your-app", arguments={
    "prompt": "a sunset"
}, headers={
    "X-My-Trace-Id": "abc-123",
    "X-My-User-Tier": "premium"
})
```

```python theme={null}
# Your app reads it
@fal.endpoint("/")
def generate(self, prompt: str) -> dict:
    trace_id = self.current_request.headers.get("x-my-trace-id")
    user_tier = self.current_request.headers.get("x-my-user-tier")
    ...
```

<Note>
  Header names are case-insensitive. `X-My-Header` and `x-my-header` both work.
</Note>

## Response Header Size Limit

The total size of all response headers returned by your app is limited to **16 KB**. This includes platform headers injected by fal (like `x-fal-request-id` and `X-Fal-Billable-Units`) and any custom headers your app sets, such as billing units or routing hints from [`provide_hints()`](/documentation/development/advanced/optimize-routing-behavior). If the combined headers exceed 16 KB, the response will fail.

Keep custom header values short. If you use `provide_hints()`, avoid returning large lists of model names or long strings — each hint value contributes to the total header size.

<Note>
  [Platform headers](/documentation/model-apis/common-parameters) like `X-Fal-Request-Timeout`, `X-Fal-No-Retry`, `X-Fal-Retry-Config`, and `X-Fal-Store-IO` are processed by the gateway before reaching your runner. They are not available in `self.current_request.headers`. Only identity headers (`x-fal-request-id`, `x-fal-caller-user-id`, `x-fal-endpoint`) and custom caller headers are forwarded to your app.
</Note>

<Card title="Environment Variables" href="/documentation/development/environment-variables">
  Per-runner context: FAL\_KEY, FAL\_APP\_NAME, FAL\_RUNNER\_STATE, and more
</Card>
