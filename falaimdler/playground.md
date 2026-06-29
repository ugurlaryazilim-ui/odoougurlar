> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Playground

> Test any model with real inputs, see results, and copy working code.

Every model on fal has a Playground where you can try it with real inputs, see outputs instantly, and copy working code in Python, JavaScript, or cURL. When you [deploy your own app](/documentation/serverless), it gets a Playground too, so your teammates and users can test it the same way.

<Frame>
  <img src="https://mintcdn.com/fal-d8505a2e/8WsQEbl1OYp5vQ4g/images/examples/playground-nano-banana-2.png?fit=max&auto=format&n=8WsQEbl1OYp5vQ4g&q=85&s=e230ae5495b191fca50bd9ec27194ab4" alt="Playground for Nano Banana 2 on fal.ai" width="1920" height="1088" data-path="images/examples/playground-nano-banana-2.png" />
</Frame>

The Playground is the fastest way to validate a model before writing any integration code. Once you have a result you like, copy the generated code into your project and you are ready to go. If you want to compare multiple models side by side, use the [Sandbox](/documentation/model-apis/sandbox) instead. For programmatic access, see [Client Setup](/documentation/model-apis/inference/client-setup).

## Try It

The best way to understand the Playground is to open one. Pick a model and start generating.

<CardGroup cols={3}>
  <Card title="Nano Banana 2" href="https://fal.ai/models/fal-ai/nano-banana-2" img="https://v3b.fal.media/files/b/0a900b9e/ptbZcVWIQ_fXGGHfv8Zez_0ea5ca41bdf143a29e21e30a53120672.jpg">
    Google's fast image generation and editing
  </Card>

  <Card title="Veo 3.1" href="https://fal.ai/models/fal-ai/veo3.1" img="https://v3b.fal.media/files/b/tiger/IwzOGSbzp6e8N00QuLtFF_129417bb24f248298e95c3fa2b1b82fb.jpg">
    Google DeepMind's latest video model with sound
  </Card>

  <Card title="ElevenLabs Music" href="https://fal.ai/models/fal-ai/elevenlabs/music" img="https://v3b.fal.media/files/b/0a875694/SZffdb8layV90JxfN5fkP_d2048a658d9e4dc9973598f3542833a0.jpg">
    High quality, realistic music generation
  </Card>
</CardGroup>

## What the Playground Shows

