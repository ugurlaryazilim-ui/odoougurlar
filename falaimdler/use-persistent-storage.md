> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Persistent Storage

> Store model weights, datasets, and files on the shared /data volume that persists across runners and deployments.

Every fal [runner](/documentation/getting-started/runners-and-caching) has access to a persistent `/data` volume. This is a distributed filesystem that is shared across all your apps and runners, linked to your fal account. Files written to `/data` persist between requests, across runner restarts, and across deployments. Use it to store model weights, datasets, configuration files, and any other data your apps need.

The `/data` volume is the primary mechanism for avoiding repeated downloads during [cold starts](/documentation/serverless/optimizations/optimize-cold-starts). When a new runner starts and calls [setup()](/documentation/development/app-lifecycle), it can load model weights from `/data` instead of downloading them from scratch. Because the volume is backed by a multi-layer cache (local NVME, distributed datacenter cache, and a global object store), subsequent reads are fast even on fresh nodes. For downloading files and model weights to `/data`, see [Downloading Models and Files](/documentation/development/download-model-weights-and-files).

<Frame>
  <iframe className="w-full aspect-video rounded-lg" srcdoc="<style>*{padding:0;margin:0;overflow:hidden}html,body{height:100%}img,span{position:absolute;width:100%;top:0;bottom:0;margin:auto}span{height:1.5em;text-align:center;font:48px/1.5 sans-serif;color:white;text-shadow:0 0 0.5em black}</style><a href='https://www.youtube.com/embed/gDJJ9bppyV8?start=923&end=1000&autoplay=1'><img src='/docs/images/video-thumbs/use-persistent-storage.jpg' alt='Files UI - fal Serverless'><span>▶</span></a>" frameborder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen />
</Frame>

## Using `/data` in Your App

The `/data` directory is automatically mounted on every runner. Files you write there persist until you delete them. A common pattern is to check whether a file already exists before downloading it, so that only the first runner pays the download cost.

```python theme={null}
import fal
from pathlib import Path

DATA_DIR = Path("/data/mnist")

class MyModel(fal.App):
    requirements = ["torch>=2.0.0", "torchvision"]
    machine_type = "GPU"

    def setup(self):
        import torch
        from torchvision import datasets

        already_present = DATA_DIR.exists()
        if already_present:
            print("Test data is already downloaded, skipping download!")

        test_data = datasets.FashionMNIST(
            root=DATA_DIR,
            train=False,
            download=not already_present,
        )
        ...
```

When you invoke this app for the first time, Torch downloads the test dataset to `/data`. Subsequent invocations, even those on new runners after the previous one shut down, skip the download and load directly from the cached files.

<Note>
  For HuggingFace libraries, fal automatically sets `HF_HOME` to `/data/.cache/huggingface`, so all downloaded models from `transformers`, `diffusers`, and `huggingface_hub` are persisted without any extra configuration.
</Note>

Since `/data` is shared across all runners, you should be careful when multiple runners write to the same path simultaneously. The recommended pattern is to write to a temporary file beside the final destination, then use `os.rename` to move it into place. This makes the operation quasi-atomic and prevents other runners from reading an incomplete file.

```python theme={null}
import tempfile, os
from pathlib import Path

WEIGHTS_FILE = Path("/data/weights.safetensors")

class MyModel(fal.App):
    def setup(self):
        if not WEIGHTS_FILE.exists():
            with tempfile.NamedTemporaryFile(delete=False, dir="/data") as temp_file:
                # download the weights to temp file
                ...
                os.rename(temp_file.name, WEIGHTS_FILE)
        ...
```

When loading model weights that span many files (as most `from_pretrained()` calls do), the sequential loading process does not take full advantage of the filesystem's parallel capabilities. You can speed it up significantly by pre-reading all the files in parallel before loading, which forces chunks into the local cache:

```python theme={null}
import subprocess

MODEL_DIR = "/data/models/deepseek-ai"
subprocess.check_call(
    f"find '{MODEL_DIR}' -type f | xargs -P 32 -I {{}} cat {{}} > /dev/null",
    shell=True
)
```

For a dedicated guide on this technique, see [Parallel File Loading](/documentation/serverless/optimizations/parallel-file-loading).

## Uploading Files to `/data`

Outside of a running app, you can upload files to `/data` through the dashboard, CLI, REST API, or a one-off function.

The [Dashboard > Files](https://fal.ai/dashboard/files) page provides a visual interface for dragging and dropping files, uploading from URLs, organizing folders, and managing your stored files.

From the CLI, use `fal files` commands:

```bash theme={null}
fal files list
fal files list models/
fal files upload local-file.bin remote-path/file.bin
```

For direct integration, the Platform APIs provide endpoints for uploading, listing, and downloading files. See the [Platform API Reference](/api-reference/platform-apis/for-serverless) for the full specification.

To upload files programmatically (for example, downloading weights from a URL to `/data` before deploying your app), use a `@fal.function` that writes directly to the filesystem:

```python theme={null}
import fal

@fal.function(machine_type="S")
def upload_weights():
    import urllib.request
    urllib.request.urlretrieve(
        "https://example.com/model-weights.safetensors",
        "/data/models/weights.safetensors"
    )
    print("Weights uploaded to /data")
```

This runs on a fal runner with access to `/data`, so the downloaded file is immediately available to all your apps.

## How It Works

The `/data` volume is mounted at the same path on every runner in your account. It is eventually consistent, meaning that a file written by one runner may take a moment to appear on another runner in a different datacenter, though within the same datacenter propagation is nearly instant.

| Property          | Value                                       |
| ----------------- | ------------------------------------------- |
| **Mount path**    | `/data` on all runners                      |
| **Shared across** | All apps and runners in your account        |
| **Consistency**   | Eventually consistent                       |
| **Max file size** | Up to 50 GB (resumable), \~1 TB (multipart) |
| **Persistence**   | Files persist until you delete them         |

Under the hood, each file is split into 4MB chunks identified by their hash and saved to a global object store. A metadata layer tracks the mapping between file paths and chunks, making operations like renames atomic and fast. The volume features two caching layers: a local cache on the node using RAID 5 NVME drives (10-15 GB/s), and a distributed cache across all servers in the datacenter using a 100 Gbps network (6-8 GB/s). A cache miss at both levels falls through to the backing object store (1.5-8 GB/s). This is why parallel reads are so much faster than sequential ones: each chunk can be fetched from a different cache node simultaneously.

When your app generates output files (images, videos, audio) and returns them through `fal.toolkit.Image` or `fal.toolkit.File`, those are uploaded to fal's CDN and returned as public URLs. CDN files are separate from `/data` storage. To control how long CDN files are retained, see [Media Expiration](/documentation/model-apis/media-expiration). For small key-value data (configuration, cached API responses, session state), fal also provides [KVStore](/documentation/development/use-kv-store) which offers faster access for data up to 1.9MB per value.
