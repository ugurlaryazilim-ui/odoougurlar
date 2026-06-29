> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Logging

> Understand how logs are captured, scoped, and surfaced across runner logs, request logs, and the Playground.

Logging is essential for debugging your [fal App](/documentation/getting-started/apps-and-execution) during development and monitoring it after [deployment](/documentation/deployment/deploy-to-production). Every message your app writes to `stdout` or `stderr` is captured by fal and made available through the dashboard, CLI, and queue status API. This means `print()` statements, Python `logging` output, and even error tracebacks are all collected automatically.

The most important thing to understand about logging on fal is that logs exist at different scopes, and each scope determines who can see them and where they appear. Runner logs capture everything a runner does across its lifetime. Request logs are the subset visible to callers. Playground logs appear in real-time during testing. Knowing which scope you are working with helps you decide what information is safe to log and where to look when debugging.

<Frame>
  <iframe className="w-full aspect-video rounded-lg" srcdoc="<style>*{padding:0;margin:0;overflow:hidden}html,body{height:100%}img,span{position:absolute;width:100%;top:0;bottom:0;margin:auto}span{height:1.5em;text-align:center;font:48px/1.5 sans-serif;color:white;text-shadow:0 0 0.5em black}</style><a href='https://www.youtube.com/embed/gDJJ9bppyV8?start=345&end=441&autoplay=1'><img src='/docs/images/video-thumbs/logging.jpg' alt='Logs - fal Serverless'><span>▶</span></a>" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen />
</Frame>

## Runner Logs

Runner logs capture the full output of a [runner](/documentation/deployment/runners) process from the moment it starts until it shuts down. This includes output from `setup()` (model loading, initialization), every request the runner handles, and any background output between requests. Runner logs are visible only to the app owner through the [dashboard](https://fal.ai/dashboard/logs) and CLI.

Use runner logs for internal diagnostics: model loading times, memory usage, cache behavior, and anything that spans the runner's lifetime rather than a single request.

```python theme={null}
class MyApp(fal.App):
    def setup(self):
        print("Loading model weights...")  # This appears in runner logs
        self.model = load_model()
        print(f"Model loaded, VRAM: {torch.cuda.memory_allocated() / 1e9:.1f}GB")
```

You can view runner logs in the CLI with [`fal runners logs <runner-id>`](/reference/cli/runners), or in the [dashboard](https://fal.ai/dashboard/logs) filtered by runner ID.

## Request Logs

Request logs are the portion of runner logs emitted while a specific request is being processed. They are time-scoped: fal captures the start and end of each request and extracts the log messages in between. These are the logs that callers see when they poll for [queue status](/documentation/model-apis/inference/queue#check-status) with `with_logs=True` (Python) or `logs: true` (JavaScript).

```python theme={null}
class MyApp(fal.App):
    @fal.endpoint("/")
    def run(self, prompt: str) -> dict:
        print(f"Generating for prompt: {prompt}")  # Visible to callers
        result = self.model(prompt)
        print(f"Generation complete, inference time: {result.time:.2f}s")
        return {"image": result.image}
```

Because request logs are visible to anyone calling your app, be careful about what you log during request handling. Avoid logging secrets, user data, or internal model details that should not be exposed.

### Private Logs

If your request logs contain sensitive information, you can make them private so only you (the app owner) can see them. Callers polling the queue will see no log output — logs are still captured and visible in the dashboard and CLI, but non-owners receive empty log arrays in their status responses.

There are two ways to make logs private: per-app via the `private_logs` option, or account-wide via the Log Privacy setting.

#### Per-app

Set `private_logs=True` in the class definition to make logs private for that app only:

```python theme={null}
class MyApp(fal.App, private_logs=True):
    @fal.endpoint("/")
    def run(self, prompt: str) -> dict:
        print("This log is only visible to the app owner")
        return {"result": "..."}
```

A per-app `private_logs=True` always makes that app's logs private, regardless of the account-level default.

#### Account-wide default

Under [Dashboard → Settings → Log Privacy](https://fal.ai/dashboard/account/log-privacy), the **Default Private Logs** toggle controls the default visibility of logs across all your apps.

When enabled, log visibility for non-owners is restricted on newly deployed apps — they inherit `private_logs=True` at registration time without needing to set it explicitly in code. Existing apps retain their current setting until redeployed; redeploy an app to pick up the current account default.

An app that explicitly sets `private_logs=True` is always private. An app that does not set `private_logs` at all follows the account default in effect when it was deployed.

## Playground Logs

When you test your app in the [Playground](/documentation/model-apis/playground), logs appear in real-time in the output panel as your endpoint processes the request. The Playground shows request logs (the same logs callers would see via the queue API), so you can verify exactly what output your users will receive.

During development with [`fal run`](/reference/cli/run), logs also stream directly to your terminal, giving you immediate feedback without needing the dashboard.

## Writing Logs

For quick debugging, `print()` is the simplest approach. Both `stdout` and `stderr` are captured.

```python theme={null}
import fal
import sys

class MyApp(fal.App):
    @fal.endpoint("/")
    def run(self) -> dict:
        print("Processing request...")
        print("Warning: cache miss", file=sys.stderr)
        return {"message": "Hello, World!"}
```

For production apps, use Python's standard `logging` module to control log levels and message format. A good pattern is to route INFO and WARNING to `stdout` and ERROR and above to `stderr`, so you can filter by severity when reviewing logs.

```python theme={null}
import logging
import sys
import fal


def get_logger():
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.INFO)
    stdout_handler.addFilter(lambda record: record.levelno < logging.ERROR)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.ERROR)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[stdout_handler, stderr_handler],
    )
    return logging.getLogger("my_app")


class MyApp(fal.App):
    def setup(self):
        self.logger = get_logger()

    @fal.endpoint("/")
    def run(self) -> dict:
        self.logger.info("Started request processing")
        try:
            result = {"message": "Hello, World!"}
            self.logger.info("Request completed successfully")
            return result
        except Exception:
            self.logger.exception("Request failed")
            raise
```

<Tip>
  Include the request ID in your log output for easier debugging. You can access it via `self.current_request.request_id` in your endpoint handler. See [Request Headers](/documentation/development/request-headers) for all available per-request context including caller identity and custom headers.
</Tip>

<Warning>
  Avoid logging secrets, API keys, or large raw payloads. Log IDs, sizes, and high-level status instead.
</Warning>

## Log Sources

When filtering logs in the dashboard or CLI, the `source` field tells you where the logs came from:

* `run` - logs from runners created by [`fal run`](/reference/cli/run) during development
* `gateway` - logs from runners serving deployed apps in production
* `deploy` - logs emitted by the deployment process itself when using [`fal deploy`](/reference/cli/deploy)

## Where to View Logs

| What you need                       | Where to look                                                                                                                                                      |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| All logs for a specific runner      | [Dashboard](https://fal.ai/dashboard/logs) filtered by runner ID, or [`fal runners logs <runner-id>`](/reference/cli/runners) in the CLI                           |
| Logs for a specific request         | [Dashboard](https://fal.ai/dashboard/logs) filtered by request ID, or [queue status API](/documentation/model-apis/inference/queue#check-status) with logs enabled |
| Real-time logs during development   | Terminal output from [`fal run`](/reference/cli/run)                                                                                                               |
| Real-time logs in the browser       | [Dashboard logs page](https://fal.ai/dashboard/logs) streams all runner logs in real-time. Playground shows request-filtered logs only.                            |
| Logs filtered by deployment version | [Dashboard](https://fal.ai/dashboard/logs) filtered by version ID                                                                                                  |
