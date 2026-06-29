> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Quick Start - Hello World

> Deploy your first fal app in under 2 minutes. Learn the basics with a simple Hello World example.

This guide walks you through building and deploying a Hello World app on fal Serverless. By the end, you will have a working app running on cloud infrastructure with a persistent URL, a [Playground](/documentation/model-apis/playground) for browser-based testing, and client SDK code you can copy into any project. The entire process takes about two minutes.

The workflow you will learn here is the same one you will use for every fal app, from simple utilities to production AI models. You write a Python class, test it with `fal run`, deploy it with `fal deploy`, and call it with the [fal client SDK](/documentation/development/calling-your-endpoints). Once you are comfortable with this loop, the [Deploy Your First Image Generator](/documentation/development/getting-started/deploy-your-first-image-generator) tutorial shows how to apply it to a real Stable Diffusion XL model.

## Before You Start

You'll need:

* Python - we recommend 3.11
* A [fal account](https://fal.ai/dashboard) (sign up is free)

## Step 1: Install the CLI

```bash theme={null}
pip install fal
```

## Step 2: Authenticate

Get your API key from the [fal dashboard](https://fal.ai/dashboard) and authenticate:

```bash theme={null}
fal auth login
```

This opens your browser to authenticate with fal. Once complete, your credentials are saved locally.

## Step 3: Create Your First App

Create a file called `hello_world.py` with this simple app:

```python theme={null}
import fal

class MyApp(fal.App):
    @fal.endpoint("/")
    def run(self) -> dict:
        print("Processing Hello World request...")
        return {"message": "Hello, World!"}
```

## Step 4: Test Your App Locally

Run your app to test it:

```bash theme={null}
fal run hello_world.py::MyApp
```

This starts your app and prints two URLs: a direct HTTP endpoint and a web playground. By default, `fal run` uses `public` auth mode so you can test without an API key.

<Tip>
  Use `--auth private` if you want to require API key authentication during development. See [Authentication Modes](/documentation/deployment/deploy-to-production#authentication-modes) for details.
</Tip>

Once you see `Application startup complete`, test it with curl using the URL from the output:

```bash theme={null}
curl $FAL_RUN_URL -H 'Content-Type: application/json' -d '{}'
```

```json theme={null}
{"message": "Hello, World!"}
```

You can also use the playground URL to test through a browser interface.

## Step 5: Deploy Your App

Once you are satisfied, deploy to create a persistent URL:

```bash theme={null}
fal deploy hello_world.py::MyApp
```

This deploys your app to fal's infrastructure with runners managed automatically based on demand. The output includes your app's endpoint ID and persistent URL.

## Step 6: Call Your Deployed App

Once deployed, you can call your app from any Python or JavaScript application using the fal client SDK.

<Tabs>
  <Tab title="Python">
    ```bash theme={null}
    pip install fal-client
    ```

    ```python theme={null}
    import fal_client

    result = fal_client.subscribe("your-username/hello-world", arguments={})
    print(result)
    # {"message": "Hello, World!"}
    ```
  </Tab>

  <Tab title="JavaScript">
    ```bash theme={null}
    npm install @fal-ai/client
    ```

    ```javascript theme={null}
    import { fal } from "@fal-ai/client";

    const result = await fal.subscribe("your-username/hello-world", {
      input: {},
    });
    console.log(result.data);
    // { message: "Hello, World!" }
    ```
  </Tab>
</Tabs>

Replace `your-username/hello-world` with the endpoint ID shown after deploying. See [Calling Your Endpoints](/documentation/development/calling-your-endpoints) for all calling patterns including async queue, streaming, real-time, and webhooks.

## Next Steps

From here, the [Deploy Your First Image Generator](/documentation/development/getting-started/deploy-your-first-image-generator) tutorial applies the same workflow to a real Stable Diffusion XL model. To understand how apps are structured and how runners start up and shut down, read [App Lifecycle](/documentation/development/app-lifecycle). For all the ways to call your deployed app, including async queue, streaming, real-time, and webhooks, see [Calling Your Endpoints](/documentation/development/calling-your-endpoints).
