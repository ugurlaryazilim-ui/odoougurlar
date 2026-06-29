> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Handle Request Cancellations

> Handle in-flight request cancellations to free GPU resources when callers cancel queued or processing requests.

When a caller [cancels a request](/documentation/model-apis/inference/queue#cancel-a-request) through the queue API, fal handles it differently depending on the request's state. If the request is still waiting in the [queue](/documentation/model-apis/inference/queue), it is removed and never processed. If a runner is already processing the request, fal sends a cancellation signal to your app so you can stop work, release GPU resources, and leave the app in a clean state.

For direct connections ([`run()`](/documentation/model-apis/inference/synchronous), [streaming](/documentation/model-apis/inference/streaming), and [real-time](/documentation/model-apis/inference/real-time)), cancellation also triggers automatically when the caller drops the HTTP or WebSocket connection -- for example, if their process crashes or the connection times out. This does not apply to queue-based requests ([`submit()`](/documentation/model-apis/inference/queue), [`subscribe()`](/documentation/model-apis/inference/synchronous)), where the connection closes after submission and only an explicit cancel API call can stop the request.

Without cancellation handling, a cancelled request continues consuming GPU time until it finishes naturally. For long-running operations like video generation or training, this can waste significant compute. By implementing a cancel endpoint, you give fal a way to tell your running code to stop early, so the runner can move on to the next request.

## How Cancellation Works

fal routes cancellation requests to your endpoint's path with a `/cancel` suffix. For an endpoint at `/predict`, the cancellation arrives at `/predict/cancel`. Both the original request and the cancellation carry the same `x-fal-request-id` header, which you use to match the cancellation to the right in-flight task.

<Steps>
  <Step title="Caller submits a request">
    fal assigns a `request_id` and routes the request to a runner. The caller receives the request handle.

    <CodeGroup>
      ```python Python theme={null}
      handler = fal_client.submit("your-username/your-app", arguments={"prompt": "a sunset"})
      print(handler.request_id)
      ```

      ```javascript JavaScript theme={null}
      const { request_id } = await fal.queue.submit("your-username/your-app", {
        input: { prompt: "a sunset" },
      });
      ```
    </CodeGroup>
  </Step>

  <Step title="Your endpoint begins processing">
    The runner calls your endpoint. You wrap the work in an `asyncio.Task` and store it by request ID so the cancel endpoint can find it later.

    ```python focus={9-19} theme={null}
    class MyApp(fal.App):
        def setup(self):
            self._tasks: dict[str, asyncio.Task] = {}

        async def _generate(self, input: GenerateInput):
            await asyncio.sleep(30)
            return {"result": f"Generated from: {input.prompt}"}

        @fal.endpoint("/predict")
        async def predict(
            self,
            input: GenerateInput,
            x_fal_request_id: str | None = fastapi.Header(None),
        ):
            if not x_fal_request_id:
                raise ValueError("x-fal-request-id is required")

            task = asyncio.create_task(self._generate(input))
            self._tasks[x_fal_request_id] = task
            try:
                return await task
            except asyncio.CancelledError:
                print(f"Request {x_fal_request_id} was cancelled")
                raise RequestCancelledException("Request cancelled")
            finally:
                self._tasks.pop(x_fal_request_id, None)

        @fal.endpoint("/predict/cancel")
        async def predict_cancel(
            self,
            x_fal_request_id: str | None = fastapi.Header(None),
        ):
            if not x_fal_request_id:
                raise ValueError("x-fal-request-id is required")

            task = self._tasks.get(x_fal_request_id)
            if task is None:
                raise ValueError("No task found for this request ID")

            if task.done():
                raise ValueError("Task has already completed")

            task.cancel()
    ```
  </Step>

  <Step title="Caller cancels the request">
    The caller decides to cancel -- either via the SDK, the REST API, or by disconnecting (for direct connections only).

    <CodeGroup>
      ```python Python theme={null}
      handler.cancel()
      ```

      ```javascript JavaScript theme={null}
      await fal.queue.cancel("your-username/your-app", {
        requestId: request_id,
      });
      ```

      ```bash cURL theme={null}
      curl -X PUT "https://queue.fal.run/your-username/your-app/requests/{request_id}/cancel" \
        -H "Authorization: Key $FAL_KEY"
      ```
    </CodeGroup>
  </Step>

  <Step title="fal calls your cancel endpoint">
    fal tracks which endpoint path each request was sent to. When a cancel arrives, it looks up the original path and appends `/cancel`. So if the request was routed to `/predict`, fal sends the cancellation to `/predict/cancel` on the same runner, with the same `x-fal-request-id` header. Your cancel endpoint looks up the task and cancels it.

    ```python focus={28-43} theme={null}
    class MyApp(fal.App):
        def setup(self):
            self._tasks: dict[str, asyncio.Task] = {}

        async def _generate(self, input: GenerateInput):
            await asyncio.sleep(30)
            return {"result": f"Generated from: {input.prompt}"}

        @fal.endpoint("/predict")
        async def predict(
            self,
            input: GenerateInput,
            x_fal_request_id: str | None = fastapi.Header(None),
        ):
            if not x_fal_request_id:
                raise ValueError("x-fal-request-id is required")

            task = asyncio.create_task(self._generate(input))
            self._tasks[x_fal_request_id] = task
            try:
                return await task
            except asyncio.CancelledError:
                print(f"Request {x_fal_request_id} was cancelled")
                raise RequestCancelledException("Request cancelled")
            finally:
                self._tasks.pop(x_fal_request_id, None)

        @fal.endpoint("/predict/cancel")
        async def predict_cancel(
            self,
            x_fal_request_id: str | None = fastapi.Header(None),
        ):
            if not x_fal_request_id:
                raise ValueError("x-fal-request-id is required")

            task = self._tasks.get(x_fal_request_id)
            if task is None:
                raise ValueError("No task found for this request ID")

            if task.done():
                raise ValueError("Task has already completed")

            task.cancel()
    ```
  </Step>

  <Step title="Your main endpoint handles the cancellation">
    Back in step 2, the `await task` now raises `CancelledError`. Your main endpoint catches it and raises `RequestCancelledException` to signal to fal that the cancellation was handled cleanly (returns a 499 status code). The `finally` block cleans up the task reference regardless of outcome.

    ```python focus={20-26} theme={null}
    class MyApp(fal.App):
        def setup(self):
            self._tasks: dict[str, asyncio.Task] = {}

        async def _generate(self, input: GenerateInput):
            await asyncio.sleep(30)
            return {"result": f"Generated from: {input.prompt}"}

        @fal.endpoint("/predict")
        async def predict(
            self,
            input: GenerateInput,
            x_fal_request_id: str | None = fastapi.Header(None),
        ):
            if not x_fal_request_id:
                raise ValueError("x-fal-request-id is required")

            task = asyncio.create_task(self._generate(input))
            self._tasks[x_fal_request_id] = task
            try:
                return await task
            except asyncio.CancelledError:
                print(f"Request {x_fal_request_id} was cancelled")
                raise RequestCancelledException("Request cancelled")
            finally:
                self._tasks.pop(x_fal_request_id, None)

        @fal.endpoint("/predict/cancel")
        async def predict_cancel(
            self,
            x_fal_request_id: str | None = fastapi.Header(None),
        ):
            if not x_fal_request_id:
                raise ValueError("x-fal-request-id is required")

            task = self._tasks.get(x_fal_request_id)
            if task is None:
                raise ValueError("No task found for this request ID")

            if task.done():
                raise ValueError("Task has already completed")

            task.cancel()
    ```
  </Step>
</Steps>

<Note>
  Cancellation is cooperative. If your task is blocked on a synchronous GPU operation (like a PyTorch inference call), the cancellation won't take effect until the operation completes and Python checks for the cancel signal. For long-running synchronous operations, consider breaking them into checkpoints where you can check for cancellation.
</Note>

`RequestCancelledException` is a special exception from `fal.exceptions` that returns a 499 status code to fal, signaling that the cancellation was handled cleanly. This tells the gateway that the runner is in a good state and can accept new requests. If you let `CancelledError` propagate unhandled instead, FastAPI returns a 500 error, which does not terminate the runner but does not cleanly signal that cancellation was handled either.

## Full Example

```python theme={null}
import asyncio

import fal
from fal.exceptions import RequestCancelledException
import fastapi
from pydantic import BaseModel


class GenerateInput(BaseModel):
    prompt: str


class MyApp(fal.App):
    def setup(self):
        self._tasks: dict[str, asyncio.Task] = {}

    async def _generate(self, input: GenerateInput):
        await asyncio.sleep(30)
        return {"result": f"Generated from: {input.prompt}"}

    @fal.endpoint("/predict")
    async def predict(
        self,
        input: GenerateInput,
        x_fal_request_id: str | None = fastapi.Header(None),
    ):
        if not x_fal_request_id:
            raise ValueError("x-fal-request-id is required")

        task = asyncio.create_task(self._generate(input))
        self._tasks[x_fal_request_id] = task
        try:
            return await task
        except asyncio.CancelledError:
            print(f"Request {x_fal_request_id} was cancelled")
            raise RequestCancelledException("Request cancelled")
        finally:
            self._tasks.pop(x_fal_request_id, None)

    @fal.endpoint("/predict/cancel")
    async def predict_cancel(
        self,
        x_fal_request_id: str | None = fastapi.Header(None),
    ):
        if not x_fal_request_id:
            raise ValueError("x-fal-request-id is required")

        task = self._tasks.get(x_fal_request_id)
        if task is None:
            raise ValueError("No task found for this request ID")

        if task.done():
            raise ValueError("Task has already completed")

        task.cancel()
```
