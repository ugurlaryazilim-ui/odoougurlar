> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Model APIs

> Access 1,000+ production-ready AI models through simple API calls

Model APIs gives you instant access to state-of-the-art AI models for image, video, audio, and multimodal generation. Every model is already optimized and production-ready, so you can [authenticate](/documentation/model-apis/authentication) and start generating immediately.

Each model runs on fal's infrastructure with automatic scaling, [queue-based reliability](/documentation/model-apis/inference/queue), and [pay-per-use billing](/documentation/model-apis/pricing). You call them the same way whether you use the [Python or JavaScript client](/documentation/model-apis/inference/client-setup) or raw HTTP. If you need to deploy your own model instead, see [Serverless](/documentation/serverless).

## Quick Example

Generate an image in three lines of code. Install the client, set your [API key](/documentation/model-apis/authentication), and call a model.

<CodeGroup>
  ```python Python theme={null}
  import fal_client

  result = fal_client.subscribe("fal-ai/nano-banana-2", arguments={
      "prompt": "a futuristic cityscape at sunset"
  })
  print(result["images"][0]["url"])
  ```

  ```javascript JavaScript theme={null}
  import { fal } from "@fal-ai/client";

  const result = await fal.subscribe("fal-ai/nano-banana-2", {
    input: { prompt: "a futuristic cityscape at sunset" }
  });
  console.log(result.data.images[0].url);
  ```

  ```bash cURL theme={null}
  curl -X POST "https://queue.fal.run/fal-ai/nano-banana-2" \
    -H "Authorization: Key $FAL_KEY" \
    -H "Content-Type: application/json" \
    -d '{"prompt": "a futuristic cityscape at sunset"}'
  ```
</CodeGroup>

The response includes a [CDN URL](/documentation/model-apis/fal-cdn) for the generated image, along with metadata like dimensions and seed. Every model follows the same pattern: send inputs as JSON, receive outputs as JSON with media URLs.

## How It Works

Every model on fal is exposed as an HTTP endpoint. You can call it directly, or go through the [queue](/documentation/model-apis/inference/queue) for automatic retries, status tracking, and scaling. There are several calling patterns depending on your use case.

**[Direct (`run`)](/documentation/model-apis/inference/synchronous)** sends a synchronous HTTP request to `fal.run` and returns the result directly. This is the simplest approach for quick scripts and prototyping.

**[Subscribe](/documentation/model-apis/inference/synchronous)** uses the queue under the hood but handles polling automatically, so it feels synchronous. This is what the Quick Example above uses.

**[Asynchronous (`submit`)](/documentation/model-apis/inference/queue)** gives you full control over the queue. Submit a request and return immediately, then poll for status or receive results via [webhook](/documentation/model-apis/inference/webhooks). This is the recommended approach for production workloads with parallel processing.

**[Streaming](/documentation/model-apis/inference/streaming)** delivers output progressively as the model generates it. This is useful for LLMs that produce tokens incrementally, or for showing generation progress in a UI.

**[`realtime()`](/documentation/model-apis/inference/real-time)** uses WebSockets for persistent connections, bypassing the queue entirely for sub-100ms latency. Only available for models with an explicit real-time endpoint.

## What You Can Generate

