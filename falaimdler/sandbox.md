> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Sandbox

> Sandbox is your creative playground for testing and comparing the latest AI models across all popular media generation operations. Compare models side-by-side, estimate costs before running, and share your creations.

Sandbox is your creative playground for testing and comparing the latest AI models across all popular media generation operations. Run any prompt through multiple models at once to quickly find the best fit for your use case.

Whether you're generating images from text, animating photos into videos, upscaling content, or creating music and sound effects or many other operations, [Sandbox](https://fal.ai/sandbox) provides a unified interface to experiment with multiple state-of-the-art models simultaneously.

## Try it

<CardGroup cols={3}>
  <Card title="Generate an Image" href="https://fal.ai/sandbox/image/text-to-image" img="https://v3b.fal.media/files/b/0a900b9e/ptbZcVWIQ_fXGGHfv8Zez_0ea5ca41bdf143a29e21e30a53120672.jpg">
    Text-to-image with Nano Banana 2, FLUX, Recraft, and more
  </Card>

  <Card title="Generate a Video" href="https://fal.ai/sandbox/video/image-to-video" img="https://v3b.fal.media/files/b/tiger/IwzOGSbzp6e8N00QuLtFF_129417bb24f248298e95c3fa2b1b82fb.jpg">
    Image-to-video with Veo 3.1, Kling, Sora 2, and more
  </Card>

  <Card title="Generate Music" href="https://fal.ai/sandbox/audio/text-to-music" img="https://v3b.fal.media/files/b/0a875694/SZffdb8layV90JxfN5fkP_d2048a658d9e4dc9973598f3542833a0.jpg">
    Text-to-music with ElevenLabs, Beatoven, MiniMax, and more
  </Card>
</CardGroup>

## What you can do

* **Compare models side-by-side**: Run the same prompt or input across multiple models to see which produces the best results for your use case
* **Test all major operations**: Text-to-image, image editing, video generation, upscaling, background removal, audio generation, and more
* **Estimate costs before running**: See the estimated cost for your selected models and quantity before submitting
* **Search your generations**: Find previous results by text, image similarity, or dominant color
* **Share your creations**: Generate shareable links with social media previews

## Supported operations

### Image

| Operation             | Description                                        |
| --------------------- | -------------------------------------------------- |
| **Text to Image**     | Generate images from text prompts                  |
| **Edit Image**        | Modify an image using a prompt and reference image |
| **Edit Multi-Images** | Apply edits using multiple reference images        |
| **Upscale**           | Increase image resolution with AI enhancement      |
| **Remove Background** | Extract subjects from their backgrounds            |

### Video

| Operation             | Description                                          |
| --------------------- | ---------------------------------------------------- |
| **Text to Video**     | Generate videos from text prompts                    |
| **Image to Video**    | Animate a still image into a video                   |
| **Start + End Frame** | Generate a video that transitions between two images |
| **Upscale**           | Enhance video resolution                             |
| **Remove Background** | Remove backgrounds from video clips                  |
| **Video to Audio**    | Generate audio/sound effects for a video             |

### Audio

| Operation                 | Description                            |
| ------------------------- | -------------------------------------- |
| **Text to Music**         | Generate music from a description      |
| **Text to Speech**        | Convert text into spoken audio         |
| **Text to Sound Effects** | Create sound effects from descriptions |

## Key concepts

### Canonical input

Different AI models, even when performing the same task, often have different input schemas. For example, one image generation model might accept `prompt` while another uses `text` or `description`.

Sandbox solves this with **canonical input** — a standardized input format for each operation type. When you fill out the form in Sandbox, you're providing canonical input. Behind the scenes, Sandbox automatically remaps your input to match each model's expected schema.

For example, when you enter a prompt in the image editing operation:

* The canonical field is `prompt`
* It may be remapped to `text`, `edit_prompt`, or `instruction` depending on the model
* Image URL fields may be remapped to `image`, `source_image`, `input_image`, etc.

