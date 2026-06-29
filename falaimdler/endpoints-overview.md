> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Define Your Endpoints

> How to define, structure, and configure the API endpoints your fal App exposes to callers.

Every [fal App](/documentation/getting-started/apps-and-execution) exposes one or more endpoints that callers interact with through the fal client SDKs or REST API. An endpoint is a Python method decorated with `@fal.endpoint("/path")` that receives input, runs your model or logic, and returns output. The simplest app has a single root endpoint at `/`, but you can define as many endpoints as you need at different paths, including specialized [streaming](/documentation/development/streaming) and [real-time](/documentation/development/realtime) endpoints for progressive and bidirectional communication.

This section covers everything involved in building endpoints, from defining input and output schemas to handling files, cancellations, and observability. If you have already set up your [application environment](/documentation/development/app-setup) and [loaded your model](/documentation/development/download-model-weights-and-files), this is where you define how users interact with it. Each page below focuses on a specific aspect of endpoint development. Start with a basic endpoint, then layer on the capabilities you need.

## A Basic Endpoint

At minimum, an endpoint is a method on your `fal.App` class decorated with `@fal.endpoint`. It receives typed input and returns typed output. The types you use determine both the API schema and how the [Playground](/documentation/model-apis/playground) renders the input form and output preview.

```python theme={null}
import fal
from pydantic import BaseModel

class Input(BaseModel):
    prompt: str

class Output(BaseModel):
    text: str

class MyApp(fal.App):
    machine_type = "GPU-A100"

    def setup(self):
        self.model = load_model()

    @fal.endpoint("/")
    def generate(self, input: Input) -> Output:
        result = self.model(input.prompt)
        return Output(text=result)
```

You can define multiple endpoints on the same app at different paths. Callers reach non-root endpoints by appending the path to the endpoint URL (e.g., `https://fal.run/your-username/your-app/enhance`).

```python theme={null}
class MyApp(fal.App):
    @fal.endpoint("/")
    def generate(self, input: GenerateInput) -> GenerateOutput:
        ...

    @fal.endpoint("/enhance")
    def enhance(self, input: EnhanceInput) -> EnhanceOutput:
        ...
```

## What's in This Section

The pages below cover each aspect of endpoint development. [Handle Inputs and Outputs](/documentation/development/handle-inputs-and-outputs) explains how to define Pydantic schemas that control both API validation and how the Playground renders your input form and output preview. [Working with Files](/documentation/development/working-with-files) covers downloading input files and uploading generated outputs to the CDN at runtime.

For progressive output, [Streaming](/documentation/development/streaming) shows how to send partial results to clients via Server-Sent Events. For bidirectional communication with persistent connections, see [Realtime](/documentation/development/realtime). [Testing](/documentation/development/test-models-and-endpoints) covers automated endpoint testing and CI setup, [Health Checks](/documentation/development/add-health-check-endpoint) let fal detect and replace unhealthy runners, and [Cancellations](/documentation/development/handle-cancellations) show how to free GPU resources when callers cancel in-flight requests.
