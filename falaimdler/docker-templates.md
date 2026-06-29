> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Docker Templates and Best Practices

> Production-ready Dockerfile templates and optimization tips for fal Serverless.

This page provides ready-to-use Dockerfile templates for common deployment patterns and covers best practices for building efficient container images on fal. If you are new to custom containers on fal, start with [Use a Custom Container Image](/documentation/development/use-custom-container-image) for the core setup.

For optimizing container images specifically for cold start performance (layer ordering, image size reduction, FlashPack), see [Optimize Container Images](/documentation/serverless/optimizations/optimize-container-images).

## Templates

### Base Python

For applications that only need pip packages and basic system tools.

```dockerfile theme={null}
FROM falai/base:3.11-12.1.0

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    git wget curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    requests==2.31.0 \
    numpy==1.24.3

# Install fal last to ensure compatible dependency versions
RUN pip install --no-cache-dir fal
```

### PyTorch and HuggingFace

For deep learning applications using PyTorch and the HuggingFace ecosystem.

```dockerfile theme={null}
FROM falai/base:3.11-12.1.0

RUN pip install --no-cache-dir \
    torch==2.6.0 \
    accelerate==1.6.0 \
    transformers==4.51.3 \
    diffusers==0.31.0 \
    hf_transfer==0.1.9 \
    peft==0.15.0 \
    sentencepiece==0.2.0 \
    --extra-index-url \
    https://download.pytorch.org/whl/cu124

# Install fal last to ensure compatible dependency versions
RUN pip install --no-cache-dir fal

ENV CUDA_HOME=/usr/local/cuda
ENV PATH=$CUDA_HOME/bin:$PATH
ENV LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
ENV TORCH_CUDA_ARCH_LIST="6.0 6.1 7.0 7.5 8.0 8.6 8.9 9.0 9.0a"
```

### Custom CUDA Version

When you need a specific CUDA runtime that differs from the fal base image.

```dockerfile theme={null}
FROM nvidia/cuda:12.8.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-dev \
    python3.11-venv \
    python3-pip \
    wget curl ca-certificates ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# fal requires the python binary at standard paths
RUN ln -sf /usr/bin/python3.11 /usr/bin/python3 && \
    ln -sf /usr/bin/python3.11 /usr/bin/python

RUN python3 -m pip install --no-cache-dir --upgrade pip

# Install your packages
RUN pip install --no-cache-dir \
    torch==2.7.0 -f https://download.pytorch.org/whl/cu128/torch_stable.html

# Install fal last to ensure compatible dependency versions
RUN pip install --no-cache-dir fal
```

## Best Practices

### Use the fal base image

`falai/base:3.11-12.1.0` comes with the correct Python version, CUDA libraries, and a small image size that reduces container pull times during cold starts.

### Pin all package versions

Unpinned versions can break your app when a new release introduces incompatibilities. Pin everything for reproducible builds.

```dockerfile theme={null}
# Pinned versions - reproducible
RUN pip install torch==2.6.0 transformers==4.51.3

# Unpinned - may break on next deploy
RUN pip install torch transformers
```

### Clean up package caches

Removing caches reduces image size, which speeds up container pulls during cold starts.

```dockerfile theme={null}
RUN apt-get update && apt-get install -y ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir torch==2.6.0
```

### Use multi-stage builds for smaller images

Separate your build dependencies from your runtime to reduce the final image size.

```dockerfile theme={null}
FROM python:3.11 as builder
COPY requirements.txt .
RUN pip install --user -r requirements.txt

FROM python:3.11-slim
COPY --from=builder /root/.local /root/.local
```

### Store model weights on /data, not in the image

Download model weights to [persistent storage](/documentation/development/use-persistent-storage) (`/data`) in your `setup()` method rather than baking them into the Docker image. This keeps your image small, speeds up container pulls, and allows weights to be cached across runner restarts.

## Common Issues

### Python binary not found

**Problem**: `python: command not found` when using a custom base image.

**Solution**: Create symlinks so fal can find the Python binary:

```dockerfile theme={null}
RUN ln -sf /usr/bin/python3.11 /usr/bin/python3 && \
    ln -sf /usr/bin/python3.11 /usr/bin/python
```

### CUDA not available

**Problem**: `RuntimeError: No CUDA GPUs are available`

**Solution**: Ensure CUDA environment variables are set in your Dockerfile:

```dockerfile theme={null}
ENV CUDA_HOME=/usr/local/cuda
ENV PATH=$CUDA_HOME/bin:$PATH
ENV LD_LIBRARY_PATH=$CUDA_HOME/lib64:$LD_LIBRARY_PATH
```

### Dependency version conflicts

**Problem**: `ImportError` or version conflicts with pydantic, protobuf, or boto3.

**Solution**: Install the `fal` package (or these three packages) as the last `RUN pip install` step in your Dockerfile so they override any conflicting versions installed by earlier layers.