This means the actual API request sent to each model may have a slightly different input shape than what you see in Sandbox, but the semantic meaning is preserved.

### Model sets

With many models available for each operation, selecting the right ones can be overwhelming. **Model sets** solve this by grouping models into curated collections:

* **State of the Art**: The best-performing models for general use
* **Anime Style**: Models optimized for anime and illustration aesthetics
* **Fast Generation**: Models prioritizing speed over maximum quality
* **Custom Sets**: Create your own collections for specific workflows

To use a model set:

1. Click the "explore sets" button in the prompt bar
2. Pick a pre-built set or create your own from the modal

Model sets are operation-specific — each operation type has its own available model sets.

### Runs and requests

Understanding Sandbox's structure:

* **Run**: A single submission in Sandbox. When you click "Run", you create one run.
* **Requests**: Individual API calls to each model within a run. If you select 3 models with quantity 2x, your run contains 6 requests.

Each run:

* Has a unique share ID for sharing
* Records all input parameters (canonical input)
* Tracks the status, cost, and duration of each request
* Generates a preview image for social sharing

### Estimated cost

Before running, Sandbox displays an estimated cost based on:

* The models you've selected
* The quantity (number of times to run each model)

The estimate appears in the footer of the prompt bar with color-coded badges:

* **Green**: Under \$1
* **Yellow**: $1 - $2.50
* **Red**: Over \$2.50

The actual cost may vary based on output complexity (e.g., longer videos cost more).

## Using Sandbox

### Running a generation

<Steps>
  <Step>
    **Select the media type**: Choose Image, Video, or Audio from the top tabs
  </Step>

  <Step>
    **Choose an operation**: Select the specific operation (e.g., Text to Image,
    Image to Video)
  </Step>

  <Step>
    **Fill in the inputs**: Enter your prompt and any required media inputs
  </Step>

  <Step>
    **Select models**: Choose which models to run (or use a model set)
  </Step>

  <Step>**Set quantity**: Optionally run each model multiple times</Step>
  <Step>**Click Run**: Submit your generation</Step>
</Steps>

### Enhancing prompts

Many operations support **prompt enhancement** — an AI-powered feature that expands your basic prompt into a more detailed, effective version:

1. Enter your initial prompt
2. Click the sparkle/enhance icon next to the prompt field
3. Sandbox uses an LLM (or VLM for image-based operations) to expand your prompt
4. The enhanced prompt replaces your original

Enhancement is especially useful for:

* **Text-to-image**: Adds artistic style, lighting, and composition details
* **Image-to-video**: Describes motion and camera movements
* **Video generation**: Specifies pacing and transitions

### Random examples

Not sure what to try? Click the **dice icon** next to the operation selector to fill the form with a curated example. Each click cycles through different examples for that operation.

### Working with results

After a run completes, each generation appears in the canvas area.

**Viewing results**

* Click any result to open the full-screen media viewer
* Navigate between results using arrow keys or on-screen controls
* View detailed metadata including model, cost, and generation time

**Badges on results**

* **Fastest**: Quickest generation in the run
* **Cheapest**: Lowest cost in the run
* **Free**: Generated using free credits

**Using results as input**

* Hover over any image/video result
* Click the "Use as input" button to apply it to a compatible operation
* Sandbox automatically switches to an appropriate operation if needed

### Copying and rerunning

The **Input Card** (visible when "Show Metadata" is enabled) provides quick actions:

| Action       | Description                                               |
| ------------ | --------------------------------------------------------- |
| **Copy**     | Populate the input form with this run's settings          |
| **Rerun**    | Immediately execute the same run again                    |
| **Archive**  | Remove from Sandbox (still accessible in request history) |
| **Share**    | Generate a shareable link                                 |
| **Bookmark** | Bookmark the run for easy access later                    |

You can also click individual fields in the input card to copy just that value to your current form.