The [model gallery](https://fal.ai/models) has 1,000+ models spanning several categories. Here are some popular starting points.

### Image Generation and Editing

<CardGroup cols={3}>
  <Card title="Nano Banana 2" href="https://fal.ai/models/fal-ai/nano-banana-2" img="https://v3b.fal.media/files/b/0a900b9e/ptbZcVWIQ_fXGGHfv8Zez_0ea5ca41bdf143a29e21e30a53120672.jpg">
    Google's fast image generation and editing model
  </Card>

  <Card title="Nano Banana Pro" href="https://fal.ai/models/fal-ai/nano-banana-pro" img="https://v3b.fal.media/files/b/kangaroo/WcNt4yo_7RJaCZa0Og6gE_37660458463d4008959517c59a40aafd.jpg">
    State-of-the-art image generation with realism and typography
  </Card>

  <Card title="Flux 2 Flex" href="https://fal.ai/models/fal-ai/flux-2-flex" img="https://v3b.fal.media/files/b/panda/LqyVE8NElm_vf-t27Yfkz_6c1dd3323df343e4a3ec968d8f67024c.jpg">
    Enhanced typography and text rendering from BFL
  </Card>

  <Card title="Recraft V4 Pro" href="https://fal.ai/models/fal-ai/recraft/v4/pro/text-to-image" img="https://v3b.fal.media/files/b/0a8e35b5/OO8LkBQxwwkEj6SVlP3Bl_2ebfa787acba475b883a9f4ad9106032.jpg">
    Professional design and marketing visuals
  </Card>

  <Card title="Nano Banana 2 Edit" href="https://fal.ai/models/fal-ai/nano-banana-2/edit" img="https://v3b.fal.media/files/b/0a900b75/DHb_RgXoXsYLdvzQz6mdn_95e87a44239c43448939b4c382dd957c.jpg">
    Intelligent image editing with Google's latest model
  </Card>

  <Card title="FLUX Kontext Pro" href="https://fal.ai/models/fal-ai/flux-pro/kontext" img="https://v3b.fal.media/files/b/0a8691ce/SR0_u1zPJbx8jCIO6bJR0_8c83f0d66bbd48f3b55f825117941f84.jpg">
    Targeted edits and complex scene transformations
  </Card>
</CardGroup>

### Video Generation

<CardGroup cols={3}>
  <Card title="Veo 3.1" href="https://fal.ai/models/fal-ai/veo3.1" img="https://v3b.fal.media/files/b/tiger/IwzOGSbzp6e8N00QuLtFF_129417bb24f248298e95c3fa2b1b82fb.jpg">
    Google DeepMind's latest video model with sound
  </Card>

  <Card title="Kling 3.0 Pro" href="https://fal.ai/models/fal-ai/kling-video/v2.5-turbo/pro/image-to-video" img="https://v3b.fal.media/files/b/0a8cfd08/Ji4e0i6Afbeql3Wr5UTz6_ab60b14661424612bf19059e97e996a5.jpg">
    Cinematic image-to-video with fluid motion
  </Card>

  <Card title="Kling O3" href="https://fal.ai/models/fal-ai/kling-video/o3/standard/image-to-video" img="https://v3b.fal.media/files/b/0a8d2007/gV_LMXNrguqRaDB9sLqir_b5d36b36de5a40bdb5cb2cd3f8af29d7.jpg">
    Start and end frame animation with scene guidance
  </Card>

  <Card title="Sora 2" href="https://fal.ai/models/fal-ai/sora-2/text-to-video" img="https://v3b.fal.media/files/b/lion/0bXyMS_zSKpeaG3LM6ARv_d4ee6acbfd9a4168b012a848c33b154d.jpg">
    OpenAI's video model with audio generation
  </Card>

  <Card title="LTX-2 19B" href="https://fal.ai/models/fal-ai/ltx-2-19b/image-to-video" img="https://v3b.fal.media/files/b/0a8935fe/Ezbvf27opeW6gEoDS4nlw_da7064399f9c4342b5e118f6875ec389.jpg">
    Video with audio from images using LTX-2
  </Card>

  <Card title="Sora 2 Pro" href="https://fal.ai/models/fal-ai/sora-2/text-to-video/pro" img="https://v3b.fal.media/files/b/lion/0bXyMS_zSKpeaG3LM6ARv_d4ee6acbfd9a4168b012a848c33b154d.jpg">
    OpenAI's premium video model with enhanced quality
  </Card>
</CardGroup>

### Audio and Speech

<CardGroup cols={3}>
  <Card title="Chatterbox TTS" href="https://fal.ai/models/fal-ai/chatterbox/text-to-speech" img="https://fal.media/files/rabbit/FzzCnGuQNXLOEYuQq8CE8_7afb3290e0de46d5a7e4d13495938e3f.jpg">
    Natural text-to-speech from Resemble AI
  </Card>

  <Card title="MiniMax Speech-02 HD" href="https://fal.ai/models/fal-ai/minimax/speech-02-hd" img="https://fal.media/files/panda/A-mMZvJzo3C_kFbO7NmMi_28b71bd757bf4319973fb209c96453f9.jpg">
    High-quality multi-voice text-to-speech
  </Card>

  <Card title="Dia TTS" href="https://fal.ai/models/fal-ai/dia-tts/voice-clone" img="https://storage.googleapis.com/fal_cdn/fal/Sound-4.jpg">
    Multi-speaker dialogue with voice cloning
  </Card>

  <Card title="Beatoven Music" href="https://fal.ai/models/fal-ai/beatoven/music-generation" img="https://v3b.fal.media/files/b/rabbit/-fqZhGXxiW3usZOZ267NO_9c5cd9c1-62d9-4ed9-8c8e-3c148614c137.png">
    Royalty-free instrumental music generation
  </Card>

  <Card title="Beatoven SFX" href="https://fal.ai/models/fal-ai/beatoven/sound-effect-generation" img="https://v3b.fal.media/files/b/penguin/SV2axpXDRJpr3LamW4PGo_9bca6ced-1271-4fbf-9869-c8db8ff81977.png">
    Professional sound effect generation
  </Card>

  <Card title="ElevenLabs Music" href="https://fal.ai/models/fal-ai/elevenlabs/music" img="https://v3b.fal.media/files/b/0a875694/SZffdb8layV90JxfN5fkP_d2048a658d9e4dc9973598f3542833a0.jpg">
    High quality, realistic music generation
  </Card>
</CardGroup>

<Card title="Explore All Models" icon="cube" href="https://fal.ai/explore" arrow={true}>
  Browse 1,000+ models across image, video, audio, 3D, and more
</Card>

Every model page on fal.ai includes a [Playground](/documentation/model-apis/playground) for testing, full API documentation with [input/output schemas](/documentation/model-apis/common-parameters), [pricing](/documentation/model-apis/pricing), and ready-to-copy code examples.

## Next Steps

<CardGroup cols={2}>
  <Card title="Playground" icon="play" href="/documentation/model-apis/playground">
    Test and compare models interactively before integrating
  </Card>

  <Card title="Inference" icon="server" href="/documentation/model-apis/inference">
    Learn the different ways to call models
  </Card>

  <Card title="Client Setup" icon="code" href="/documentation/model-apis/inference/client-setup">
    Install and configure the fal client for Python, JavaScript, and more
  </Card>

  <Card title="Examples" icon="flask" href="/examples">
    Step-by-step tutorials for image, video, and audio generation
  </Card>
</CardGroup>
