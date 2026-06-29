> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Document Your Model

> Attach a human-readable About section to your fal App so callers can understand your model directly from the Playground and the OpenAPI schema.

When you deploy a [Serverless App](/documentation/serverless/index), the [Playground](/documentation/model-apis/playground) already renders your input and output fields from your [Pydantic schemas](/documentation/development/handle-inputs-and-outputs). What it can't infer is the *context* a caller needs: what the model does, the assumptions it makes about inputs, the color spaces or formats it expects, and the guarantees it makes about outputs.

Instead of handing integrating teams a separate doc or Slack message, you can attach that context directly to your endpoint as an **About section**. It is written as a docstring, rendered at the top of the Playground's API tab, and exposed in the model's OpenAPI schema so other teams can pull it programmatically as the single source of truth for your model.

## Add an About section

The About content comes from the **docstring of your root endpoint function** (the method decorated with `@fal.endpoint("/")`). Write it in Markdown — headings, lists, links, tables, code blocks, and images are all supported.

```python theme={null}
import fal
from pydantic import BaseModel

class Input(BaseModel):
    image_url: str

class Output(BaseModel):
    image_url: str

class UpscaleApp(fal.App):
    machine_type = "GPU-H100"

    @fal.endpoint("/")
    def upscale(self, input: Input) -> Output:
        """
        # Super-Resolution Upscaler

        Upscales an input image by 4x while preserving fine detail.

        ## Input assumptions
        - `image_url` must point to an **sRGB** image (PNG or JPEG).
        - Maximum input resolution is 2048 x 2048.

        ## Output guarantees
        - Returns a PNG in the same color space as the input.
        - Aspect ratio is always preserved.

        ## Notes
        Linear and Display-P3 color spaces are **not** supported yet.
        """
        ...
```

<Tip>
  Treat the About section as the README for your model. Documenting input invariants and output guarantees here means callers can adapt to changes (for example, widening accepted color spaces) by re-reading the schema, instead of pinging your team.
</Tip>

## Where it appears

The rendered Markdown appears at the **top of the API tab** on your model's Playground page:

```text theme={null}
https://fal.ai/models/<your-username>/<your-app>/api
```

It is shown above the request/response reference, so anyone opening your model in the Playground sees the description before the technical schema. The content is rendered as standard Markdown.

## Retrieve it programmatically

For callers wrapping your endpoint in their own UI (not the fal Playground), the About content is available in the model's queue OpenAPI schema under `info["x-fal-metadata"].about`.

Fetch the schema for any endpoint:

```text theme={null}
https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=<endpoint_id>
```

<CodeGroup>
  ```bash curl theme={null}
  curl "https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=your-username/your-app"
  ```

  ```python Python theme={null}
  import requests

  schema = requests.get(
      "https://fal.ai/api/openapi/queue/openapi.json",
      params={"endpoint_id": "your-username/your-app"},
  ).json()

  about = schema["info"]["x-fal-metadata"].get("about")
  print(about)  # the rendered Markdown of your About section
  ```
</CodeGroup>

The relevant part of the response looks like this:

```json theme={null}
{
  "openapi": "3.0.4",
  "info": {
    "title": "Queue OpenAPI for your-username/your-app",
    "x-fal-metadata": {
      "endpointId": "your-username/your-app",
      "category": "image-to-image",
      "thumbnailUrl": "https://fal.media/files/...",
      "playgroundUrl": "https://fal.ai/models/your-username/your-app",
      "documentationUrl": "https://fal.ai/models/your-username/your-app/api",
      "about": "# Super-Resolution Upscaler\n\nUpscales an input image..."
    }
  }
}
```

The `x-fal-metadata` object always carries identifying fields; `about` is present only when your root endpoint has a docstring.

| Field              | Description                                                                                  |
| ------------------ | -------------------------------------------------------------------------------------------- |
| `endpointId`       | The endpoint identifier (`owner/app`).                                                       |
| `category`         | Model category, when set on the model card.                                                  |
| `thumbnailUrl`     | Thumbnail from the model card metadata (see below).                                          |
| `playgroundUrl`    | Link to the Playground page.                                                                 |
| `documentationUrl` | Link to the API tab.                                                                         |
| `about`            | The rendered Markdown of your root endpoint's docstring. Omitted when there is no docstring. |

## Thumbnails and example media

A common question is whether the About section also carries thumbnails and example galleries like marketplace model pages do. It does not — the About section is purely the Markdown you write in the docstring. Specifically:

* **Thumbnail** — `x-fal-metadata.thumbnailUrl` reflects the **model card thumbnail** (set on the model's metadata), not anything defined in the docstring. For a freshly deployed Serverless app it may be empty until a thumbnail is set. To show images *inside* the About content itself, embed them with standard Markdown image syntax in your docstring (`![alt](https://...)`).
* **Example galleries** — the sample input/output media shown on marketplace model pages are **not** included in the schema, and root-level request `examples` are stripped from the generated schema. The schema carries the *interface*, not example media.
* **Per-field metadata is preserved** — field-level `description`, `title`, `minimum`/`maximum`, defaults, and enum/`Literal` choices all come through the schema and drive tooltips, sliders, and dropdowns in any UI. See [Handle Inputs and Outputs](/documentation/development/handle-inputs-and-outputs) for how to define these, and [presets](/documentation/development/handle-inputs-and-outputs#presets-input) for combobox-style options.

<Note>
  If you need richer per-parameter documentation (min/max ranges, dropdown choices, hints), define it on your Pydantic fields rather than in the About section. The About section is best for model-level context — what the model does and the assumptions it makes — while field metadata documents individual parameters.
</Note>