## Searching generations

Sandbox provides powerful search capabilities to find previous generations.

### Text search

Type in the search bar to find generations by semantic similarity to your query. This searches the prompts and other text fields.

### Image search

1. Click the image icon in the search bar
2. Upload an image
3. Find visually similar generations

### Color search

1. Click the palette icon in the search bar
2. Select a color
3. Find generations with that dominant color

### Filtering

Combine search with filters:

* **Operation Type**: Show only specific operations (e.g., just video generations)
* **Team Member**: In team workspaces, filter by who created the generation
* **Bookmarks**: Show only bookmarked favorites
* **Similarity Threshold**: Adjust how closely results must match your search

## Free credits

Sandbox occasionally offers free credits for specific models:

* Look for the **gift icon** with an orange dot in the interface
* Click to see all models with remaining free credits
* Free credits come from:
  * Global campaigns (available to all users)
  * User-specific grants

When you have free credits, the cost badge shows "Free" and generations are marked with a gift icon.

<Note>
  Free credits and free request coupons are only usable in Sandbox and the
  Playground — they cannot be used through the API or Workflows.
</Note>

## Sharing runs

Share your generations with anyone:

1. Complete a run (all generations must finish)
2. Click the share icon on the input card
3. Copy the generated link

Shared runs include:

* A preview image/video for social media cards
* All generations from the run
* Input parameters used

Recipients can view the shared run without a fal account. If they want to remix it, they can copy the inputs to their own Sandbox.

## Keyboard shortcuts

| Shortcut | Action                             |
| -------- | ---------------------------------- |
| `←` `→`  | Navigate between results in viewer |
| `Escape` | Close viewer                       |

## Using your own apps and workflows

You can add your own [serverless apps](/serverless) and [workflows](/model-apis/model-endpoints/workflows) to Sandbox, allowing you to compare your custom models alongside platform models.

### Requirements

For your app or workflow to work in Sandbox, it must:

1. **Accept the canonical input fields** (or supported variations) for the operation type
2. **Return the expected output fields** for that operation's media type

Sandbox automatically validates your app's schema when you add it and will show warnings if there are compatibility issues.

### Adding your apps

<Steps>
  <Step>
    **Click the apps icon** in the operation selector bar (next to the operation dropdown)
  </Step>

  <Step>
    **Search for your app or workflow** using the search field
  </Step>

  <Step>
    **Select apps to add** — Sandbox validates each app's schema against the operation requirements
  </Step>

  <Step>
    **Save your selection** — Added apps appear in the model picker alongside platform models
  </Step>
</Steps>

Apps are added per-operation. If your app works for multiple operations (e.g., both text-to-image and image editing), you'll need to add it to each operation separately.

<Note>
  When running your own apps in Sandbox, cost and duration metrics may not be
  available since these are tracked differently for private endpoints.
</Note>

### Canonical input schemas

Each operation type has a **canonical input schema** — the standardized fields that Sandbox uses. Your app can use either the canonical field names or any of the supported variations.

#### Image operations

| Operation             | Canonical Fields                       |
| --------------------- | -------------------------------------- |
| **Text to Image**     | `prompt`, `aspect_ratio`               |
| **Edit Image**        | `prompt`, `image_url`, `aspect_ratio`  |
| **Edit Multi-Images** | `prompt`, `image_urls`, `aspect_ratio` |
| **Upscale**           | `image_url`, `scale`                   |
| **Remove Background** | `image_url`                            |

#### Video operations

| Operation             | Canonical Fields                                                 |
| --------------------- | ---------------------------------------------------------------- |
| **Text to Video**     | `prompt`, `duration`, `aspect_ratio`                             |
| **Image to Video**    | `prompt`, `image_url`, `duration`, `aspect_ratio`                |
| **Start + End Frame** | `prompt`, `start_frame`, `end_frame`, `duration`, `aspect_ratio` |
| **Upscale**           | `video_url`, `scale`                                             |
| **Remove Background** | `video_url`                                                      |
| **Video to Audio**    | `video_url`, `prompt`                                            |

