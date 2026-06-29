> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Environment and Runtime

> Choose how to define the environment your fal app runs in.

Before your app can run on fal, the platform needs to know what packages, system libraries, and runtime your code depends on. This page helps you choose between two approaches: using fal's managed Python runtime with a pip requirements list, or bringing your own Docker container for full control over the environment.

If your app only needs pip packages, the managed runtime is the simplest option. You list your dependencies in the `requirements` attribute and fal handles CUDA setup and environment isolation, so you do not need to write or maintain a Dockerfile. If you need system-level packages (like `ffmpeg`), a specific CUDA version, a non-Python runtime, or you are migrating an existing Docker-based server, the custom container path gives you full control over the build. Both approaches produce the same kind of [runner](/documentation/getting-started/runners-and-caching) and support all the same scaling, observability, and deployment features.

## fal Runtime

For apps that only need pip packages, the managed runtime is the simplest setup. You define your pip dependencies in the `requirements` attribute of your app class and fal builds the container for you. This approach handles CUDA and PyTorch setup automatically based on your chosen [machine type](/documentation/deployment/machine-types), so you do not need to manage base images or CUDA library versions.

```python theme={null}
class MyApp(fal.App):
    machine_type = "GPU-A100"
    requirements = ["torch==2.4.0", "diffusers", "transformers"]
```

If your project has local Python modules or external repositories you need to include, the [Import Code](/documentation/development/import-code) page covers `app_files`, `local_python_modules`, and git clone patterns.

See [fal Runtime](/documentation/development/fal-runtime) for the full guide including CUDA handling, extra index URLs, and best practices.

## Custom Container

When you need full control over the environment, use a Dockerfile. This is the right choice when your app requires system packages, a specific base image, non-Python dependencies, or you are bringing an existing Docker image from another platform.

```python theme={null}
from fal.container import ContainerImage

class MyApp(fal.App):
    image = ContainerImage.from_dockerfile_str("""
        FROM pytorch/pytorch:2.1.0-cuda12.1-cudnn8-runtime
        RUN apt-get update && apt-get install -y ffmpeg
        RUN pip install diffusers transformers
    """)
```

You can also pull from private registries (Docker Hub, Google Artifact Registry, AWS ECR) with authentication. See [Custom Container Images](/documentation/development/use-custom-container-image) for the full Dockerfile reference and [Private Registries](/documentation/development/private-registries) for registry authentication setup.

## Which Should I Use?

| Situation                                  | Recommended                                                                                   |
| ------------------------------------------ | --------------------------------------------------------------------------------------------- |
| New Python model with pip packages         | [fal Runtime](/documentation/development/fal-runtime)                                         |
| Need system packages (ffmpeg, imagemagick) | [Custom Container](/documentation/development/use-custom-container-image)                     |
| Specific CUDA or PyTorch version           | [Custom Container](/documentation/development/use-custom-container-image)                     |
| Migrating an existing Docker server        | [Custom Container + exposed\_port](/documentation/development/migrate-external-docker-server) |
| Non-Python runtime (Node.js, Go, etc.)     | [Custom Container](/documentation/development/use-custom-container-image)                     |
| Local modules or git repositories          | [fal Runtime + Import Code](/documentation/development/import-code)                           |
