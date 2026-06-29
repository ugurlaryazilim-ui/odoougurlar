> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Test Models and Endpoints

> Test your fal App endpoints programmatically using AppClient, which deploys an ephemeral instance and runs your tests against live infrastructure.

Before [deploying to production](/documentation/deployment/deploy-to-production), you want to verify that your endpoints produce correct outputs, handle edge cases gracefully, and perform within acceptable latency. The `AppClient` in the fal SDK gives you a way to do this programmatically -- it deploys your app to fal's serverless infrastructure in ephemeral mode, runs your tests against the live endpoints (including GPU execution, `setup()`, and the full request pipeline), and cleans up the deployment when testing is complete.

This means your tests run against the real environment your app will use in production, not a mocked local version. If your model loads correctly in `setup()`, processes inputs through your endpoint, and returns valid outputs, you can be confident the deployed version will behave the same way. You can integrate these tests into your CI pipeline to catch regressions before they reach production.

## Testing with AppClient

`AppClient` connects to your app class and exposes its endpoints as callable methods. It handles deployment, connection, and teardown automatically via a context manager.

```python theme={null}
import fal
from pydantic import BaseModel, Field
from fal.toolkit import Image

class ImageModelInput(BaseModel): # ...

class MyApp(fal.App):  # ...
    keep_alive = 300

    def setup(self): # ...

    @fal.endpoint("/")
    def generate_image(self, request: ImageModelInput) -> Image: # ...
```

Now you can write comprehensive tests for this app:

```python theme={null}
def test_myapp():
    with fal.app.AppClient.connect(MyApp) as client:
        result = client.generate_image(prompt="A cat holding a sign that says hello world")
        assert result is not None
        assert hasattr(result, 'url')
```

## Running locally with `fal run --local`

When you want a tighter feedback loop than an ephemeral deployment can give you, `fal run --local` executes your function or app on your own machine instead of provisioning a remote runner. For apps, this starts the FastAPI server on `localhost` so you can hit your endpoints directly:

```bash theme={null}
fal run --local path/to/myfile.py::MyApp
```

The startup logs print the local URL. From another terminal, call your endpoints with any HTTP client:

```bash theme={null}
curl -X POST http://localhost:8080/ \
  -H "Content-Type: application/json" \
  -d '{"prompt": "A cat holding a sign that says hello world"}'
```

This skips the remote machine spin-up entirely, which makes it well suited for quick checks while you're tweaking endpoint code, validating request and response shapes, or stepping through your app with a local debugger.

Because the app runs in your local Python environment, you are responsible for having the right dependencies and hardware available — `setup()` runs on your machine, and there is no GPU unless your machine has one. When you need to verify behavior on the real serverless environment (containers, GPUs, scaling, cold starts), use `AppClient` as shown above instead.
