> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Working with Files

> Download input files and return generated outputs from your fal App using the toolkit's file types and download utilities.

Most AI models consume files as input and produce files as output. A video upscaler takes a video URL and returns an enhanced video. An image generator takes a text prompt and returns images. Your [fal App](/documentation/getting-started/apps-and-execution) needs a way to download files that users provide, process them, and return the results as publicly accessible URLs. The `fal.toolkit` provides a set of file types and download utilities that handle all of this.

The download utilities (`download_file`, `download_model_weights`) handle the input side: they download remote files to a local path on your runner, with built-in caching and streaming for large files. The file types (`File`, `Image`, `Video`, `Audio`) handle the output side: you create them from raw bytes, PIL images, or local files, and they automatically upload to [fal's CDN](/documentation/model-apis/fal-cdn) and return a public URL. Together, these cover the complete file I/O lifecycle for a request. For defining input and output schemas that the [Playground](/documentation/model-apis/playground) renders correctly, see [Handle Inputs and Outputs](/documentation/development/handle-inputs-and-outputs).

## Downloading Input Files

Users provide file inputs as URLs. The `download_file` function downloads them to a local path on your runner for processing. It handles large files efficiently by streaming in 64 MB chunks, and it writes to a temporary file first then renames atomically so you never end up with a partial file if the download fails.

```python theme={null}
from fal.toolkit import download_file

class MyModel(fal.App):
    machine_type = "GPU-A100"

    @fal.endpoint("/")
    def process(self, video_url: str) -> dict:
        local_path = download_file(video_url, target_dir="/tmp/inputs")
        result = self.model.process(str(local_path))
        return {"output": result}
```

If `target_dir` is a relative path, it resolves relative to `/data` ([persistent storage](/documentation/development/use-persistent-storage)). So `download_file(url, target_dir="models/")` saves to `/data/models/`. The function also handles `data:` URIs automatically, decoding base64-encoded inline content without making a network request.

### Caching

`download_file` checks if the local file already exists and compares its size to the remote file's `Content-Length` header. If they match, it returns the existing path without re-downloading. This makes repeated calls with the same URL essentially free.

```python theme={null}
path = download_file(url, target_dir="/data/inputs")

path = download_file(url, target_dir="/data/inputs")

path = download_file(url, target_dir="/data/inputs", force=True)
```

<Note>
  Caching uses file size comparison, not content hashing. If a remote file changes but stays the same size, the cached version is returned. Use `force=True` if you need to guarantee freshness.
</Note>

### Authenticated Downloads

If the file is hosted behind authentication (e.g., a private S3 bucket or a gated model on Hugging Face), pass custom headers via `request_headers`:

```python theme={null}
path = download_file(
    "https://private-storage.example.com/model.bin",
    target_dir="/data/models",
    request_headers={"Authorization": "Bearer your-token"},
)
```

### File Size Limits

Set `filesize_limit` (in MB) to reject files that are too large before downloading:

```python theme={null}
path = download_file(url, target_dir="/tmp", filesize_limit=500)
```

### Downloading Model Weights

For the common pattern of downloading model weights to persistent storage, `download_model_weights` is a convenience wrapper around `download_file`. It stores files in `/data/.fal/model_weights/` using a hash of the URL as the directory name, so repeated calls with the same URL are cached automatically.

```python theme={null}
from fal.toolkit import download_model_weights

class MyModel(fal.App):
    def setup(self):
        weights_path = download_model_weights("https://huggingface.co/org/model/resolve/main/weights.bin")
        self.model = load_from_weights(weights_path)
```

For more details on downloading and caching large model files, see [Download Model Weights](/documentation/development/download-model-weights-and-files).

***

## Returning Files from Endpoints

When your model generates a file, wrap it in one of the toolkit's file types before returning it. The type handles uploading to fal's CDN and returning a public URL in the response.

```python theme={null}
import fal
from fal.toolkit import Image

class MyModel(fal.App):
    machine_type = "GPU-A100"

    def setup(self):
        self.pipe = load_model()

    @fal.endpoint("/")
    def generate(self, prompt: str) -> dict:
        pil_image = self.pipe(prompt).images[0]
        return {"image": Image.from_pil(pil_image)}
```

The returned object has a `.url` field containing the public CDN URL (e.g., `https://v3.fal.media/files/...`). These URLs are publicly accessible and subject to your [media expiration settings](/documentation/model-apis/media-expiration).

### File Types and Methods

All file types extend `File` and inherit its methods. `Image` adds `width`, `height`, and PIL conversion. `Video` and `Audio` add no extra fields but tell the Playground to render the appropriate media player.

| Type             | Class Methods                                                                             | Extra Fields                                          |
| ---------------- | ----------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| `File`           | `from_path(path)`, `from_bytes(data, content_type=, file_name=)`                          | `url`, `content_type`, `file_name`, `file_size`       |
| `Image`          | `from_pil(pil_image, format=)`, `from_bytes(data, format, size=)`, inherits `from_path()` | `width`, `height`                                     |
| `Video`          | Inherits `from_path()`, `from_bytes()`                                                    | (none beyond File)                                    |
| `Audio`          | Inherits `from_path()`, `from_bytes()`                                                    | (none beyond File)                                    |
| `CompressedFile` | Inherits `from_path()`, `from_bytes()`                                                    | Supports `__iter__()` and `glob()` for ZIP extraction |

Every file type also provides instance methods: `as_bytes()` returns the file content as bytes, and `save(path)` writes it to a local path. `Image` additionally provides `to_pil()` to convert back to a PIL Image.

### Supported Formats

`File`, `Video`, and `Audio` accept any file format. There is no validation or allowlist at the SDK level. You can pass any URL or bytes regardless of content type. The `content_type` field is metadata that gets stored alongside the file but does not restrict what you can upload.

`Image` is the only type with a defined format list. When using `Image.from_pil()` or `Image.from_bytes()`, the `format` parameter accepts `"png"`, `"jpeg"`, `"jpg"`, `"webp"`, or `"gif"`. When using `Image.from_path()` (inherited from `File`), there is no format restriction.

The Playground renders previews based on the type you use (`Image` shows an image viewer, `Video` shows a video player, `Audio` shows an audio player), but playback depends on browser support. For maximum compatibility, use widely supported formats like MP4 (H.264) for video and WAV or MP3 for audio.

### Creating Files

The most common patterns for creating file objects:

```python theme={null}
from fal.toolkit import File, Image, Video, Audio

image = Image.from_pil(pil_image)
image = Image.from_pil(pil_image, format="webp")
image = Image.from_bytes(raw_bytes, format="png")
image = Image.from_path("/tmp/output.png")

video = Video.from_path("/tmp/output.mp4")
audio = Audio.from_path("/tmp/output.wav")
audio = Audio.from_bytes(raw_bytes, content_type="audio/wav", file_name="output.wav")

generic = File.from_path("/tmp/result.obj")
generic = File.from_bytes(data, content_type="application/octet-stream", file_name="model.glb")
```

### The Type System and Playground

Using `Image`, `Video`, or `Audio` in your Pydantic output schema tells the Playground to render the appropriate preview. `Image` shows an image viewer, `Video` shows a video player, and `Audio` shows an audio player. If you use the base `File` type, the Playground renders a download link instead.

```python theme={null}
from fal.toolkit import Image, Video, Audio

class Output(BaseModel):
    image: Image
    video: Video
    audio: Audio
```

For richer input schemas with file URL types that validate correctly, see the `FileInput` and `ImageInput` union types in [Handle Inputs and Outputs](/documentation/development/handle-inputs-and-outputs).

### Compressed Files

`CompressedFile` extends `File` with ZIP extraction support. When you iterate over a `CompressedFile` or call `glob()`, it automatically downloads and extracts the archive to a temporary directory.

```python theme={null}
from fal.toolkit import CompressedFile

class MyApp(fal.App):
    @fal.endpoint("/")
    def process(self, archive_url: str) -> dict:
        archive = CompressedFile(url=archive_url)
        png_files = list(archive.glob("*.png"))
        return {"file_count": len(png_files)}
```

The extracted directory is cleaned up automatically when the `CompressedFile` object is garbage collected.

***

## CDN vs /data Storage

Your app works with two storage systems that serve different purposes. Understanding when to use each prevents common mistakes like storing temporary outputs in persistent storage or losing generated files after a runner shuts down.

The [fal CDN](/documentation/model-apis/fal-cdn) is for generated outputs that you return to users. When you call `Image.from_pil()` or `File.from_path()`, the file is uploaded to the CDN and a public URL is returned. These URLs are accessible to anyone without authentication, and they expire according to your [media expiration settings](/documentation/model-apis/media-expiration). Each upload produces a unique URL with no shared namespace.

The `/data` directory is [persistent storage](/documentation/development/use-persistent-storage) mounted as a local filesystem on every runner. It is shared across all runners and all apps in your account. Use it for model weights, datasets, cached preprocessed files, and anything that should persist across requests and runner restarts. Files on `/data` are not URL-accessible and remain until you delete them.

For per-request temporary files that don't need to persist, use `/tmp`. It is local to each runner and cleared when the runner shuts down.

|                 | CDN                                                                          | /data                             | /tmp                       |
| --------------- | ---------------------------------------------------------------------------- | --------------------------------- | -------------------------- |
| **Use for**     | Generated outputs returned to users                                          | Model weights, datasets, caches   | Per-request scratch files  |
| **Persistence** | Subject to [expiration settings](/documentation/model-apis/media-expiration) | Permanent until deleted           | Cleared on runner shutdown |
| **Shared**      | No (each upload is unique)                                                   | Yes (across all runners and apps) | No (per-runner)            |
| **Access**      | Public URL, no auth                                                          | Local filesystem only             | Local filesystem only      |

<CardGroup cols={2}>
  <Card title="fal CDN" href="/documentation/model-apis/fal-cdn">
    Uploading files from client code before calling a model
  </Card>

  <Card title="Persistent Storage" href="/documentation/development/use-persistent-storage">
    Managing persistent files on /data
  </Card>
</CardGroup>
