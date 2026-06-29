> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Add Health Check Endpoint

> Add a health check endpoint to your fal app so the platform can detect and replace unhealthy runners.

Health check endpoints let fal verify that your [runners](/documentation/deployment/runners) are functioning correctly. When a health check fails repeatedly, fal automatically terminates the unhealthy runner and provisions a new one. This is useful for apps that depend on external services, database connections, or other resources that can become unavailable during a runner's lifetime.

You define a health check by adding an `@fal.endpoint` with the `health_check` parameter. The endpoint should be lightweight and raise an exception if the runner is in an unrecoverable state. For more on how runners start up and shut down, see [App Lifecycle](/documentation/development/app-lifecycle). For how status codes affect runner lifecycle and retries, see [Retries and Error Handling](/documentation/serverless/reliability/retries).

## Basic Usage

Use the `health_check` keyword argument in the `@fal.endpoint()` decorator to designate an endpoint as your health check:

```python theme={null}
import fal
from pydantic import BaseModel

class HealthResponse(BaseModel):
    status: str

class MyApp(fal.App):
    def setup(self):
        self.model = load_model()
        self.connection = connect_to_something()

    @fal.endpoint("/")
    def predict(self, input: Input) -> Output:
        x = self.connection.do_something(input)
        return self.model.run(x)

    @fal.endpoint(
        "/health",
        health_check=fal.HealthCheck(
            start_period_seconds=10,
            timeout_seconds=5,
            failure_threshold=3,
            call_regularly=True,
        ),
    )
    def health(self) -> HealthResponse:
        if not self.connection.is_alive():
            raise RuntimeError("Lost connection to the external service")
        return HealthResponse(status="ok")
```

<Note>
  Only one endpoint can be designated as the health check endpoint per app.
</Note>

## Configuration

| Parameter              | Type | Default | Description                                                                                                                                                |
| ---------------------- | ---- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `start_period_seconds` | int  | `30`    | Minimum time the runner has been running before health check failures count. Replaced by `startup_timeout` if that value is higher.                        |
| `timeout_seconds`      | int  | `5`     | Timeout in seconds for the health check request.                                                                                                           |
| `failure_threshold`    | int  | `3`     | Number of consecutive failures before the runner is considered unhealthy and terminated.                                                                   |
| `call_regularly`       | bool | `True`  | If true, fal calls the health check every 15 seconds. If false, health checks only run when manually triggered via the `x-fal-runner-health-check` header. |

## How It Works

By default, fal calls your health check endpoint every 15 seconds. During the `start_period_seconds` window after a runner starts, failures are ignored to give your app time to initialize. After that, if the health check fails or times out for `failure_threshold` consecutive calls, the runner is terminated and replaced. To signal an unhealthy state, raise an exception inside the health check method. Returning a normal response means the runner is healthy.

<Warning>
  The health check endpoint can be called while another request is being processed. Avoid heavy computations or acquiring GPU resources in your health check, as it could interfere with in-flight requests.
</Warning>

## Manual Health Checks

You can trigger a health check from within a regular endpoint by setting the `x-fal-runner-health-check` header on the response. This is useful when your endpoint detects a degraded state and wants the platform to verify runner health immediately.

```python theme={null}
@fal.endpoint("/predict")
def predict(self, input: Input, response: Response) -> Output:
    response.headers["x-fal-runner-health-check"] = "true"
    return self.model.run(input)
```

Manually triggered health checks bypass `failure_threshold` and `start_period_seconds`. If the subsequent health check fails, the runner is terminated immediately.

## Writing Good Health Checks

Keep your health check lightweight. It runs concurrently with normal requests, so heavy GPU work could contend with or slow down in-flight inference. For most apps, checking external dependencies (database connections, upstream APIs) is sufficient. If you do need to verify GPU health, keep the operation minimal (e.g., a small tensor allocation) to avoid interfering with active requests.

Only raise exceptions for truly unrecoverable states that require a fresh runner. For transient issues, try to recover within the health check before failing:

```python theme={null}
@fal.endpoint("/health", health_check=fal.HealthCheck(timeout_seconds=10))
def health(self) -> HealthResponse:
    if not self.connection.is_alive():
        try:
            self.connection.reconnect()
        except Exception as e:
            raise RuntimeError(f"Failed to reconnect: {e}")
    return HealthResponse(status="ok")
```

If you are concerned about the performance impact of periodic health checks, set `call_regularly=False` and trigger checks manually from your endpoints when you detect a problem.
