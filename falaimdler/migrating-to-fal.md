> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Migrating to fal

> Bring your existing models and infrastructure to fal with minimal code changes.

If you are already running AI models on another platform or on your own infrastructure, fal is designed to make migration straightforward. You can bring your existing Docker containers, HTTP servers, or platform-specific code and deploy them on fal's GPU infrastructure with minimal changes. The guides in this section provide step-by-step walkthroughs for common migration paths.

If you are starting a new project rather than migrating, you can skip this section entirely and go to [Defining Your Environment](/documentation/development/container-setup) to set up your app from scratch.

The fastest path is [Migrate a Docker Server](/documentation/development/migrate-external-docker-server), which lets you deploy any existing HTTP server with `@fal.function` and `exposed_port` with no changes to your application code. If you are coming from a specific platform, the [Replicate](/documentation/development/migrate-from-replicate), [Modal](/documentation/development/migrate-from-modal), and [RunPod](/documentation/development/migrate-from-runpod) guides provide side-by-side code comparisons and cover how to map your existing configuration (GPU types, scaling, secrets, storage) to fal equivalents.
