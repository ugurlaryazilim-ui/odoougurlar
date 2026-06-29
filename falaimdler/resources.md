> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Libraries, APIs, and Community

> Client libraries, open-source packages, API references, and community links for building with fal.

This page collects everything you need beyond the core documentation: the open-source libraries you install, the API references you look up, and the community channels where you can get help. Whether you are calling models from Python or JavaScript, deploying your own with the [CLI](/api-reference/cli/index), or integrating fal into a larger system with the [Platform APIs](/api-reference/platform-apis/index), the links below will get you there.

All fal libraries are open source and available on GitHub. The platform itself offers a [model gallery](https://fal.ai/models), a [dashboard](https://fal.ai/dashboard) for managing your account, and a [sandbox](https://fal.ai/sandbox) for comparing models side by side. If you get stuck, the [Discord](https://discord.gg/fal-ai) community and [blog](https://blog.fal.ai) are good places to start.

## Open-Source Packages

| Package                | Install                            | What it does                                                                                                             | Source                                                                                 |
| ---------------------- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------- |
| `fal`                  | `pip install fal`                  | Deploy models with the serverless runtime, CLI (`fal deploy`, `fal run`), and toolkit (`Image`, `File`, `download_file`) | [fal-ai/fal](https://github.com/fal-ai/fal) (Apache-2.0)                               |
| `fal-client`           | `pip install fal-client`           | Call models from Python with `subscribe`, `submit`, `upload_file`                                                        | [fal-ai/fal](https://github.com/fal-ai/fal/tree/main/projects/fal_client) (Apache-2.0) |
| `@fal-ai/client`       | `npm install @fal-ai/client`       | Call models from JavaScript with the same API as the Python client, with TypeScript types                                | [fal-ai/fal-js](https://github.com/fal-ai/fal-js) (MIT)                                |
| `@fal-ai/server-proxy` | `npm install @fal-ai/server-proxy` | Server-side proxy for web apps that keeps your API key off the client (Next.js, Express)                                 | [fal-ai/fal-js](https://github.com/fal-ai/fal-js) (MIT)                                |
| `flashpack`            | `pip install flashpack`            | Fast model loading with high-throughput tensor loading for PyTorch (up to 25 Gbps)                                       | [fal-ai/flashpack](https://github.com/fal-ai/flashpack) (MIT)                          |

## Platform

<CardGroup cols={2}>
  <Card title="Model Gallery" icon="cube" href="https://fal.ai/models">
    Browse 1,000+ production-ready AI models ([docs](/documentation/model-apis/overview))
  </Card>

  <Card title="Dashboard" icon="gauge" href="https://fal.ai/dashboard">
    Manage apps, keys, billing, and monitoring ([analytics](/documentation/serverless/observability/app-analytics), [events](/documentation/serverless/observability/app-events), [errors](/documentation/serverless/observability/error-analytics))
  </Card>

  <Card title="Sandbox" icon="flask" href="https://fal.ai/sandbox">
    Compare models side by side in your browser ([docs](/documentation/model-apis/sandbox))
  </Card>

  <Card title="Status Page" icon="signal" href="https://status.fal.ai">
    Real-time platform health and incident history
  </Card>
</CardGroup>

## Documentation

The docs are organized into three main areas depending on how you use fal. Model APIs covers calling existing models, Serverless covers deploying your own, and Compute covers dedicated GPU instances for training or custom workloads.

<CardGroup cols={2}>
  <Card title="Model APIs" icon="cube" href="/documentation/model-apis/overview">
    Call 1,000+ models with simple API calls: inference, streaming, real-time
  </Card>

  <Card title="Serverless" icon="server" href="/documentation/serverless/index">
    Deploy your own models: environment setup, endpoints, scaling, observability
  </Card>

  <Card title="Compute" icon="microchip" href="/documentation/compute/index">
    Dedicated GPU instances with SSH access for training and custom workloads
  </Card>

  <Card title="Examples" icon="code" href="/examples/index">
    Step-by-step tutorials for image, video, and audio generation
  </Card>

  <Card title="Changelog" icon="clock" href="/changelog">
    Platform updates and new features
  </Card>

  <Card title="OpenAPI Spec" icon="file-code" href="/api-reference/platform-apis/openapi-schema">
    Machine-readable API specification for building custom integrations
  </Card>
</CardGroup>

## API References

For programmatic access beyond the client libraries, fal exposes a REST API for managing apps, files, and keys, a full CLI reference, and the Python SDK docs.

<CardGroup cols={3}>
  <Card title="Platform APIs" icon="rectangle-terminal" href="/api-reference/platform-apis/index">
    REST API for managing apps, files, metrics, and keys
  </Card>

  <Card title="CLI Reference" icon="terminal" href="/api-reference/cli/index">
    Full command reference for the fal CLI
  </Card>

  <Card title="Python SDK" icon="python" href="/api-reference/python-sdk/index">
    Python SDK API reference
  </Card>
</CardGroup>

## Client Libraries

fal has official client libraries for Python and JavaScript, plus community-maintained clients for Swift, Kotlin, and Dart. Each library handles authentication, request queuing, and file uploads so you can focus on your application.

<CardGroup cols={3}>
  <Card title="Python" icon="python" href="/api-reference/client-libraries/python/index">
    pip install fal-client
  </Card>

  <Card title="JavaScript" icon="js" href="/api-reference/client-libraries/javascript/index">
    npm install @fal-ai/client
  </Card>

  <Card title="Swift" icon="swift" href="/api-reference/client-libraries/swift/index">
    iOS client
  </Card>

  <Card title="Kotlin" icon="code" href="/api-reference/client-libraries/kotlin/index">
    Android / JVM client
  </Card>

  <Card title="Dart" icon="code" href="/api-reference/client-libraries/dart/index">
    Flutter client
  </Card>
</CardGroup>

## Community and Support

The fal community is active on Discord, where you can ask questions, share projects, and get help from the team and other developers. The blog covers product updates and engineering deep dives.

<CardGroup cols={3}>
  <Card title="Discord" icon="discord" href="https://discord.gg/fal-ai">
    Join the community, ask questions, share what you're building
  </Card>

  <Card title="Blog" icon="newspaper" href="https://blog.fal.ai">
    Product updates, tutorials, and engineering deep dives
  </Card>

  <Card title="Contact Sales" icon="building" href="https://fal.ai/enterprise#contact-sales">
    Enterprise plans, dedicated support, and custom solutions
  </Card>
</CardGroup>
