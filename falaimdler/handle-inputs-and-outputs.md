> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Handle Inputs and Outputs

> Define input and output schemas for your fal App endpoints that render correctly in the Playground.

Every [fal App](/documentation/getting-started/apps-and-execution) endpoint defines its interface through Python type annotations. The types you choose for your function parameters and return values determine what the [Playground](/documentation/model-apis/playground) renders: text inputs, sliders, file uploaders, image galleries, video players, and more. Getting these right means your model is immediately testable from the browser without building a custom UI.

fal endpoints are fully compatible with [Pydantic](https://docs.pydantic.dev/) models. You can use standard Pydantic features like field validation, default values, and nested models. On top of that, fal provides `FalBaseModel` for field ordering and hidden fields, specialized field helpers (`ImageField`, `VideoField`, `AudioField`) for Playground rendering, and toolkit types (`Image`, `Video`, `Audio`, `File`) for returning media with metadata. For the runtime side of file handling (downloading user inputs and uploading generated outputs to CDN), see [Working with Files](/documentation/development/working-with-files).

## FalBaseModel

For the best experience defining inputs and outputs, use `FalBaseModel` from the fal SDK. It extends Pydantic's `BaseModel` with features specifically designed for fal applications:

* **Field ordering** - Control the order fields appear in the playground and API schema
* **Hidden fields** - Mark parameters as API-only, hiding them from the playground and API schema.

```python theme={null}
from fal.toolkit import FalBaseModel, Field, Hidden

class TextToImageInput(FalBaseModel):
    FIELD_ORDERS = ["prompt", "negative_prompt", "image_size"]

    prompt: str = Field(description="Text description of the image")
    negative_prompt: str = Field(default="", description="What to avoid")
    image_size: str = Field(default="1024x1024", description="Output dimensions")

    # Hidden from playground UI but accessible via API
    debug_mode: bool = Hidden(Field(default=False))
    internal_seed: int = Hidden(Field(default=-1))
```

### Field ordering

Use the `FIELD_ORDERS` class variable to control the order fields appear in the API schema and playground. Fields listed in `FIELD_ORDERS` appear first, in the specified order, followed by any remaining fields.

This is particularly useful when you have a base model with common fields that multiple models inherit from. By default, Pydantic places child class fields before parent class fields in the schema. `FIELD_ORDERS` lets you ensure base model fields (like `prompt`) appear first for a consistent user experience.

```python theme={null}
from fal.toolkit import FalBaseModel, Field, ImageField

# Base model with common fields
class BaseTextInput(FalBaseModel):
    FIELD_ORDERS = ["prompt", "negative_prompt"]

    prompt: str = Field(description="Text prompt")
    negative_prompt: str = Field(default="", description="What to avoid")

# Extended model for image-to-image
class ImageToImageInput(BaseTextInput):
    # Override FIELD_ORDERS to control the full order
    FIELD_ORDERS = ["prompt", "negative_prompt", "image_url", "strength"]

    image_url: str = ImageField(description="Input image")
    strength: float = Field(default=0.8, description="How much to transform")

# Without FIELD_ORDERS, schema would show: image_url, strength, prompt, negative_prompt
# With FIELD_ORDERS, schema shows: prompt, negative_prompt, image_url, strength
```

### Hidden fields

Use `Hidden()` to wrap any field that should be available via API but hidden from the playground UI. This is useful for:

* Testing parameters you want to expose to select API integrations
* Internal debugging flags
* Advanced options that would clutter the UI

<Warning>
  Hidden fields must have a default value or `default_factory` since they cannot be required inputs in the UI.
</Warning>

```python theme={null}
from fal.toolkit import FalBaseModel, Field, Hidden

class MyInput(FalBaseModel):
    prompt: str = Field(description="User prompt")

    # These won't appear in the playground
    enable_profiling: bool = Hidden(Field(default=False))
    custom_config: dict = Hidden(Field(default_factory=dict))
```

### Media field helpers

For better playground rendering, use the specialized field helpers instead of plain `Field()`:

| Helper            | UI Rendering         |
| ----------------- | -------------------- |
| `FileField(...)`  | Generic file upload  |
| `ImageField(...)` | Image upload/preview |
| `AudioField(...)` | Audio upload/player  |
| `VideoField(...)` | Video upload/player  |

```python theme={null}
from fal.toolkit import FalBaseModel, ImageField, AudioField

class MyInput(FalBaseModel):
    # Renders as image upload in playground
    input_image: str = ImageField(description="Source image")

    # Renders as audio upload in playground
    voice_sample: str = AudioField(description="Voice sample for cloning")
```

These helpers work with both Pydantic v1 and v2. See the [Standard Inputs and Outputs](#standard-inputs-and-outputs) section below for more details on each media type, including naming conventions and output handling.

## Output Format for Playground Rendering

The Playground detects media outputs by checking for objects that have both a `url` and `content_type` field. If you use the toolkit types (`Image`, `Video`, `Audio`, `File`), these fields are set automatically. But if you are returning raw dicts from a [custom Docker container](/documentation/development/use-custom-container-image) or a [Direct Server Mode](/documentation/development/migrate-external-docker-server#option-1-direct-server-mode) endpoint, you must include both fields for the Playground to render the output as media instead of raw JSON.

```json theme={null}
{
  "image": {
    "url": "https://v3.fal.media/files/...",
    "content_type": "image/png"
  }
}
```

The Playground recognizes these field names for automatic rendering:

| Output field                           | Renders as              |
| -------------------------------------- | ----------------------- |
| `image` or `images`                    | Image preview / gallery |
| `video`                                | Video player            |
| `audio`, `audio_file`, or `audio_url`  | Audio player            |
| `model_glb`, `model_obj`, `model_mesh` | 3D model viewer         |

Each object in the response must have at minimum `url` and `content_type`. Without `content_type`, the Playground falls back to displaying the result as raw JSON. Additional fields like `file_name`, `file_size`, `width`, and `height` are optional but improve the display.

For [streaming endpoints](/documentation/development/streaming) that send results via SSE, the same format applies to each event. Streaming endpoints typically use `data:` URIs (base64-encoded inline content) instead of CDN URLs, since uploading each intermediate frame to CDN would add latency. The Playground renders data URIs the same way as CDN URLs.

```json theme={null}
{"image": {"url": "data:image/jpeg;base64,...", "content_type": "image/jpeg"}}
```

## Standard Inputs and Outputs

### File Input

Name your field with a `file_url` suffix and it will be rendered as a file in the playground, allowing users to upload or download the file.

```python theme={null}
from pydantic import BaseModel

class MyInput(BaseModel):
    file_url: str

class MyOutput(BaseModel):
    ...

class MyApp(fal.App):
    @fal.endpoint("/")
    def predict(self, input: MyInput) -> MyOutput:
        input_path = download_file(input.file_url)
        ...
        return MyOutput(...)
```

Alternatively if that naming convention is not suitable, you can use the `FileField` helper:

```python theme={null}
from fal.toolkit import FalBaseModel, FileField

class MyInput(FalBaseModel):
    document: str = FileField(description="Upload a document")
```

<Accordion title="Manual approach with json_schema_extra">
  For advanced use cases, you can manually specify the `ui` metadata. The syntax differs between Pydantic versions:

  <CodeGroup>
    ```python Pydantic v2 theme={null}
    from pydantic import BaseModel, Field

    class MyInput(BaseModel):
        document: str = Field(..., json_schema_extra={"ui": {"field": "file"}})
    ```

    ```python Pydantic v1 theme={null}
    from pydantic import BaseModel, Field

    class MyInput(BaseModel):
        document: str = Field(..., ui={"field": "file"})
    ```
  </CodeGroup>
</Accordion>

### File Output

Use the `File` type from `fal.toolkit` in your output schema. The Playground renders it as a download link.

```python theme={null}
from fal.toolkit import File
from pydantic import BaseModel

class MyOutput(BaseModel):
    file: File
```

The response includes file metadata:

```json theme={null}
{
  "file": {
    "url": "https://v3.fal.media/files/...",
    "content_type": "application/octet-stream",
    "file_name": "file.bin",
    "file_size": 1024
  }
}
```

See [Working with Files](/documentation/development/working-with-files#creating-files) for how to create `File` objects from local paths or bytes.

### Image Input

Name your field with a `image_url` suffix and it will be rendered as an image in the playground, allowing users to upload or download the image.

```python theme={null}
from pydantic import BaseModel
from fal.toolkit import download_file

class MyInput(BaseModel):
    image_url: str

class MyOutput(BaseModel):
    ...

class MyApp(fal.App):
    @fal.endpoint("/")
    def predict(self, input: MyInput) -> MyOutput:
        input_path = download_file(input.image_url)
        ...
        return MyOutput(...)
```

Alternatively if that naming convention is not suitable, you can use the `ImageField` helper:

```python theme={null}
from fal.toolkit import FalBaseModel, ImageField

class MyInput(FalBaseModel):
    photo: str = ImageField(description="Upload a photo")
```

<Accordion title="Manual approach with json_schema_extra">
  For advanced use cases, you can manually specify the `ui` metadata. The syntax differs between Pydantic versions:

  <CodeGroup>
    ```python Pydantic v2 theme={null}
    from pydantic import BaseModel, Field

    class MyInput(BaseModel):
        photo: str = Field(..., json_schema_extra={"ui": {"field": "image"}})
    ```

    ```python Pydantic v1 theme={null}
    from pydantic import BaseModel, Field

    class MyInput(BaseModel):
        photo: str = Field(..., ui={"field": "image"})
    ```
  </CodeGroup>
</Accordion>

### Image Output

Use the `Image` type in your output schema. The Playground renders it as an image preview.

```python theme={null}
from fal.toolkit import Image
from pydantic import BaseModel

class MyOutput(BaseModel):
    image: Image
```

The response includes image metadata with dimensions:

```json theme={null}
{
  "image": {
    "url": "https://v3.fal.media/files/...",
    "content_type": "image/png",
    "file_name": "image.png",
    "file_size": 1024,
    "width": 1024,
    "height": 1024
  }
}
```

See [Working with Files](/documentation/development/working-with-files#creating-files) for how to create `Image` objects from PIL images, bytes, or local files.

### Multiple Image Output

Return a list of `Image` objects to output multiple images. The Playground renders them in a gallery grid.

```python theme={null}
from typing import List
from fal.toolkit import Image
from pydantic import BaseModel

class MyOutput(BaseModel):
    images: List[Image]
    has_nsfw_concepts: List[bool]

class MyApp(fal.App):
    @fal.endpoint("/")
    def predict(self, prompt: str, num_images: int = 1) -> MyOutput:
        results = self.pipe(prompt, num_images=num_images).images
        return MyOutput(
            images=[Image.from_pil(img) for img in results],
            has_nsfw_concepts=[False] * len(results),
        )
```

Response:

```json theme={null}
{
  "images": [
    {"url": "https://v3.fal.media/files/.../image_0.png", "width": 1024, "height": 1024},
    {"url": "https://v3.fal.media/files/.../image_1.png", "width": 1024, "height": 1024},
    {"url": "https://v3.fal.media/files/.../image_2.png", "width": 1024, "height": 1024}
  ],
  "has_nsfw_concepts": [false, false, false]
}
```

**Playground gallery layout:**

Images are displayed in **array order** (index 0 first), laid out in a 2-column grid:

* **1 image**: Full width
* **2 images**: Side by side (index 0 left, index 1 right)
* **3 images**: First image full width on top, then index 1 left and index 2 right below
* **4 images**: 2x2 grid (index 0 top-left, index 1 top-right, index 2 bottom-left, index 3 bottom-right)

For odd numbers of images, the first image always spans the full width. The `has_nsfw_concepts` array maps by index: `has_nsfw_concepts[i]` corresponds to `images[i]`.

### Image Dataset Input

Use `image_urls` suffix to render a dataset of images in the playground.

```python theme={null}
from typing import List
from pydantic import BaseModel

class MyInput(BaseModel):
    image_urls: List[str]
```

### Audio Input

Name your field with a `audio_url` suffix and it will be rendered as an audio in the playground, allowing users to upload or download the audio.

```python theme={null}
from typing import List
from pydantic import BaseModel

class MyInput(BaseModel):
    audio_url: str

class MyOutput(BaseModel):
    ...

class MyApp(fal.App):
    @fal.endpoint("/")
    def predict(self, input: MyInput) -> MyOutput:
        input_path = download_file(input.audio_url)
        ...
        return MyOutput(...)
```

Alternatively if that naming convention is not suitable, you can use the `AudioField` helper:

```python theme={null}
from fal.toolkit import FalBaseModel, AudioField

class MyInput(FalBaseModel):
    voice_sample: str = AudioField(description="Upload a voice sample")
```

<Accordion title="Manual approach with json_schema_extra">
  For advanced use cases, you can manually specify the `ui` metadata. The syntax differs between Pydantic versions:

  <CodeGroup>
    ```python Pydantic v2 theme={null}
    from pydantic import BaseModel, Field

    class MyInput(BaseModel):
        voice_sample: str = Field(..., json_schema_extra={"ui": {"field": "audio"}})
    ```

    ```python Pydantic v1 theme={null}
    from pydantic import BaseModel, Field

    class MyInput(BaseModel):
        voice_sample: str = Field(..., ui={"field": "audio"})
    ```
  </CodeGroup>
</Accordion>

### Audio Output

Use the `Audio` type in your output schema. The Playground renders it as an audio player with waveform visualization.

```python theme={null}
from fal.toolkit import Audio
from pydantic import BaseModel

class MyOutput(BaseModel):
    audio: Audio
```

The response includes audio metadata:

```json theme={null}
{
  "audio": {
    "url": "https://v3.fal.media/files/...",
    "content_type": "audio/mpeg",
    "file_name": "audio.mp3",
    "file_size": 1024
  }
}
```

See [Working with Files](/documentation/development/working-with-files#creating-files) for how to create `Audio` objects from local files or bytes.

### Multiple Audio Output

Return a list of `Audio` objects. The Playground renders each as a stacked waveform player.

```python theme={null}
from typing import List
from fal.toolkit import Audio
from pydantic import BaseModel

class MyOutput(BaseModel):
    audios: List[Audio]
```

The Playground accepts `audios` (array), `audio` (single or array), or `audio_file`. Audio outputs are displayed vertically with waveform visualization and playback controls, in array order.

### Audio Dataset Input

Use `audio_urls` suffix to render a dataset of audios in the playground.

```python theme={null}
from typing import List
from pydantic import BaseModel

class MyInput(BaseModel):
    audio_urls: List[str]
```

### Video Input

Name your field with a `video_url` suffix and it will be rendered as a video in the playground, allowing users to upload or download the video.

```python theme={null}
from typing import List
from pydantic import BaseModel

class MyInput(BaseModel):
    video_url: str

class MyOutput(BaseModel):
    ...

class MyApp(fal.App):
    @fal.endpoint("/")
    def predict(self, input: MyInput) -> MyOutput:
        input_path = download_file(input.video_url)
        ...
        return MyOutput(...)
```

Alternatively if that naming convention is not suitable, you can use the `VideoField` helper:

```python theme={null}
from fal.toolkit import FalBaseModel, VideoField

class MyInput(FalBaseModel):
    clip: str = VideoField(description="Upload a video clip")
```

<Accordion title="Manual approach with json_schema_extra">
  For advanced use cases, you can manually specify the `ui` metadata. The syntax differs between Pydantic versions:

  <CodeGroup>
    ```python Pydantic v2 theme={null}
    from pydantic import BaseModel, Field

    class MyInput(BaseModel):
        clip: str = Field(..., json_schema_extra={"ui": {"field": "video"}})
    ```

    ```python Pydantic v1 theme={null}
    from pydantic import BaseModel, Field

    class MyInput(BaseModel):
        clip: str = Field(..., ui={"field": "video"})
    ```
  </CodeGroup>
</Accordion>

### Video Output

Use the `Video` type in your output schema. The Playground renders it as a video player.

```python theme={null}
from fal.toolkit import Video
from pydantic import BaseModel

class MyOutput(BaseModel):
    video: Video
```

The response includes video metadata:

```json theme={null}
{
  "video": {
    "url": "https://v3.fal.media/files/...",
    "content_type": "video/mp4",
    "file_name": "video.mp4",
    "file_size": 1024
  }
}
```

See [Working with Files](/documentation/development/working-with-files#creating-files) for how to create `Video` objects from local files or bytes.

### Multiple Video Output

Return a list of `Video` objects. The Playground renders each video as a stacked player (not a grid).

```python theme={null}
from typing import List
from fal.toolkit import Video
from pydantic import BaseModel

class MyOutput(BaseModel):
    videos: List[Video]
```

The Playground accepts `videos` (array of objects with `url`) or `video` (single object or array). Videos are displayed vertically, one player per video, in array order.

### Video Dataset Input

Use `video_urls` suffix to render a dataset of videos in the playground.

```python theme={null}
from typing import List
from pydantic import BaseModel

class MyInput(BaseModel):
    video_urls: List[str]
```

### Mask Image Input

Name your field with a `mask_image_url` or `mask_url` suffix (or prefix) and the Playground renders an image upload with a built-in mask painting tool. Users can upload a mask image directly or click "Create..." to draw a mask over a reference image. The reference image is automatically pulled from an `image_url` or `inpaint_image_url` field in the same input schema.

```python theme={null}
from pydantic import BaseModel

class InpaintInput(BaseModel):
    image_url: str
    mask_image_url: str
    prompt: str
```

The mask painter produces a black-and-white image where white regions indicate areas to inpaint. Both `mask_image_url` and `mask_url` prefixes/suffixes are supported (e.g., `mask_url_face`, `custom_mask_image_url`).

### Color Input

If your input uses a Pydantic model named `RGBColor` with `r`, `g`, `b` integer fields, the Playground renders a color picker with a visual swatch and individual R/G/B inputs (0-255). A list of `RGBColor` values renders a color palette editor where users can add and remove colors.

```python theme={null}
from pydantic import BaseModel, Field
from typing import List

class RGBColor(BaseModel):
    r: int = Field(ge=0, le=255)
    g: int = Field(ge=0, le=255)
    b: int = Field(ge=0, le=255)

class MyInput(BaseModel):
    background_color: RGBColor = RGBColor(r=255, g=255, b=255)
    color_palette: List[RGBColor] = []
```

<Note>
  The Playground detects this by the type name `RGBColor`. The model must be named exactly `RGBColor` for the color picker to render.
</Note>

### Image Size Input

Use `ImageSizeInput` from `fal.toolkit` to render an image size selector with preset buttons (square, landscape, portrait) and custom width/height inputs. This is the same type used by most image generation models on fal.

```python theme={null}
from fal.toolkit import ImageSizeInput, get_image_size

class MyInput(BaseModel):
    image_size: ImageSizeInput = "square_hd"

class MyApp(fal.App):
    @fal.endpoint("/")
    def generate(self, input: MyInput) -> dict:
        size = get_image_size(input.image_size)
        width, height = size.width, size.height
        ...
```

The available presets are `"square_hd"` (1024x1024), `"square"` (512x512), `"portrait_4_3"` (768x1024), `"portrait_16_9"` (576x1024), `"landscape_4_3"` (1024x768), and `"landscape_16_9"` (1024x576). Users can also enter custom dimensions directly.

### Camera Image Input

Name your field with a `face_image_url` suffix and the Playground renders a camera capture widget that lets users take a photo with their webcam, in addition to the standard file upload options.

```python theme={null}
from pydantic import BaseModel

class FaceSwapInput(BaseModel):
    face_image_url: str
    target_image_url: str
```

### Camera Control Input

Use `ui.field = "camera_control"` or name your field ending with `advanced_camera_control` to render a visual camera motion selector. Users pick a movement type (roll, pan, tilt, zoom, horizontal, vertical) and a value, which is useful for video generation models that accept camera motion parameters.

```python theme={null}
from fal.toolkit import FalBaseModel, Field

class VideoInput(FalBaseModel):
    prompt: str
    camera_control: dict = Field(
        default={"movement_type": "default", "movement_value": 0},
        json_schema_extra={"ui": {"field": "camera_control"}}
    )
```

### 3D Model Input

Name your field with a `model_url` suffix and the Playground renders a 3D model upload widget.

```python theme={null}
from pydantic import BaseModel

class TextureInput(BaseModel):
    model_url: str
    prompt: str
```

### Archive and Dataset Input

Name your field with a `data_url` or `archive_url` suffix to render a dataset upload widget. This is useful for training endpoints or batch processing that accept ZIP archives or collections of files.

```python theme={null}
from pydantic import BaseModel

class TrainingInput(BaseModel):
    training_data_url: str
    trigger_word: str
```

### Presets Input

Fields ending in `model_name` automatically render as a preset selector. The Playground shows a dropdown populated from the field's `examples` metadata, with an option to enter a custom value. This is useful for model selection fields where you want to suggest common options while allowing arbitrary input.

```python theme={null}
from pydantic import BaseModel, Field

class MyInput(BaseModel):
    model_name: str = Field(
        default="stabilityai/stable-diffusion-xl-base-1.0",
        examples=[
            "stabilityai/stable-diffusion-xl-base-1.0",
            "runwayml/stable-diffusion-v1-5",
            "black-forest-labs/FLUX.1-dev",
        ]
    )
```

***

### EXR / HDR Output

The Playground can render [OpenEXR](https://openexr.com/) files with HDR tone mapping. When your endpoint returns a file with a URL ending in `.exr`, the Playground automatically displays it using a WebGL-based HDR viewer with ACES Filmic tone mapping.

Use `File.from_path()` to return EXR files — the `Image` toolkit class does not support EXR format.

```python theme={null}
import fal
import numpy as np
from pydantic import BaseModel
from fal.toolkit import File

class DepthInput(BaseModel):
    image_url: str

class DepthOutput(BaseModel):
    depth_map: File

class DepthApp(fal.App):
    machine_type = "GPU-A100"

    def setup(self):
        import cv2
        self.cv2 = cv2

    @fal.endpoint("/")
    def predict(self, input: DepthInput) -> DepthOutput:
        depth = self.run_depth_estimation(input.image_url)

        # Save as EXR — preserves full float32 precision
        output_path = "/tmp/depth.exr"
        self.cv2.imwrite(output_path, depth.astype(np.float32))

        return DepthOutput(
            depth_map=File.from_path(output_path, content_type="image/x-exr"),
        )
```

<Note>
  EXR rendering in the Playground is **output only**. Uploading EXR files as input is not currently supported.
</Note>

***

### 3D Model Output

The Playground can render 3D model files with an interactive viewer (orbit controls, lighting, zoom). When your endpoint returns a file with one of the supported extensions, the Playground automatically displays it as a 3D scene.

Supported formats:

| Format        | Extension | Renderer                         |
| ------------- | --------- | -------------------------------- |
| glTF Binary   | `.glb`    | Google Model Viewer (AR-capable) |
| Wavefront OBJ | `.obj`    | Three.js with orbit controls     |
| FBX           | `.fbx`    | Three.js with animation support  |
| Mesh          | `.mesh`   | Google Model Viewer              |

Use `File.from_path()` to return 3D files with the correct extension:

```python theme={null}
import fal
from pydantic import BaseModel
from fal.toolkit import File

class MeshInput(BaseModel):
    image_url: str

class MeshOutput(BaseModel):
    mesh: File

class MeshApp(fal.App):
    machine_type = "GPU-A100"

    def setup(self):
        self.pipeline = load_3d_pipeline()

    @fal.endpoint("/")
    def generate(self, input: MeshInput) -> MeshOutput:
        mesh = self.pipeline.generate(input.image_url)

        output_path = "/tmp/output.glb"
        mesh.export(output_path)

        return MeshOutput(
            mesh=File.from_path(output_path, content_type="model/gltf-binary"),
        )
```

The Playground detects 3D output by checking the URL file extension. GLB is the recommended format for best Playground compatibility, as it supports textures, materials, and AR preview.

<Tip>
  For examples of deploying 3D models on fal, see [Deploy 3D Progressive Rendering](/examples/video-generation/deploy-3d-progressive-rendering).
</Tip>

***

## Playground UI Mapping

Your Pydantic schema controls how the Playground renders each input field. The Playground automatically selects the right widget based on the field's type, name, and metadata.

### Widget Reference

| Python Type / Pattern                            | Playground Widget                      |
| ------------------------------------------------ | -------------------------------------- |
| `str`                                            | Text input                             |
| `str` named `prompt` or ending in `_prompt`      | Textarea (3 rows)                      |
| `bool`                                           | Toggle switch                          |
| `int` or `float` with `ge` and `le`              | Slider + number input                  |
| `int` ending in `seed`                           | Number input + randomize button        |
| `Literal["a", "b", "c"]` or `Enum`               | Dropdown select                        |
| `List[Literal[...]]` or `List[Enum]`             | Checkboxes                             |
| `str` ending in `_image_url` or `ImageField`     | Image upload (drag-drop, paste, URL)   |
| `str` ending in `_face_image_url`                | Camera capture + image upload          |
| `str` ending in `_mask_image_url` or `_mask_url` | Image upload + mask painter            |
| `str` ending in `_video_url` or `VideoField`     | Video upload with preview              |
| `str` ending in `_audio_url` or `AudioField`     | Audio upload + microphone recording    |
| `str` ending in `_file_url` or `FileField`       | Generic file upload                    |
| `str` ending in `_model_url`                     | 3D model upload                        |
| `str` ending in `_data_url` or `_archive_url`    | Dataset/archive upload                 |
| `str` ending in `model_name` with `examples`     | Preset selector + custom input         |
| `List[Image]` or ending in `_image_urls`         | Multi-image picker                     |
| `RGBColor` model (with `r`, `g`, `b` fields)     | Color picker                           |
| `List[RGBColor]`                                 | Color palette editor                   |
| `ImageSizeInput` (from `fal.toolkit`)            | Image size selector (presets + custom) |
| `ui.field = "camera_control"`                    | Camera motion selector                 |
| Nested Pydantic model                            | Recursive form (indented section)      |
| `List[str]` or `List[int]`                       | Add/remove input list                  |

### Examples

**Slider** - any `int` or `float` with both `ge` (min) and `le` (max) renders as a slider. Use `multiple_of` to control the step precision:

```python theme={null}
class MyInput(BaseModel):
    guidance_scale: float = Field(default=7.5, ge=1.0, le=20.0, multiple_of=0.5)
    num_inference_steps: int = Field(default=30, ge=1, le=100)
    strength: float = Field(default=0.8, ge=0.0, le=1.0, multiple_of=0.01)
```

**Dropdown** - `Literal` types or Python `Enum` classes render as dropdown selects:

```python theme={null}
from typing import Literal

class MyInput(BaseModel):
    scheduler: Literal["euler", "ddim", "dpm++"] = "euler"
    image_size: Literal["square_hd", "landscape_16_9", "portrait_4_3"] = "square_hd"
```

**Seed** - any `int` field with a name ending in `seed` gets a randomize button:

```python theme={null}
class MyInput(BaseModel):
    seed: int = Field(default=42, description="Random seed for reproducibility")
```

**Textarea** -- fields named `prompt` automatically render as a multi-line textarea. For other fields, use `ui.field`:

```python theme={null}
from fal.toolkit import FalBaseModel, Field

class MyInput(FalBaseModel):
    prompt: str = Field(description="This automatically renders as textarea")
    system_message: str = Field(
        default="",
        json_schema_extra={"ui": {"field": "textarea"}}
    )
```

**Checkboxes** - a list of enum values renders as a multi-select checkbox group:

```python theme={null}
from typing import List, Literal

class MyInput(BaseModel):
    styles: List[Literal["photorealistic", "anime", "oil-painting", "watercolor"]] = []
```

### UI Metadata

You can control Playground behavior with `json_schema_extra` metadata on any field:

```python theme={null}
from fal.toolkit import FalBaseModel, Field

class MyInput(FalBaseModel):
    prompt: str = Field(description="Main prompt")

    # Override the widget type
    notes: str = Field(
        default="",
        json_schema_extra={"ui": {"field": "textarea"}}
    )

    # Show helper text below the field
    lora_url: str = Field(
        default="",
        json_schema_extra={"ui": {"hint": "Paste a HuggingFace or Civitai URL"}}
    )

    # Mark as read-only in Playground (API-only parameter)
    internal_config: str = Field(
        default="",
        json_schema_extra={"ui": {"frozen": True}}
    )

    # Force field into the main form (not "Additional Settings")
    negative_prompt: str = Field(
        default="",
        json_schema_extra={"ui": {"important": True}}
    )
```

| Property       | Effect                                                                                                                    |
| -------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `ui.field`     | Override widget type (`"textarea"`, `"image"`, `"video"`, `"audio"`, `"file"`, `"seed"`, `"camera_control"`, `"presets"`) |
| `ui.hint`      | Helper text shown below the field                                                                                         |
| `ui.frozen`    | Field is read-only with an "API only" badge                                                                               |
| `ui.important` | Field appears in the main form section                                                                                    |

### Field Grouping

The Playground automatically groups fields into two sections:

* **Main form**: Required fields and fields marked with `ui.important = true`
* **Additional Settings**: Optional fields with defaults

This keeps the Playground clean for users who just want to enter a prompt and generate, while still exposing all parameters for advanced use.

```python theme={null}
class MyInput(BaseModel):
    # These appear in the main form (required or important)
    prompt: str = Field(description="Required -- always visible")

    # These collapse into "Additional Settings"
    guidance_scale: float = Field(default=7.5, ge=1.0, le=20.0)
    seed: int = Field(default=-1)
    num_images: int = Field(default=1, ge=1, le=4)
```
