> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# fal Runtime

> How to use fal's managed Python runtime to run your models.

The fal runtime is the recommended way to define your app's environment. Instead of writing a Dockerfile, you list your pip dependencies in the `requirements` attribute and fal builds an optimized, cached environment for you. This approach handles CUDA setup, PyTorch index URLs, and environment isolation automatically based on your chosen [machine type](/documentation/deployment/machine-types).

If you need system-level packages, a specific base image, or a non-Python runtime, use a [custom container](/documentation/development/use-custom-container-image) instead. If you need to include local Python modules or clone external repositories, see [Import Code](/documentation/development/import-code). For an overview of when to use which approach, see [Environment and Runtime](/documentation/development/container-setup).

## Defining Requirements

The `requirements` attribute in your `fal.App` class is where you specify the Python packages your model needs. fal ensures these are installed in the [runner's](/documentation/deployment/runners) environment before [setup()](/documentation/development/app-lifecycle#runner-startup) is called.

```python theme={null}
import fal

class MyModel(fal.App):
    machine_type = "GPU-A100"
    
    requirements = [
        "torch==2.4.0",
        "transformers",
        "diffusers",
        "accelerate"
    ]
    
    def setup(self):
        import torch
        ...
```

Pin your package versions (e.g., `torch==2.4.0`) to ensure reproducible builds. Use the `requirements` attribute instead of running `pip install` inside `setup()`, since packages in `requirements` are installed during the container build and cached across deploys. Only include the packages your app actually needs to keep startup times short.

When you deploy, fal creates an isolated environment based on your `machine_type`, installs your listed packages, and caches the resulting container image. On subsequent deploys, unchanged requirements are served from cache. Your `setup()` method then runs on the provisioned runner to load the model into memory.

## Using Prebuilt Wheels

You can install packages directly from wheel URLs. This is useful for custom-built packages or packages not available on PyPI.

### Direct URL

Provide the full URL to a wheel file:

```python theme={null}
requirements = [
    "https://your-storage.example.com/wheels/mypackage-1.0.0-cp311-cp311-linux_x86_64.whl",
]
```

### Package @ URL (PEP 440)

Use the `package@url` syntax to give the package a name for dependency resolution:

```python theme={null}
requirements = [
    "mypackage@https://your-storage.example.com/wheels/mypackage-1.0.0-cp311-cp311-linux_x86_64.whl",
]
```

This syntax is recommended when other packages depend on `mypackage`, as pip can properly track the dependency.

## Alternative Package Indexes

Use `--extra-index-url` or `--find-links` to install packages from alternative sources.

### Extra Index URL

Install packages from an additional PyPI-compatible index:

```python theme={null}
requirements = [
    "torch==2.5.0",
    "--extra-index-url",
    "https://download.pytorch.org/whl/cu124",
]
```

<Warning>
  The `--extra-index-url` flag must appear **before** any packages that need it. Place index flags at the beginning or directly before the relevant packages.
</Warning>

### Find Links

Use `--find-links` to search for packages in a directory or URL containing wheel files:

```python theme={null}
requirements = [
    "mypackage",
    "--find-links",
    "https://github.com/your-org/releases/download/v1.0.0/",
]
```

### Multiple Indexes

Combine multiple index sources when needed:

```python theme={null}
requirements = [
    "--extra-index-url",
    "https://download.pytorch.org/whl/cu124",
    "--extra-index-url",
    "https://your-company.example.com/simple",
    "torch==2.5.0",
    "your-internal-package==1.0.0",
]
```

## Private Packages

### Private Git Repositories

Install directly from a private GitHub repository using a personal access token:

```python theme={null}
requirements = [
    "git+https://YOUR_TOKEN@github.com/your-org/private-repo.git",
]
```

Pin to a specific commit or tag for reproducibility:

```python theme={null}
requirements = [
    "git+https://YOUR_TOKEN@github.com/your-org/private-repo.git@v1.0.0",
    "git+https://YOUR_TOKEN@github.com/your-org/private-repo.git@abc123def",
]
```

<Warning>
  **Security Consideration**: Tokens embedded in requirements are visible in your code. For better security:

  * Use short-lived tokens when possible
  * Consider hosting wheels on a storage service with pre-signed URLs
  * Use [fal secrets](/documentation/development/manage-secrets-securely) for sensitive values in your app code
</Warning>

### Private PyPI Index

Install from a private PyPI server with authentication:

```python theme={null}
requirements = [
    "--extra-index-url",
    "https://username:password@pypi.your-company.com/simple",
    "your-private-package==1.0.0",
]
```

### Pre-signed URLs

For private storage (S3, GCS, etc.), generate a pre-signed URL with an expiration time:

```python theme={null}
requirements = [
    "https://your-bucket.s3.amazonaws.com/wheels/mypackage-1.0.0.whl?AWSAccessKeyId=...&Signature=...&Expires=...",
]
```

## Dynamic Wheel Selection

When you need different wheels for different Python versions or platforms, use a helper function:

```python theme={null}
def get_package_wheel():
    import sys
    wheels = {
        10: "https://example.com/wheels/mypackage-1.0.0-cp310-cp310-linux_x86_64.whl",
        11: "https://example.com/wheels/mypackage-1.0.0-cp311-cp311-linux_x86_64.whl",
    }
    return wheels[sys.version_info.minor]


class MyApp(fal.App):
    machine_type = "GPU-A100"
    requirements = [
        "torch==2.5.0",
        get_package_wheel(),
    ]
```

<Note>
  Helper functions are evaluated at deploy time on your local machine, so they have access to local environment variables and can make decisions based on the target Python version.
</Note>

***

<Card title="Importing Local Code" href="/documentation/development/import-code">
  Learn how to bring your local Python modules and files into the fal runtime.
</Card>
