> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Download Model Weights and Files

> Download model weights, datasets, and external files to your runner using fal toolkit utilities and Hugging Face best practices.

Most AI applications need to download model weights or datasets before they can serve requests. This page covers the fal toolkit utilities for downloading files (`download_file` and `download_model_weights`), as well as best practices for optimizing Hugging Face downloads on fal's infrastructure. All downloaded files should be stored on [persistent storage](/documentation/development/use-persistent-storage) at `/data` so they are cached across runner restarts.

These download operations typically happen inside your [setup()](/documentation/development/app-lifecycle) method, which runs once when a new runner starts. Faster downloads mean shorter cold starts, so the optimization techniques in this guide directly affect your app's responsiveness when scaling up. For broader cold start strategies beyond downloads, see [Optimizing Cold Starts](/documentation/serverless/optimizations/optimize-cold-starts).

## Downloading Files

You can download files from external sources using the `download_file` function. This function handles downloading files from URLs with built-in caching and error handling.

This is particularly useful for downloading datasets, configuration files, or any external resources your application needs.

```python theme={null}
from fal.toolkit import download_file, FAL_PERSISTENT_DIR


class MyApp(fal.App):
    def setup(self):
        path = download_file(
            "https://example.com/myfile.txt",
            FAL_PERSISTENT_DIR / "mydir",
        )
        ...
```

## Downloading Model Weights

You can download model weights from external sources using the `download_model_weights` function. This function is specifically designed for downloading model weights and provides several useful features:

* **Predefined storage location**: Automatically stores weights in an optimized directory structure
* **Smart caching**: Avoids re-downloading weights that are already present unless forced
* **Authentication support**: Supports custom request headers for private repositories

This function is particularly useful for downloading pre-trained model weights from Hugging Face, custom model repositories, or private storage locations.

```python theme={null}
from fal.toolkit import download_model_weights


class MyApp(fal.App):
    def setup(self):
        path = download_model_weights(
            "https://example.com/myfile.txt",
            # Optional: force download even if the weights are already present
            force=False,
            # Optional: specify request headers
            request_headers={
                "Authorization": "Bearer <token>",
            },
        )
        ...
```

## Improving Hugging Face download speeds

The Hugging Face library caches files locally to prevent duplicate downloads. Within Fal, this cache is automatically placed on the [`/data` persistent volume](./use-persistent-storage) via the `HF_HOME` environment variable that is set to `/data/.cache/huggingface`.

The steps below offer additional speedups.

### Set Hugging Face token

Ensure you have your Hugging Face token set to be used by Fal runs. Authenticated downloads seem to be faster than anonymous ones:

`fal secret set HF_TOKEN=xxx`

### Save weights to the `/data` volume

Hugging Face weights need to be stored within the `/data` volume. This:

* Speeds up runner starts by removing the need for files to be reconstructed from the cache (which is already on `/data`)
* Ensures enough disk space is available

```python theme={null}
snapshot_download(
    repo_id=model_id,
    local_dir="/data/models/deepseek-ai",
    ...
)
```

### Speed up initial weights downloading

Depending on the size of the weights, the initial call to `snapshot_download` can take a while.

Hugging Face seems to reduce download speeds for large models after some time. While individual transfer thread often start at 50+ MB/s, after a while the speed drops to 5-6 MB/s.

There are 3 ways to speed up downloads:

* Increase concurrency, `max_workers` and cache size:

  ```python theme={null}
  os.environ["HF_XET_HIGH_PERFORMANCE"] = "1"
  os.environ["HF_XET_CHUNK_CACHE_SIZE_BYTES"] = "1000000000000"
  os.environ["HF_XET_NUM_CONCURRENT_RANGE_GETS"] = "32"

  snapshot_download(
      repo_id=model_id,
      local_dir=model_dir,
      max_workers=32
  )
  ```

* Download many models in parallel: when downloading multiple models, it helps to start a separate Fal run for each one. The different source IP address reduces the risk of rate limiting.

* Restart slow downloads: restart the run after e.g. 10 minutes, which will likely cause it to go to a different physical server, and the download will resume at higher speeds.

### Speed up model files check

Even after fully caching weights, calling `snapshot_download` with a large model can sometimes take 45+ seconds.

The Hugging Face library takes this time to do API calls and metadata checks. You can use `local_files_only=True` to skip this step, which typically makes the call return in less than 1 second.

Using `local_files_only=True` will throw an error if the files are not completely cached. To prevent that, it is a good idea to wrap the call in a try/catch block and retry it without `local_files_only`:

```python theme={null}
from huggingface_hub.errors import LocalEntryNotFoundError

try:
    snapshot_download(
        ...
        local_files_only=True,
    )
except LocalEntryNotFoundError:
    snapshot_download(
        ...
    )
```

### Speed up model loads

Hugging face models are typically split into multiple files, and loading them happens serially. This is sub-optimal if the files are not cached locally as they will be fetched one by one.

It is advisable to pre-read all the files in parallel which will create missing caches concurrently, at much higher speeds.

Please refer to [Sequential vs parallel reading](./use-persistent-storage#sequential-vs-parallel-reading).

## Caching Compiled Kernels

Once your model weights are stored on `/data`, you can also cache compiled PyTorch kernels to `/data/inductor-caches/`. This is particularly useful for models using `torch.compile()`, as it avoids recompiling kernels on every worker startup.

<Tip>
  Learn how to share compiled kernels across workers in [Optimize Startup with Compiled Caches](/documentation/serverless/optimizations/optimize-startup-with-compiled-caches).
</Tip>
