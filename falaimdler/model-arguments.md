> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Common Model Arguments

> Input parameters like seed, image_size, and safety checker that appear across many models on fal.

When you call a model on fal, everything you pass in the `arguments` dict (Python) or `input` object (JavaScript) goes into the request body as the model's input. Each model defines its own schema, and you can always find the exact schema on the model's API page (e.g., [Nano Banana 2 API](https://fal.ai/models/fal-ai/nano-banana-2/api)).

Many image generation models on fal share a set of common arguments that behave consistently across models. These are not platform-level controls (those are [platform headers](/documentation/model-apis/common-parameters) passed via the `headers` dict). They are model inputs that affect what the model generates and how. This page documents the most common ones for image generation so you don't have to look them up on every model's API page individually.

## seed

Random seed for reproducible outputs. The same seed with the same inputs produces the same result. Useful for debugging, A/B testing, or letting users "lock" a generation they like and iterate on the prompt.

|             |                 |
| ----------- | --------------- |
| **Type**    | Integer or null |
| **Default** | Random          |

<CodeGroup>
  ```python Python theme={null}
  result = fal_client.subscribe("fal-ai/nano-banana-2", arguments={
      "prompt": "a sunset",
      "seed": 42
  })
  ```

  ```javascript JavaScript theme={null}
  const result = await fal.subscribe("fal-ai/nano-banana-2", {
    input: { prompt: "a sunset", seed: 42 }
  });
  ```
</CodeGroup>

## num\_images

Number of images to generate per request. Higher values produce more results in a single call but increase processing time and cost proportionally.

|             |               |
| ----------- | ------------- |
| **Type**    | Integer       |
| **Default** | 1             |
| **Range**   | Typically 1-4 |

<CodeGroup>
  ```python Python theme={null}
  result = fal_client.subscribe("fal-ai/nano-banana-2", arguments={
      "prompt": "a sunset",
      "num_images": 4
  })
  ```

  ```javascript JavaScript theme={null}
  const result = await fal.subscribe("fal-ai/nano-banana-2", {
    input: { prompt: "a sunset", num_images: 4 }
  });
  ```
</CodeGroup>

## image\_size

Output image dimensions, used by models built with fal's [toolkit](/documentation/development/working-with-files) (such as [FLUX](https://fal.ai/models/fal-ai/flux/schnell) models). You can pass a preset string for common aspect ratios, or a custom `{width, height}` object for precise control.

| Preset           | Dimensions |
| ---------------- | ---------- |
| `square_hd`      | 1024x1024  |
| `square`         | 512x512    |
| `portrait_4_3`   | 768x1024   |
| `portrait_16_9`  | 576x1024   |
| `landscape_4_3`  | 1024x768   |
| `landscape_16_9` | 1024x576   |

<CodeGroup>
  ```python Python theme={null}
  result = fal_client.subscribe("fal-ai/flux/schnell", arguments={
      "prompt": "a sunset",
      "image_size": "landscape_16_9"
  })

  result = fal_client.subscribe("fal-ai/flux/schnell", arguments={
      "prompt": "a sunset",
      "image_size": {"width": 1280, "height": 720}
  })
  ```

  ```javascript JavaScript theme={null}
  const result = await fal.subscribe("fal-ai/flux/schnell", {
    input: { prompt: "a sunset", image_size: "landscape_16_9" }
  });

  const result = await fal.subscribe("fal-ai/flux/schnell", {
    input: { prompt: "a sunset", image_size: { width: 1280, height: 720 } }
  });
  ```
</CodeGroup>

## aspect\_ratio

Some models (such as [Nano Banana 2](https://fal.ai/models/fal-ai/nano-banana-2)) use `aspect_ratio` instead of `image_size`. This accepts a ratio string and the model determines the output resolution internally.

|                   |                                                                                             |
| ----------------- | ------------------------------------------------------------------------------------------- |
| **Type**          | String                                                                                      |
| **Default**       | Varies by model                                                                             |
| **Common values** | `"1:1"`, `"16:9"`, `"9:16"`, `"4:3"`, `"3:4"`, `"3:2"`, `"2:3"`, `"21:9"`, `"4:5"`, `"5:4"` |

<CodeGroup>
  ```python Python theme={null}
  result = fal_client.subscribe("fal-ai/nano-banana-2", arguments={
      "prompt": "a sunset",
      "aspect_ratio": "16:9"
  })
  ```

  ```javascript JavaScript theme={null}
  const result = await fal.subscribe("fal-ai/nano-banana-2", {
    input: { prompt: "a sunset", aspect_ratio: "16:9" }
  });
  ```
</CodeGroup>

<Note>
  Check the model's API page to see whether it uses `image_size` or `aspect_ratio`. Passing the wrong one will have no effect.
</Note>

## enable\_safety\_checker

Enable or disable the content safety filter on generated outputs. When enabled, fal runs an ML-based classifier on each generated image to detect NSFW content (nudity and sexual content).

|                      |                        |
| -------------------- | ---------------------- |
| **Type**             | Boolean                |
| **Default**          | `true`                 |
| **Also accepted as** | `enable_safety_checks` |

Each generated image is analyzed by a classifier after generation. Images flagged as unsafe are replaced with a black image of the same dimensions. The response includes a `has_nsfw_concepts` array indicating which images were flagged, so you can detect and handle filtered outputs in your code.

```json theme={null}
{
  "images": [
    {"url": "https://v3.fal.media/files/...", "width": 1024, "height": 1024},
    {"url": "https://v3.fal.media/files/...", "width": 1024, "height": 1024}
  ],
  "has_nsfw_concepts": [false, true]
}
```

In this example, the second image was flagged and replaced with a black image.

<CodeGroup>
  ```python Python theme={null}
  result = fal_client.subscribe("fal-ai/nano-banana-2", arguments={
      "prompt": "a sunset",
      "enable_safety_checker": True
  })

  if any(result.get("has_nsfw_concepts", [])):
      print("Some images were filtered by the safety checker")
  ```

  ```javascript JavaScript theme={null}
  const result = await fal.subscribe("fal-ai/nano-banana-2", {
    input: { prompt: "a sunset", enable_safety_checker: true }
  });

  if (result.has_nsfw_concepts?.some(Boolean)) {
    console.log("Some images were filtered by the safety checker");
  }
  ```
</CodeGroup>

To disable the safety checker:

<CodeGroup>
  ```python Python theme={null}
  result = fal_client.subscribe("fal-ai/nano-banana-2", arguments={
      "prompt": "a sunset",
      "enable_safety_checker": False
  })
  ```

  ```javascript JavaScript theme={null}
  const result = await fal.subscribe("fal-ai/nano-banana-2", {
    input: { prompt: "a sunset", enable_safety_checker: false }
  });
  ```
</CodeGroup>

<Note>
  Not all models support disabling the safety checker. Check the model's API page (e.g., [Nano Banana 2 API](https://fal.ai/models/fal-ai/nano-banana-2/api)) for the available parameters.
</Note>

## enable\_prompt\_expansion

When enabled, fal runs your prompt through an LLM before passing it to the model. The LLM rewrites short or vague prompts into richer descriptions with detail on composition, textures, colors, lighting, and mood. For example, "a sunset" might become a detailed scene description with specific lighting conditions, color palettes, and framing. This typically improves output quality for brief prompts but may alter the result if your prompt is already detailed and precise.

|                      |                                                     |
| -------------------- | --------------------------------------------------- |
| **Type**             | Boolean                                             |
| **Default**          | Varies by model                                     |
| **Also accepted as** | `expand_prompt` (some models use this name instead) |
| **Additional cost**  | Small per-request charge for the LLM inference step |

The expansion adds an LLM inference step before generation, so expect slightly higher latency per request. The expanded prompt is not returned in the response, so if you want to see what the model actually received, run the model with expansion disabled and handle prompt enhancement in your own pipeline.

<CodeGroup>
  ```python Python theme={null}
  result = fal_client.subscribe("fal-ai/nano-banana-2", arguments={
      "prompt": "a sunset",
      "expand_prompt": True
  })
  ```

  ```javascript JavaScript theme={null}
  const result = await fal.subscribe("fal-ai/nano-banana-2", {
    input: { prompt: "a sunset", expand_prompt: true }
  });
  ```
</CodeGroup>

<Note>
  Check the model's API page for the exact parameter name. Some models use `enable_prompt_expansion`, others use `expand_prompt`.
</Note>

## output\_format

Format of the generated image file. Choose based on your use case: `jpeg` for smaller file sizes with lossy compression, `png` for lossless quality with transparency support, or `webp` for a modern format that balances both.

|             |                                                 |
| ----------- | ----------------------------------------------- |
| **Type**    | String                                          |
| **Default** | Varies by model (typically `"jpeg"` or `"png"`) |
| **Values**  | `"jpeg"`, `"jpg"`, `"png"`, `"webp"`, `"gif"`   |

<CodeGroup>
  ```python Python theme={null}
  result = fal_client.subscribe("fal-ai/flux/schnell", arguments={
      "prompt": "a sunset",
      "output_format": "png"
  })
  ```

  ```javascript JavaScript theme={null}
  const result = await fal.subscribe("fal-ai/flux/schnell", {
    input: { prompt: "a sunset", output_format: "png" }
  });
  ```
</CodeGroup>