#### Audio operations

| Operation                 | Canonical Fields |
| ------------------------- | ---------------- |
| **Text to Music**         | `prompt`         |
| **Text to Speech**        | `prompt`         |
| **Text to Sound Effects** | `prompt`         |

### Supported field variations

If your app uses different field names, Sandbox can automatically remap them. The table below shows which field names are recognized for each canonical field:

| Canonical Field | Accepted Variations                                                                                   |
| --------------- | ----------------------------------------------------------------------------------------------------- |
| `prompt`        | `text`, `description`, `edit_prompt`, `instruction`, `lyrics_prompt`, `script`, `text_prompt`         |
| `image_url`     | `image`, `source_image`, `input_image`, `control_image_url`, `reference_image_url`, `start_image_url` |
| `image_urls`    | `images`, `source_images`, `input_images`, `control_images`, `reference_image_urls`                   |
| `video_url`     | `video`, `source_video`, `input_video`                                                                |
| `start_frame`   | `start_image_url`, `start_image`, `first_frame`, `first_frame_url`, `first_image_url`                 |
| `end_frame`     | `end_image_url`, `end_image`, `last_frame`, `last_frame_url`, `tail_image_url`, `last_image_url`      |
| `scale`         | `upscaling_factor`, `upscale_factor`                                                                  |
| `duration`      | `video_length`                                                                                        |

### Field transforms

Some fields undergo value transformation in addition to name remapping:

| Canonical Field | Transform Behavior                                                                                                                |
| --------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `aspect_ratio`  | Values like `16:9`, `4:3`, `1:1` may be converted to `landscape_16_9`, `landscape_4_3`, `square_hd` for models using `image_size` |
| `duration`      | Automatically matched to the closest available option if model has enumerated durations (e.g., `5s`, `10s`)                       |
| `scale`         | May be converted to discrete values like `"2"` or `"4"` for models with `desired_increase` field                                  |

### Required output fields

Your app must return the correct output structure for Sandbox to display results:

| Output Type | Required Fields                                    |
| ----------- | -------------------------------------------------- |
| **Image**   | `images` (array), `image` (object), or `image_url` |
| **Video**   | `video` (object) or `video_url`                    |
| **Audio**   | `audio` (object) or `audio_url`                    |

For image outputs, the standard structure is:

```json theme={null}
{
  "images": [
    {
      "url": "https://...",
      "width": 1024,
      "height": 1024,
      "content_type": "image/png"
    }
  ]
}
```

For video outputs:

```json theme={null}
{
  "video": {
    "url": "https://...",
    "content_type": "video/mp4"
  }
}
```

For audio outputs:

```json theme={null}
{
  "audio_url": "https://..."
}
```

### Validation indicators

When adding apps, Sandbox shows validation status:

| Icon     | Meaning                                                        |
| -------- | -------------------------------------------------------------- |
| ✓ Green  | Fully compatible — schema matches operation requirements       |
| ⚠ Yellow | Has warnings — may work but some fields require transformation |
| ✕ Red    | Incompatible — missing required fields or wrong output type    |
| ℹ Blue   | Has info — some fields will be automatically transformed       |

<Warning>
  Apps with validation errors (red icon) cannot be added. You'll need to update
  your app's schema to match the operation requirements.
</Warning>

## Tips for best results

1. **Start with model sets**: Typically, the default models automatically selected are the best performing models for the operation.
2. **Enhance your prompts**: Let AI expand basic ideas into detailed prompts with the "enhance prompt" button.
3. **Compare with quantity 1x**: Save costs by running single generations when comparing models
4. **Use image search**: Find similar past generations to avoid recreating work
5. **Bookmark favorites**: Mark your best results for easy access later
6. **Check free credits**: Look for the gift icon before running expensive models