Each model page on fal.ai (for example, [Nano Banana 2](https://fal.ai/models/fal-ai/nano-banana-2)) is organized into tabs. The **Playground** tab lets you fill in inputs and run the model directly in your browser. The **API** tab shows the full input and output schemas with type information, so you know exactly what fields are available and what the response looks like. The page also displays pricing, average latency, and ready-to-copy code examples.

## Testing a Model

<Steps>
  <Step title="Find a model">
    Browse the [model gallery](https://fal.ai/models) or search for a specific model. Click on it to open its page.
  </Step>

  <Step title="Fill in the inputs">
    The Playground form is auto-generated from the model's input schema. Required fields are marked, and optional fields have sensible defaults. For models that accept images, video, or audio, you can upload files directly.
  </Step>

  <Step title="Run the model">
    Click **Run** to submit your request. The result appears below the form, typically within a few seconds.
  </Step>

  <Step title="Iterate">
    Adjust your inputs and run again. Each result stays visible so you can compare outputs across runs.
  </Step>
</Steps>

## Copying Code

Every Playground result includes generated code that reproduces the exact request you just ran. Click the code tab to see examples in Python, JavaScript, and cURL, then copy them directly into your project.

<CodeGroup>
  ```python Python theme={null}
  import fal_client

  result = fal_client.subscribe("fal-ai/nano-banana-2", arguments={
      "prompt": "a futuristic cityscape at sunset",
      "aspect_ratio": "16:9"
  })
  print(result["images"][0]["url"])
  ```

  ```javascript JavaScript theme={null}
  import { fal } from "@fal-ai/client";

  const result = await fal.subscribe("fal-ai/nano-banana-2", {
    input: {
      prompt: "An action shot of a black lab swimming in an inground suburban swimming pool. The camera is placed meticulously on the water line, dividing the image in half, revealing both the dogs head above water holding a tennis ball in it's mouth, and it's paws paddling underwater."
    },
    logs: true,
    onQueueUpdate: (update) => {
      if (update.status === "IN_PROGRESS") {
        update.logs.map((log) => log.message).forEach(console.log);
      }
    },
  });
  console.log(result.data);
  console.log(result.requestId);
  ```

  ```bash cURL theme={null}
  curl -X POST "https://queue.fal.run/fal-ai/nano-banana-2" \
    -H "Authorization: Key $FAL_KEY" \
    -H "Content-Type: application/json" \
    -d '{"prompt": "a futuristic cityscape at sunset", "aspect_ratio": "16:9"}'
  ```
</CodeGroup>

The generated code includes all the parameters you configured in the form, so there is no gap between what you tested and what you ship.

## Your Own Apps

When you run `fal deploy`, the output includes a Playground URL for your app. This means anyone with access can test your endpoints through the same interface that powers the model gallery.

```bash theme={null}
fal deploy my_app.py::MyApp
# Output includes:
#   Playground: https://fal.ai/models/your-username/my-app
```

To control how your app's inputs render in the Playground (image uploaders, hidden fields, field ordering), see [Handle Inputs and Outputs](/documentation/development/handle-inputs-and-outputs). For example, naming a field with an `image_url` suffix renders it as an image upload widget, and wrapping a field in `Hidden()` keeps it accessible via API but hides it from the Playground form.

## Playground vs Sandbox

The Playground and the [Sandbox](https://fal.ai/sandbox) serve different purposes. The Playground is for testing a single model with specific inputs and copying code. The Sandbox is for comparing multiple models at once, with features like model sets, cost estimates, search across past generations, and shareable links.

|                     | Playground                | Sandbox                                  |
| ------------------- | ------------------------- | ---------------------------------------- |
| **Purpose**         | Test one model, copy code | Compare multiple models                  |
| **Where**           | Each model's page         | [fal.ai/sandbox](https://fal.ai/sandbox) |
| **Your own apps**   | Yes, after `fal deploy`   | Yes, can be added manually               |
| **Code generation** | Python, JS, cURL          | Not available                            |
| **Sharing**         | Not available             | Shareable links with previews            |

## More Models to Try

<CardGroup cols={3}>
  <Card title="Nano Banana 2 Edit" href="https://fal.ai/models/fal-ai/nano-banana-2/edit" img="https://v3b.fal.media/files/b/0a900b75/DHb_RgXoXsYLdvzQz6mdn_95e87a44239c43448939b4c382dd957c.jpg">
    Intelligent image editing
  </Card>

  <Card title="Kling 3.0 Pro" href="https://fal.ai/models/fal-ai/kling-video/v2.5-turbo/pro/image-to-video" img="https://v3b.fal.media/files/b/0a8cfd08/Ji4e0i6Afbeql3Wr5UTz6_ab60b14661424612bf19059e97e996a5.jpg">
    Cinematic image-to-video
  </Card>

  <Card title="Sora 2" href="https://fal.ai/models/fal-ai/sora-2/text-to-video" img="https://v3b.fal.media/files/b/lion/0bXyMS_zSKpeaG3LM6ARv_d4ee6acbfd9a4168b012a848c33b154d.jpg">
    OpenAI's video model with audio
  </Card>

  <Card title="Recraft V4 Pro" href="https://fal.ai/models/fal-ai/recraft/v4/pro/text-to-image" img="https://v3b.fal.media/files/b/0a8e35b5/OO8LkBQxwwkEj6SVlP3Bl_2ebfa787acba475b883a9f4ad9106032.jpg">
    Professional design visuals
  </Card>

  <Card title="Chatterbox TTS" href="https://fal.ai/models/fal-ai/chatterbox/text-to-speech" img="https://fal.media/files/rabbit/FzzCnGuQNXLOEYuQq8CE8_7afb3290e0de46d5a7e4d13495938e3f.jpg">
    Natural text-to-speech
  </Card>

  <Card title="Browse All" icon="cube" href="https://fal.ai/explore">
    1,000+ models to explore
  </Card>
</CardGroup>
