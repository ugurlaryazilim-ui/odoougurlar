About
Run Upscale On Fal

1. Calling the API
#
Install the client
#
The client provides a convenient way to interact with the model API.


pip install fal-client
Setup your API Key
#
Set FAL_KEY as an environment variable in your runtime.


export FAL_KEY="YOUR_API_KEY"
Submit a request
#
The client API handles the API submit protocol. It will handle the request status updates and return the result when the request is completed.

Python
import fal_client

def on_queue_update(update):
    if isinstance(update, fal_client.InProgress):
        for log in update.logs:
           print(log["message"])

result = fal_client.subscribe(
    "fal-ai/esrgan",
    arguments={
        "image_url": "https://storage.googleapis.com/falserverless/model_tests/remove_background/elephant.jpg"
    },
    with_logs=True,
    on_queue_update=on_queue_update,
)
print(result)

Python (async)

import asyncio
import fal_client

async def subscribe():
    handler = await fal_client.submit_async(
        "fal-ai/esrgan",
        arguments={
            "image_url": "https://storage.googleapis.com/falserverless/model_tests/remove_background/elephant.jpg"
        },
    )

    async for event in handler.iter_events(with_logs=True):
        print(event)

    result = await handler.get()

    print(result)


if __name__ == "__main__":
    asyncio.run(subscribe())


2. Authentication
#
The API uses an API Key for authentication. It is recommended you set the FAL_KEY environment variable in your runtime when possible.

API Key
#
Protect your API Key
When running code on the client-side (e.g. in a browser, mobile app or GUI applications), make sure to not expose your FAL_KEY. Instead, use a server-side proxy to make requests to the API. For more information, check out our server-side integration guide.

3. Queue
#
Long-running requests
For long-running requests, such as training jobs or models with slower inference times, it is recommended to check the Queue status and rely on Webhooks instead of blocking while waiting for the result.

Submit a request
#
The client API provides a convenient way to submit requests to the model.

Python

import fal_client

handler = fal_client.submit(
    "fal-ai/esrgan",
    arguments={
        "image_url": "https://storage.googleapis.com/falserverless/model_tests/remove_background/elephant.jpg"
    },
    webhook_url="https://optional.webhook.url/for/results",
)

request_id = handler.request_id

Python (async)

import asyncio
import fal_client

async def submit():
    handler = await fal_client.submit_async(
        "fal-ai/esrgan",
        arguments={
            "image_url": "https://storage.googleapis.com/falserverless/model_tests/remove_background/elephant.jpg"
        },
        webhook_url="https://optional.webhook.url/for/results",
    )

    request_id = handler.request_id
    print(request_id)

if __name__ == "__main__":
    asyncio.run(submit())

    Fetch request status
#
You can fetch the status of a request to check if it is completed or still in progress.

Python
status = fal_client.status("fal-ai/esrgan", request_id, with_logs=True)

Python (async)
status = await fal_client.status_async("fal-ai/esrgan", request_id, with_logs=True)

Get the result
#
Once the request is completed, you can fetch the result. See the Output Schema for the expected result format.

Python

result = fal_client.result("fal-ai/esrgan", request_id)

Python (async)
result = await fal_client.result_async("fal-ai/esrgan", request_id)

4. Files
#
Some attributes in the API accept file URLs as input. Whenever that's the case you can pass your own URL or a Base64 data URI.

Data URI (base64)
#
You can pass a Base64 data URI as a file input. The API will handle the file decoding for you. Keep in mind that for large files, this alternative although convenient can impact the request performance.

Hosted files (URL)
#
You can also pass your own URLs as long as they are publicly accessible. Be aware that some hosts might block cross-site requests, rate-limit, or consider the request as a bot.

Uploading files
#
We provide a convenient file storage that allows you to upload files and use them in your requests. You can upload files using the client API and use the returned URL in your requests.

Python

url = fal_client.upload_file("path/to/file")

Python (async)

url = fal_client.upload_file_async("path/to/file")


Read more about file handling in our file upload guide.

5. Schema
#
Input
#
image_url string
Url to input image

scale float
Rescaling factor Default value: 2

tile integer
Tile size. Default is 0, that is no tile. When encountering the out-of-GPU-memory issue, please specify it, e.g., 400 or 200

face boolean
Upscaling a face

model ModelEnum
Model to use for upscaling Default value: "RealESRGAN_x4plus"

Possible enum values: RealESRGAN_x4plus, RealESRGAN_x2plus, RealESRGAN_x4plus_anime_6B, RealESRGAN_x4_v3, RealESRGAN_x4_wdn_v3, RealESRGAN_x4_anime_v3

output_format OutputFormatEnum
Output image format (png or jpeg) Default value: "png"

Possible enum values: png, jpeg


{
  "image_url": "https://storage.googleapis.com/falserverless/model_tests/remove_background/elephant.jpg",
  "scale": 2,
  "model": "RealESRGAN_x4plus",
  "output_format": "png"
}
Output
#
image Image
Upscaled image


{
  "image": {
    "url": "",
    "content_type": "image/png",
    "file_name": "z9RV14K95DvU.png",
    "file_size": 4404019,
    "width": 1024,
    "height": 1024
  }
}
Other types
#
Image
#
url string
The URL where the file can be downloaded from.

content_type string
The mime type of the file.

file_name string
The name of the file. It will be auto-generated if not provided.

file_size integer
The size of the file in bytes.

width integer
The width of the image in pixels.

height integer
The height of the image in pixels.

