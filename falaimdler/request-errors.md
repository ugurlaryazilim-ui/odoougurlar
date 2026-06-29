> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Request Error Types

> Infrastructure-level error types for timeouts, runner failures, and connection errors.

When a request fails due to infrastructure-level issues rather than model validation, the platform returns a structured error response with a machine-readable `error_type` field. These errors cover timeouts, runner crashes, scheduling failures, and connection problems that occur before or during request processing.

Request errors use a different response format than [model validation errors](/documentation/model-apis/errors). Model errors return a `detail` array of typed error objects. Request errors return a flat object with `detail` as a human-readable string and `error_type` as a machine-readable category. The same value is also available in the `X-Fal-Error-Type` response header for programmatic access without parsing the body.

## Response Structure

| Property     | Description                                                                 |
| :----------- | :-------------------------------------------------------------------------- |
| `detail`     | A human-readable description of the error.                                  |
| `error_type` | A machine-readable string identifying the error category (see table below). |

```json theme={null}
{
  "detail": "Request timed out",
  "error_type": "request_timeout"
}
```

The `X-Fal-Error-Type` response header contains the same value as `error_type`.

## Error Type Reference

| Error Type                   | Description                                                    | Typical Status Code |
| :--------------------------- | :------------------------------------------------------------- | :------------------ |
| `request_timeout`            | The request exceeded the allowed processing time.              | 504                 |
| `startup_timeout`            | The runner did not start within the allowed time.              | 504                 |
| `runner_scheduling_failure`  | No runner could be allocated to handle the request.            | 503                 |
| `runner_connection_timeout`  | The connection to the runner timed out.                        | 503                 |
| `runner_disconnected`        | The runner disconnected unexpectedly during processing.        | 503                 |
| `runner_connection_refused`  | The runner refused the connection.                             | 503                 |
| `runner_connection_error`    | A general connection error occurred with the runner.           | 503                 |
| `runner_incomplete_response` | The runner sent an incomplete response payload.                | 502                 |
| `runner_server_error`        | The runner encountered an internal server error.               | 500                 |
| `client_disconnected`        | The client closed the connection before the response was sent. | 499                 |
| `client_cancelled`           | The request was cancelled by the client.                       | 499                 |
| `bad_request`                | The request was malformed (e.g., invalid timeout header).      | 400                 |
| `internal_error`             | An unexpected internal error occurred.                         | 500                 |

## Handling Request Errors

**For retry logic:** Use `error_type` to decide whether to retry. Runner and timeout errors (e.g., `runner_connection_timeout`, `startup_timeout`) are typically transient and worth retrying. Client errors (`client_disconnected`, `bad_request`) should not be retried. See [Retries and Error Handling](/documentation/serverless/reliability/retries) for how the platform handles retries automatically.

**For monitoring:** The `error_type` is also available in [queue status responses](/documentation/model-apis/inference/queue#request-lifecycle) for failed requests, making it useful for tracking failure patterns in your [analytics dashboard](/documentation/serverless/observability/app-analytics).

<CardGroup cols={2}>
  <Card title="Model Errors" icon="triangle-exclamation" href="/documentation/model-apis/errors">
    Validation errors from model inputs (images, video, audio)
  </Card>

  <Card title="Retries" icon="rotate" href="/documentation/serverless/reliability/retries">
    How fal automatically retries failed requests
  </Card>
</CardGroup>
