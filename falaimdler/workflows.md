> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Workflow Endpoints

> Workflows are a way to chain multiple models together to create a more complex pipeline. This allows you to create a single endpoint that can take an input and pass it through multiple models in sequence. This is useful for creating more complex models that require multiple steps, or for creating a single endpoint that can handle multiple tasks.

Workflows let you chain multiple models together into a single endpoint, creating complex pipelines that run as one API call. Instead of orchestrating individual model requests yourself, you define the steps and fal handles the execution, passing outputs from one model as inputs to the next.

Unlike standard model calls that return a single result, workflows emit streaming events as each step progresses, giving you access to intermediate results along the way. This makes them ideal for multi-step generation tasks where you want real-time feedback. For more on consuming streaming responses, see [streaming inference](/documentation/model-apis/inference/streaming).

## Workflow as an API

Workflow APIs work the same way as other model endpoints, you can simply send a request and get a response back. However, it is common for workflows to contain multiple steps and produce intermediate results, as each step contains their own response that could be relevant in your use-case.

Therefore, workflows benefit from the **streaming** feature, which allows you to get partial results as they are being generated.

## Workflow events

The workflow API will trigger a few events during its execution, these events can be used to monitor the progress of the workflow and get intermediate results. Below are the events that you can expect from a workflow stream:

### The `submit` event

This event is triggered every time a new step has been submitted to execution. It contains the `app_id`, `request_id` and the `node_id`.

```json theme={null}
{
  "type": "submit",
  "node_id": "stable_diffusion_xl",
  "app_id": "fal-ai/fast-sdxl",
  "request_id": "d778bdf4-0275-47c2-9f23-16c27041cbeb"
}
```

### The `completion` event

This event is triggered upon the completion of a specific step.

```json theme={null}
{
  "type": "completion",
  "node_id": "stable_diffusion_xl",
  "output": {
    "images": [
      {
        "url": "https://fal.media/result.jpeg",
        "width": 1024,
        "height": 1024,
        "content_type": "image/jpeg"
      }
    ],
    "timings": { "inference": 2.1733 },
    "seed": 6252023,
    "has_nsfw_concepts": [false],
    "prompt": "a cute puppy"
  }
}
```

### The `output` event

The `output` event means that the workflow has completed and the final result is ready.

```json theme={null}
{
  "type": "output",
  "output": {
    "images": [
      {
        "url": "https://fal.media/result.jpeg",
        "width": 1024,
        "height": 1024,
        "content_type": "image/jpeg"
      }
    ]
  }
}
```

### The `error` event

The `error` event is triggered when an error occurs during the execution of a step. The `error` object contains the `error.status` with the HTTP status code, an error `message` as well as `error.body` with the underlying error serialized.

```json theme={null}
{
  "type": "error",
  "node_id": "stable_diffusion_xl",
  "message": "Error while fetching the result of the request d778bdf4-0275-47c2-9f23-16c27041cbeb",
  "error": {
    "status": 422,
    "body": {
      "detail": [
        {
          "loc": ["body", "num_images"],
          "msg": "ensure this value is less than or equal to 8",
          "type": "value_error.number.not_le",
          "ctx": { "limit_value": 8 }
        }
      ]
    }
  }
}
```

## Example

A cool and simple example of the power of workflows is `workflows/fal-ai/sdxl-sticker`, which consists of three steps:

<Steps>
  <Step>
    Generates an image using `fal-ai/fast-sdxl`.
  </Step>

  <Step>
    Remove the background of the image using `fal-ai/imageutils/rembg`.
  </Step>

  <Step>
    Converts the image to a sticker using `fal-ai/face-to-sticker`.
  </Step>
</Steps>

What could be a tedious process of running and coordinating three different models is now a single endpoint that you can call with a single request.

<Tabs>
  <Tab title="Javascript" icon="js">
    ```js theme={null}
    import { fal } from "@fal-ai/client";

    const stream = await fal.stream("workflows/fal-ai/4x4-grid-images", {
    input: {
      prompt: "a cute puppy, in the style of pixar animation",
    },
    });

    for await (const event of stream) {
    console.log("partial", event);
    }

    const result = await stream.done();

    console.log("final result", result);
    ```
  </Tab>

  <Tab title="python" icon="python">
    ```python theme={null}
    import fal_client

    stream = fal_client.stream(
        "workflows/fal-ai/4x4-grid-images",
        arguments={
            "prompt": "a cute puppy, in the style of pixar animation",
        },
    )
    for event in stream:
        print(event)
    ```
  </Tab>

  <Tab title="python (async)" icon="python">
    ```python theme={null}
    import asyncio
    import fal_client

    async def main():
        stream = await fal_client.stream_async(
            "workflows/fal-ai/4x4-grid-images",
            arguments={
                "prompt": "a cute puppy, in the style of pixar animation",
            },
        )

        async for event in stream:
            print(event)


    if __name__ == "__main__":
        asyncio.run(main())
    ```
  </Tab>

  <Tab title="Swift" icon="swift">
    <Note>
      **Coming soon**

      The Swift client does not support streaming yet.
    </Note>
  </Tab>
</Tabs>

## Type definitions

Below are the type definition in TypeScript of events that you can expect from a workflow stream:

```ts theme={null}
type WorkflowBaseEvent = {
  type: "submit" | "completion" | "error" | "output";
  node_id: string;
};

export type WorkflowSubmitEvent = WorkflowBaseEvent & {
  type: "submit";
  app_id: string;
  request_id: string;
};

export type WorkflowCompletionEvent<Output = any> = WorkflowBaseEvent & {
  type: "completion";
  app_id: string;
  output: Output;
};

export type WorkflowDoneEvent<Output = any> = WorkflowBaseEvent & {
  type: "output";
  output: Output;
};

export type WorkflowErrorEvent = WorkflowBaseEvent & {
  type: "error";
  message: string;
  error: any;
};
```
