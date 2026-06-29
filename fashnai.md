API Setup
Follow these steps to get started with the FASHN API and make your first successful request.

Create Your Account
Sign up at app.fashn.ai to access the Developer API dashboard.

Generate an API Key
Go to the Developer API dashboard and click Create new API key.

Store your key securely 🔒
You won't be able to view it again after closing the window.

Purchase Credits
Go to Billing -> Click on the FASHN API tab.
Choose between subscription plans or on-demand credit top-ups based on your usage needs.

Understand the Fundamentals
Review API Fundamentals to understand authentication, request patterns, and error handling.

Try Virtual Try-On
Start with our Try-On Max endpoint - our most capable virtual try-on model with the highest quality output.

Explore Guides
Check out our Python and JavaScript quickstart guides for implementation examples.

Need Help?
If you encounter any issues during setup, check our Troubleshooting Guide or contact support@fashn.ai.

Next: Ready to make your first API call? Start with API Fundamentals or jump directly to Try-On Max.

Coding AgentsFASHN publishes an agent skill that teaches coding agents how to integrate FASHN through the REST API or the official TypeScript and Python SDKs. Once installed, your agent can wire FASHN into your project, or run a one-off generation, without you pasting documentation into the chat.
It works with Claude Code, Codex, Cursor, and many others.
Install
Install the skill with skills.sh. The CLI auto-detects which coding agents you have installed and configures the skill for each:
npx skills add fashn-ai/fashn-skill
API keyThe skill reads a FASHN_API_KEY from the environment. If it isn't set, the
skill asks for your key and helps you configure it, caching it for future
runs. Generate one from API Setup.
What the skill knows

Every FASHN endpoint and its inputs.
The prediction lifecycle: subscribe (submit and auto-poll) versus the manual run plus status polling flow.
The response envelope, the error catalog, credit usage, and webhooks.
Both integration paths (REST and the TypeScript or Python SDKs), plus a one-off inline run.

Usage
After installing, your agent loads the skill automatically (restart the agent if a session is already open). Mention FASHN in your request so the skill activates, then describe the outcome you want and it chooses the right model and wires up the call.
Build FASHN into your app

"Add a FASHN virtual try-on route to my Next.js app: accept a model photo and a garment image, and return the result URL."
"Use FASHN to write a Python worker that runs every garment in ./products through a model."
"Integrate FASHN API into my PHP project."

Generate something on the spot
In Claude Code and Codex, run a one-off generation by invoking the skill directly with /fashn:

/fashn generate three on-model shots of this product for our product page (product-to-model)
/fashn do a try-on with this model photo and this jacket (one-off inline run)

With other agents, describe the same task in chat and the skill activates automatically.
Links

Skill repository: github.com/fashn-AI/fashn-skill
skills.sh documentation: skills.sh/docs


Next: Pick an integration path with the TypeScript or Python SDK, or browse the API Reference.



v1.1.0
OpenAPI 3.1.1
FASHN API
FASHN

Download OpenAPI Document

Download OpenAPI Document
FASHN is an AI-first company specializing in human-centric generative image models tailored for fashion applications. The API provides developers and product teams with access to endpoints for image generation, virtual try-on, model creation, editing, background manipulation, and reframing functionalities.

Server
Server:
https://api.fashn.ai
Production server


Authentication
Required
Selected Auth Type:ApiKeyAuth
API key for API access (format: fa-UNIQUE_ID-HASH)
Bearer Token
:
Token
Show Password
Client Libraries
Python http.client
Predictions ​Copy link
AI prediction operations

PredictionsOperations
post
/v1/run
get
/v1/status/{id}

Create a new prediction​Copy link

Auth Required
Submit a prediction request for AI-powered fashion processing. Supports multiple model types including:

Try-on max (tryon-max)
Virtual try-on v1.6 (tryon-v1.6)
Model creation (model-create)
Model swap (model-swap)
Product to model (product-to-model)
Face to model (face-to-model)
Background operations (background-remove, background-change)
Image reframing (reframe)
Image to video (image-to-video)
Image editing (edit)
Product packshot (packshot)
All requests use the versioned format with model_name and inputs structure.

Query Parameters
webhook_urlCopy link to webhook_url
Type:string
Format:uri
Example
Optional webhook URL to receive completion notifications

Body
required
application/json

One of
TryOnMaxRequest
model_nameCopy link to model_name
Discriminator
enum
const:  
tryon-max
required
Premium virtual try-on built for AI fashion photoshoots and publishable e-commerce content. Places products onto model images with enhanced fidelity, producing images suitable for PDPs, catalogs, and marketing assets.

values
tryon-max
inputsCopy link to inputs
Type:object · TryOnMaxInputs
required
Show Child Attributesfor inputs
Responses

200
Prediction created successfully

Type:object · PredictionResponse
error
Type:string
nullable
required
Example
Error message if prediction failed to start

id
Type:string
required
Example
Unique prediction identifier

application/json

400
Bad request - Invalid request format. Check request structure and required parameters.

Type:object · ErrorResponse
error
Type:string
enum
required
Error type identifier

values
InternalServerError
BadRequest
NotFound
RateLimitExceeded
UnauthorizedAccess
OutOfCredits
ConcurrencyLimitExceeded
message
Type:string
required
Example
Human-readable error message

application/json

401
Unauthorized - Invalid/missing API key. Verify your API key in the Authorization header.

Type:object · ErrorResponse
error
Type:string
enum
required
Error type identifier

values
InternalServerError
BadRequest
NotFound
RateLimitExceeded
UnauthorizedAccess
OutOfCredits
ConcurrencyLimitExceeded
message
Type:string
required
Example
Human-readable error message

application/json

429
Too many requests - Implement request throttling, wait for current requests to complete, or purchase more credits.

Type:object · ErrorResponse
Examples
error
Type:string
enum
required
Error type identifier

values
InternalServerError
BadRequest
NotFound
RateLimitExceeded
UnauthorizedAccess
OutOfCredits
ConcurrencyLimitExceeded
message
Type:string
required
Example
Human-readable error message

application/json

500
Internal server error - Server error. Retry after delay, contact support if persistent.

Type:object · ErrorResponse
error
Type:string
enum
required
Error type identifier

values
InternalServerError
BadRequest
NotFound
RateLimitExceeded
UnauthorizedAccess
OutOfCredits
ConcurrencyLimitExceeded
message
Type:string
required
Example
Human-readable error message


import http.client
import json

conn = http.client.HTTPSConnection("api.fashn.ai")

payload = json.dumps({
  "model_name": "tryon-max",
  "inputs": {
    "product_image": "https://example.com/garment.jpg",
    "model_image": "https://example.com/model.jpg"
  }
})
headers = {
  "Content-Type": "application/json",
  "Authorization": "Bearer YOUR_SECRET_TOKEN"
}

conn.request(
    "POST",
    "/v1/run?webhook_url=https%3A%2F%2Fexample.com%2Fwebhook",
    body=payload,
    headers=headers,
)

response = conn.getresponse()
print(response.read().decode())

conn.close()

200
{
  "id": "12345678-1234-5678-9012-123456789012",
  "error": null
}
400
{"error":"BadRequest","message":"Invalid request body"}

401 
{"error":"UnauthorizedAccess","message":"Invalid or inactive API key"}
429
{
  "error": "RateLimitExceeded",
  "message": "Too many requests"
}

500
{"error":"InternalServerError","message":"Server error"}


Get prediction status​Copy link

Auth Required
Poll for the status of a specific prediction using its ID. Use this endpoint to track prediction progress and retrieve results.

Status States:

starting - Prediction is being initialized
in_queue - Prediction is waiting to be processed
processing - Model is actively generating your result
completed - Generation finished successfully, output available
failed - Generation failed, check error details
Output Availability:

CDN URLs (default): Available for 72 hours after completion
Base64 outputs (when return_base64: true): Available for 60 minutes after completion
Path Parameters
idCopy link to id
Type:string
required
Example
The unique prediction ID returned from the /v1/run endpoint

Responses

200
Prediction status retrieved successfully

Type:object · StatusResponse
Examples
error
Type:object
nullable
required
Error information if prediction failed, null otherwise

Structured error object with name and message fields

Show Child Attributesfor error
id
Type:string
required
Example
The unique prediction ID

status
Type:string
enum
required
Example
Current status of the prediction

values
starting
in_queue
processing
completed
failed
canceled
time_out
output
nullable
Generated media - for images, outputs are either CDN URLs or base64 (when requested); for videos, outputs are CDN MP4 URLs


One of
array string[]
Type:array string[]
Example
Array of CDN URLs to generated media (images or videos)

application/json

401
Unauthorized - Invalid or missing API key

Type:object · ErrorResponse
error
Type:string
enum
required
Error type identifier

values
InternalServerError
BadRequest
NotFound
RateLimitExceeded
UnauthorizedAccess
OutOfCredits
ConcurrencyLimitExceeded
message
Type:string
required
Example
Human-readable error message

application/json

404
Prediction not found

Type:object · ErrorResponse
error
Type:string
enum
required
Error type identifier

values
InternalServerError
BadRequest
NotFound
RateLimitExceeded
UnauthorizedAccess
OutOfCredits
ConcurrencyLimitExceeded
message
Type:string
required
Example
Human-readable error message

application/json

429
Rate limit exceeded

Type:object · ErrorResponse
error
Type:string
enum
required
Error type identifier

values
InternalServerError
BadRequest
NotFound
RateLimitExceeded
UnauthorizedAccess
OutOfCredits
ConcurrencyLimitExceeded
message
Type:string
required
Example
Human-readable error message

application/json

500
Internal server error

Type:object · ErrorResponse
error
Type:string
enum
required
Error type identifier

values
InternalServerError
BadRequest
NotFound
RateLimitExceeded
UnauthorizedAccess
OutOfCredits
ConcurrencyLimitExceeded
message
Type:string
required
Example
Human-readable error message

import http.client

conn = http.client.HTTPSConnection("api.fashn.ai")

headers = {
  "Authorization": "Bearer YOUR_SECRET_TOKEN"
}

conn.request(
    "GET",
    "/v1/status/123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
    headers=headers,
)

response = conn.getresponse()
print(response.read().decode())

conn.close()

200
{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "status": "starting",
  "output": null,
  "error": null
}

401
{
  "error": "UnauthorizedAccess",
  "message": "Invalid or inactive API key"
}

404
{
  "error": "NotFound",
  "message": "Prediction not found"
}

429
{
  "error": "RateLimitExceeded",
  "message": "Too many requests"
}

500

{
  "error": "InternalServerError",
  "message": "Failed to fetch prediction status"
}

Models

TryOnMaxRequest​Copy link
inputs
Type:object · TryOnMaxInputs
required

inputs
model_name
enum
const:  
tryon-max
required
Premium virtual try-on built for AI fashion photoshoots and publishable e-commerce content. Places products onto model images with enhanced fidelity, producing images suitable for PDPs, catalogs, and marketing assets.

values
tryon-max

TryOnRequest​Copy link
inputs
Type:object · TryOnInputs
required

inputs
model_name
enum
const:  
tryon-v1.6
required
Virtual Try-On v1.6 enables realistic garment visualization using just a single photo of a person and a garment

values
tryon-v1.6

ModelCreateRequest​Copy link
inputs
Type:object · ModelCreateInputs
required

inputs
model_name
enum
const:  
model-create
required
Model creation endpoint

values
model-create

ModelSwapRequest​Copy link
inputs
Type:object · ModelSwapInputs
required

inputs
model_name
enum
const:  
model-swap
required
Model swap endpoint for transforming model identity while preserving clothing and pose

values
model-swap

BackgroundRemoveRequest​Copy link
inputs
Type:object · BackgroundRemoveInputs
required

inputs
model_name
enum
const:  
background-remove
required
Background removal endpoint

values
background-remove

BackgroundChangeRequest​Copy link
inputs
Type:object · BackgroundChangeInputs
required

inputs
model_name
enum
const:  
background-change
required
Background change endpoint

values
background-change

ReframeRequest​Copy link
inputs
Type:object · ReframeInputs
required

inputs
model_name
enum
const:  
reframe
required
Image reframing endpoint

values
reframe

ProductToModelRequest​Copy link
inputs
Type:object · ProductToModelInputs
required

inputs
model_name
enum
const:  
product-to-model
required
Product to Model endpoint transforms product images into people wearing those products. It supports dual-mode operation: standard product-to-model (generates new person) and try-on mode (adds product to existing person)

values
product-to-model

FaceToModelRequest​Copy link
inputs
Type:object · FaceToModelInputs
required

inputs
model_name
enum
const:  
face-to-model
required
Face to Model endpoint transforms face images into try-on ready upper-body avatars. It converts cropped headshots or selfies into full upper-body representations that can be used in virtual try-on applications when full-body photos are not available, while preserving facial identity.

values
face-to-model

ImageToVideoRequest​Copy link
inputs
Type:object · ImageToVideoInputs
required

inputs
model_name
enum
const:  
image-to-video
required
Image to Video turns a single image into a short motion clip, with tasteful camera work and model movements tailored for fashion.

values
image-to-video

EditRequest​Copy link
inputs
Type:object · EditInputs
required

inputs
model_name
enum
const:  
edit
required
Versatile post-processing to restyle shots, adjust views, and fix details while preserving identity and product fidelity.

values
edit

PackshotRequest​Copy link
inputs
Type:object · PackshotInputs
required

inputs
model_name
enum
const:  
packshot
required
Turns a product photo into a clean commercial packshot. Optionally accepts a style reference image to guide staging, background, and lighting.

values
packshot

TryOnMaxInputs​Copy link
model_image
Type:string
required
Example
URL or base64 encoded image of the person to wear the product. The try-on process preserves the model's identity, pose, and styling while seamlessly integrating the product. Base64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)

product_image
Type:string
required
Example
URL or base64 encoded image of the product (garment, accessory, etc.) to place on the model. Base64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)

aspect_ratio
Type:string
enum
Optional aspect ratio for the output image.

values
21:9
1:1
4:3
3:2
2:3
Show all values
generation_mode
Type:string
enum
Sets the generation quality level. 'quality' produces the most detailed and realistic output but takes longer to process and costs more credits. 'fast' prioritizes speed and lower cost.

values
balanced
quality
num_images
Type:integer
min:  
1
max:  
4
Default
Number of images to generate per request (1-4).

output_format
Type:string
enum
Default
Specifies the desired output image format.

png: Delivers the highest quality image, ideal for use cases such as content creation where quality is paramount.
jpeg: Provides a faster response with a slightly compressed image, more suitable for real-time applications.
values
png
jpeg
prompt
Type:string
Default
Optional instructions to customize the try-on result. Use this to adjust how the product is worn or make minor styling changes.

Examples: "remove scarf", "tuck in shirt", "roll up sleeves", "open jacket"

resolution
Type:string
enum
Default
Resolution setting for the output image.

values
1k
2k
4k
return_base64
Type:boolean
Default
When set to true, the API will return the generated image as a base64-encoded string instead of a CDN URL. The base64 string will be prefixed according to the output_format (e.g., data:image/png;base64,... or data:image/jpeg;base64,...). This option offers enhanced privacy as user-generated outputs are not stored on our servers when return_base64 is enabled.

seed
Type:integer
min:  
0
max:  
4294967295
Default
Sets random operations to a fixed state. Use the same seed to reproduce results with the same inputs, or different seed to force different results.


TryOnInputs​Copy link
garment_image
Type:string
required
Example
Reference image of the clothing item to be tried on the model_image. Base64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)

model_image
Type:string
required
Example
Primary image of the person on whom the virtual try-on will be performed. Models Studio users can use their saved models by passing saved:<model_name>. Base64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)

category
Type:string
enum
Default
Use auto to enable automatic classification of the garment type. For flat-lay or ghost mannequin images, the system detects the garment type automatically. For on-model images, full-body shots default to a full outfit swap. For focused shots (upper or lower body), the system selects the most likely garment type (tops or bottoms).

values
auto
tops
bottoms
one-pieces
garment_photo_type
Type:string
enum
Default
Specifies the type of garment photo to optimize internal parameters for better performance. model is for photos of garments on a model, flat-lay is for flat-lay or ghost mannequin images, and auto attempts to automatically detect the photo type.

values
auto
flat-lay
model
mode
Type:string
enum
Default
Specifies the mode of operation.

performance mode is faster but may compromise quality (5 seconds).
balanced mode is a perfect middle ground between speed and quality (8 seconds).
quality mode is slower, but delivers the highest quality results (12–17 seconds).
values
performance
balanced
quality
moderation_level
Type:string
enum
Default
Sets the content moderation level for garment images.

conservative enforces stricter modesty standards suitable for culturally sensitive contexts. Blocks underwear, swimwear, and revealing outfits.
permissive allows swimwear, underwear, and revealing garments, while still blocking explicit nudity.
none disables all content moderation.
This technology is designed for ethical virtual try-on applications. Misuse—such as generating inappropriate imagery without consent—violates our Terms of Service. Setting moderation_level: none does not remove your responsibility for ethical and lawful use. Violations may result in service denial.

values
conservative
permissive
none
num_samples
Type:integer
min:  
1
max:  
4
Default
Number of images to generate per request (1-4).

output_format
Type:string
enum
Default
Specifies the desired output image format.

png: Delivers the highest quality image, ideal for use cases such as content creation where quality is paramount.
jpeg: Provides a faster response with a slightly compressed image, more suitable for real-time applications like consumer virtual try-on experiences.
values
png
jpeg
return_base64
Type:boolean
Default
When set to true, the API will return the generated image as a base64-encoded string instead of a CDN URL. The base64 string will be prefixed according to the output_format (e.g., data:image/png;base64,... or data:image/jpeg;base64,...). This option offers enhanced privacy as user-generated outputs are not stored on our servers when return_base64 is enabled.

seed
Type:integer
min:  
0
max:  
4294967295
Default
Sets random operations to a fixed state. Use the same seed to reproduce results with the same inputs, or different seed to force different results.

segmentation_free
Type:boolean
Default
Direct garment fitting without clothing segmentation, enabling bulkier garment try-ons with improved preservation of body shape and skin texture. Set to false if original garments are not removed properly.


ModelCreateInputs​Copy link
prompt
Type:string
required
Example
Prompt for the model image generation. Describes the desired fashion model, clothing, pose, and scene.

aspect_ratio
Type:string
enum
Default
Defines the width-to-height ratio of the generated image. This parameter controls the canvas dimensions for text-only generation. When image_reference is provided, the output inherits the reference image's aspect ratio and this parameter is ignored.

Supported Resolutions

Each aspect ratio corresponds to a specific resolution optimized for ~1MP output:

Aspect Ratio	Resolution	Use Case
21:9	1568 × 672	Ultra-wide cinematic
1:1	1024 × 1024	Square format, social media
2:3	832 × 1248	Portrait, fashion photography
3:4	880 × 1176	Standard portrait
4:5	912 × 1144	Instagram portrait
5:4	1144 × 912	Landscape portrait
4:3	1176 × 880	Traditional landscape
3:2	1176 × 784	Wide landscape
16:9	1360 × 768	Widescreen, banners
9:16	760 × 1360	Vertical video format
values
21:9
1:1
4:3
3:2
2:3
Show all values
face_reference
Type:string
Example
Optional face reference image to guide facial features in the generated model. When provided, the generated person will resemble the face in this image.

Base64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)

face_reference_mode
Type:string
enum
Default
Controls how the face reference is applied.

match_base adapts the reference face to match the base image's style and lighting.
match_reference preserves the reference face as closely as possible.
values
match_base
match_reference
generation_mode
Type:string
enum
Sets the generation quality level. 'quality' produces the most detailed and realistic output but takes longer to process and costs more credits. 'fast' prioritizes speed and lower cost.

values
fast
balanced
quality
image_reference
Type:string
Example
Optional reference image that guides the generation process. The model extracts structural information from this image to control the output composition.

Processing Behavior:

Aspect Ratio: When image_reference is provided and aspect_ratio is omitted, the output matches the reference image's dimensions. If aspect_ratio is explicitly set, it overrides the reference image's proportions.
Image Processing: Automatically resized while preserving aspect ratio.
Base64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)

num_images
Type:integer
min:  
1
max:  
4
Default
Number of images to generate.

output_format
Type:string
enum
Default
Specifies the desired output image format.

png: Delivers the highest quality image, ideal for use cases such as content creation where quality is paramount.
jpeg: Provides a faster response with a slightly compressed image, more suitable for real-time applications.
values
png
jpeg
resolution
Type:string
enum
Default
Resolution setting for the output image.

values
1k
2k
4k
return_base64
Type:boolean
Default
When set to true, the API will return the generated image as a base64-encoded string instead of a CDN URL. The base64 string will be prefixed according to the output_format (e.g., data:image/png;base64,... or data:image/jpeg;base64,...). This option offers enhanced privacy as user-generated outputs are not stored on our servers when return_base64 is enabled.

seed
Type:integer
min:  
0
max:  
4294967295
Default
Sets random operations to a fixed state. Use the same seed to reproduce results with the same inputs, or different seed to force different results.


ModelSwapInputs​Copy link
model_image
Type:string
required
Example
Source fashion model image containing the clothing and pose to preserve. The model's identity (face, skin tone, hair) will be transformed while keeping the outfit exactly as shown. Base64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)

aspect_ratio
Type:string
enum
Optional aspect ratio for the output image.

values
21:9
1:1
4:3
3:2
2:3
Show all values
face_reference
Type:string
Example
Optional face reference image to guide facial features of the replacement person. When provided, the new person will resemble the face in this image.

Base64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)

face_reference_mode
Type:string
enum
Default
Controls how the face reference is applied.

match_base adapts the reference face to match the base image's style and lighting.
match_reference preserves the reference face as closely as possible.
values
match_base
match_reference
generation_mode
Type:string
enum
Sets the generation quality level. 'quality' produces the most detailed and realistic output but takes longer to process and costs more credits. 'fast' prioritizes speed and lower cost.

values
fast
balanced
quality
num_images
Type:integer
min:  
1
max:  
4
Default
Number of images to generate.

output_format
Type:string
enum
Default
Specifies the desired output image format.

png: Delivers the highest quality image, ideal for use cases such as content creation where quality is paramount.
jpeg: Provides a faster response with a slightly compressed image, more suitable for real-time applications.
values
png
jpeg
prompt
Type:string
Default
Example
Description of the desired model identity transformation. Specify ethnicity, facial features, hair color, and other physical characteristics.

Default: Empty string (Random identity change)

resolution
Type:string
enum
Default
Resolution setting for the output image.

values
1k
2k
4k
return_base64
Type:boolean
Default
When set to true, the API will return the generated image as a base64-encoded string instead of a CDN URL. The base64 string will be prefixed according to the output_format (e.g., data:image/png;base64,... or data:image/jpeg;base64,...). This option offers enhanced privacy as user-generated outputs are not stored on our servers when return_base64 is enabled.

seed
Type:integer
min:  
0
max:  
4294967295
Default
Sets random operations to a fixed state. Use the same seed to reproduce results with the same inputs, or different seed to force different results.


BackgroundRemoveInputs​Copy link
image
Type:string
required
Example
Source image to remove the background from. The AI will automatically detect the main subject and create a clean cutout with transparent background. Base64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)

return_base64
Type:boolean
Default
When set to true, the API will return the generated image as a base64-encoded string instead of a CDN URL. The base64 string will be prefixed data:image/png;base64,.... This option offers enhanced privacy as user-generated outputs are not stored on our servers when return_base64 is enabled.


BackgroundChangeInputs​Copy link
image
Type:string
required
Example
Source image containing the subject to preserve. The AI will automatically detect and separate the foreground subject from the background. Base64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)

prompt
Type:string
required
Example
Description of the desired new background (e.g., 'beach sunset', 'modern office', 'forest clearing'). The AI generates a new background based on this description and harmonizes it with the preserved foreground subject.

generation_mode
Type:string
enum
Sets the generation quality level. 'quality' produces the most detailed and realistic output but takes longer to process and costs more credits. 'fast' prioritizes speed and lower cost.

values
fast
balanced
quality
num_images
Type:integer
min:  
1
max:  
4
Default
Number of images to generate in a single run.

output_format
Type:string
enum
Default
Specifies the output image format.

png: Delivers the highest quality image, ideal for use cases such as content creation where quality is paramount.
jpeg: Provides a faster response with a slightly compressed image, more suitable for real-time applications.
values
png
jpeg
resolution
Type:string
enum
Default
Resolution setting for the output image.

values
1k
2k
4k
return_base64
Type:boolean
Default
When set to true, the API will return the generated image as a base64-encoded string instead of a CDN URL. The base64 string will be prefixed according to the output_format (e.g., data:image/png;base64,... or data:image/jpeg;base64,...). This option offers enhanced privacy as user-generated outputs are not stored on our servers when return_base64 is enabled.

seed
Type:integer
min:  
0
max:  
4294967295
Default
Sets random operations to a fixed state. Use the same seed to reproduce results with the same inputs, or different seed to force different results.


ReframeInputs​Copy link
aspect_ratio
Type:string
enum
required
Example
Target aspect ratio for the reframed image. The AI determines whether expansion or cropping is more appropriate based on the current image content and dimensions.

Behavior:

If target is wider than source → may expand horizontally or crop vertically
If target is taller than source → may expand vertically or crop horizontally
If source already matches target (within 2% tolerance) → returns an error
Supported Aspect Ratios

Each aspect ratio corresponds to a specific resolution optimized for ~1MP output:

Aspect Ratio	Resolution	Use Case
21:9	1568 × 672	Ultra-wide cinematic
1:1	1024 × 1024	Square format, social media
4:3	1176 × 880	Traditional landscape
3:2	1248 × 832	Standard landscape
2:3	832 × 1248	Portrait, fashion photography
5:4	1144 × 912	Instagram landscape
4:5	912 × 1144	Instagram portrait
3:4	880 × 1176	Standard portrait
16:9	1360 × 760	Horizontal video format
9:16	760 × 1360	Vertical video format
values
21:9
1:1
4:3
3:2
2:3
Show all values
image
Type:string
required
Example
Source image to reframe to a new aspect ratio. The AI will intelligently analyze the image content and decide whether to expand (outpainting/zoom-out) or crop (zoom-in) based on subject position, content density, and edge details.

Resolution Handling: Output resolution is limited to ~1MP. If your image is already at or above this size, it will be downsampled so that, after reframing, the final result fits within the 1MP limit.

Base64 Format: Base64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)

generation_mode
Type:string
enum
Sets the generation quality level. 'quality' produces the most detailed and realistic output but takes longer to process and costs more credits. 'fast' prioritizes speed and lower cost.

values
fast
balanced
quality
num_images
Type:integer
min:  
1
max:  
4
Default
Number of images to generate per request (1-4).

output_format
Type:string
enum
Default
Specifies the desired output image format.

png: Delivers the highest quality image, ideal for use cases such as content creation where quality is paramount.
jpeg: Provides a faster response with a slightly compressed image, more suitable for real-time applications.
values
png
jpeg
return_base64
Type:boolean
Default
When set to true, the API will return the generated image as a base64-encoded string instead of a CDN URL. The base64 string will be prefixed according to the output_format (e.g., data:image/png;base64,... or data:image/jpeg;base64,...). This option offers enhanced privacy as user-generated outputs are not stored on our servers when return_base64 is enabled.

seed
Type:integer
min:  
0
max:  
4294967295
Default
Sets random operations to a fixed state. Use the same seed to reproduce results with the same inputs, or different seed to force different results.


ProductToModelInputs​Copy link
product_image
Type:string
required
Example
URL or base64 encoded image of the product to be worn. Supports clothing, accessories, shoes, and other wearable fashion items. Base64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)

aspect_ratio
Type:string
enum
Desired aspect ratio for the output image. Only applies when model_image is not provided (standard product-to-model mode).

When model_image is provided (try-on mode), this parameter is ignored and the output will match the model_image's aspect ratio.

Default: product_image's aspect ratio (standard mode only)

values
21:9
1:1
4:3
3:2
2:3
Show all values
generation_mode
Type:string
enum
Sets the generation quality level. 'quality' produces the most detailed and realistic output but takes longer to process and costs more credits. 'fast' prioritizes speed and lower cost.

values
fast
balanced
quality
image_prompt
Type:string
Example
Optional URL or base64 of an inspiration image to guide pose, environment, and lighting while keeping the final edit product-centric.

model_image
Type:string
Example
URL or base64 encoded image of the person to wear the product. When provided, enables try-on mode. When omitted, generates a new person wearing the product. Base64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)

output_format
Type:string
enum
Default
Specifies the desired output image format.

png: Delivers the highest quality image, ideal for use cases such as content creation where quality is paramount.
jpeg: Provides a faster response with a slightly compressed image, more suitable for real-time applications.
values
png
jpeg
prompt
Type:string
Default
Example
Additional instructions for person appearance (when model_image is not provided), styling preferences, or background.

Examples: "man with tattoos", "tucked-in", "open jacket", "rolled-up sleeves", "studio background", "professional office setting"

Default: None

resolution
Type:string
enum
Default
Resolution setting for the output image.

values
1k
2k
4k
return_base64
Type:boolean
Default
When set to true, the API will return the generated image as a base64-encoded string instead of a CDN URL. The base64 string will be prefixed data:image/png;base64,....

This option offers enhanced privacy as user-generated outputs are not stored on our servers when return_base64 is enabled.

seed
Type:integer
min:  
0
max:  
4294967295
Default
Seed for reproducible results. Use the same seed to reproduce results with the same inputs, or different seed to force different results. Must be between 0 and 2^32-1.


FaceToModelInputs​Copy link
face_image
Type:string
required
Example
URL or base64 encoded image of the face to transform into an upper-body avatar. The AI will analyze facial features, hair, and skin tone to create a representation suitable for virtual try-on applications.

Base64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)

aspect_ratio
Type:string
enum
Default
Desired aspect ratio for the output image. Vertical ratios (e.g. 2:3, 3:4, 9:16) produce the most natural upper-body portraits.

Default: 2:3

values
21:9
1:1
4:3
3:2
2:3
Show all values
generation_mode
Type:string
enum
Sets the generation quality level. 'quality' produces the most detailed and realistic output but takes longer to process and costs more credits. 'fast' prioritizes speed and lower cost.

values
fast
balanced
quality
num_images
Type:integer
min:  
1
max:  
4
Default
Number of images to generate in a single run.

output_format
Type:string
enum
Default
Specifies the output image format.

png - PNG format, original quality
jpeg - JPEG format, smaller file size
Default: "jpeg"

values
png
jpeg
prompt
Type:string
Default
Example
Optional styling or body shape guidance for the avatar representation. Examples: "athletic build", "curvy figure", "slender frame".

If you don't provide a prompt, the body shape will be inferred from the face image.

Default: Empty string

resolution
Type:string
enum
Default
Resolution setting for the output image.

values
1k
2k
4k
return_base64
Type:boolean
Default
When set to true, the API will return the generated image as a base64-encoded string instead of a CDN URL. The base64 string will be prefixed data:image/png;base64,....

This option offers enhanced privacy as user-generated outputs are not stored on our servers when return_base64 is enabled.

Default: false

seed
Type:integer
min:  
0
max:  
4294967295
Default
Sets random operations to a fixed state. Use the same seed to reproduce results with the same inputs, or different seed to force different results.


ImageToVideoInputs​Copy link
image
Type:string
required
Example
Source image to animate into a short video.

Base64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)

duration
Type:integer
enum
Default
Duration of the generated video in seconds.

values
5
10
end_image
Type:string
Example
Optional image to use as the final frame of the generated video. When provided, the video smoothly transitions from the image (start frame) to end_image (end frame) over the clip duration.

Only supported with resolution: "1080p".

Base64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>).

negative_prompt
Type:string
Optional cues to avoid undesirable motion or framing.

prompt
Type:string
Default
Optional motion guidance. Detailed prompting is not recommended because motion is difficult to control precisely. For the best results, leave this field empty and allow the system to plan motion automatically. If you include guidance, keep it short and concrete (e.g., "raising hand to touch face").

resolution
Type:string
enum
Default
Target video resolution used by the internal video engine.

values
480p
720p
1080p
seed
Type:integer
Default
Sets random operations to a fixed state. Use the same seed to reproduce results with the same inputs, or different seed to force different results.


EditInputs​Copy link
image
Type:string
required
Example
Source image to edit. The AI will apply the requested modifications based on your prompt while preserving the overall composition and identity of the image.

Base64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)

prompt
Type:string
required
Example
Natural language description of the edit to apply. Be specific about what you want to change.

Examples: "change the dress to red", "add sunglasses", "make the background a beach sunset", "change the shirt to a floral pattern"

aspect_ratio
Type:string
enum
Optional aspect ratio for the output image.

values
21:9
1:1
4:3
3:2
2:3
Show all values
generation_mode
Type:string
enum
Sets the generation quality level. 'quality' produces the most detailed and realistic output but takes longer to process and costs more credits. 'fast' prioritizes speed and lower cost.

values
fast
balanced
quality
image_context
Type:string
Example
Optional URL or base64 of a context image to guide the edit. This image provides additional visual context that influences how the edit is applied.

Base64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)

mask
Type:string
Example
Optional mask image where white (255) marks regions to edit and black (0) areas remain unchanged. When provided, the edit will only affect the masked regions, enabling precise local edits.

Base64 images must include the proper prefix (e.g., data:image/png;base64,<YOUR_BASE64>)

num_images
Type:integer
min:  
1
max:  
4
Default
Number of images to generate per request (1-4).

output_format
Type:string
enum
Default
Specifies the desired output image format.

png: Delivers the highest quality image, ideal for use cases such as content creation where quality is paramount.
jpeg: Provides a faster response with a slightly compressed image, more suitable for real-time applications.
values
png
jpeg
resolution
Type:string
enum
Default
Resolution setting for the output image.

values
1k
2k
4k
return_base64
Type:boolean
Default
When set to true, the API will return the generated image as a base64-encoded string instead of a CDN URL. The base64 string will be prefixed according to the output_format (e.g., data:image/png;base64,... or data:image/jpeg;base64,...). This option offers enhanced privacy as user-generated outputs are not stored on our servers when return_base64 is enabled.

seed
Type:integer
min:  
0
max:  
4294967295
Default
Sets random operations to a fixed state. Use the same seed to reproduce results with the same inputs, or different seed to force different results.


PackshotInputs​Copy link
product_image
Type:string
required
Example
Source product image to convert into a commercial packshot. The AI generates a clean studio-style presentation while preserving product identity and detail.

Base64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)

aspect_ratio
Type:string
enum
Optional aspect ratio for the output image.

values
21:9
1:1
4:3
3:2
2:3
Show all values
generation_mode
Type:string
enum
Sets the generation quality level. 'quality' produces the most detailed and realistic output but takes longer to process and costs more credits. 'fast' prioritizes speed and lower cost.

values
fast
balanced
quality
image_context
Type:string
Example
Optional URL or base64 of a style reference image guiding the packshot presentation (staging, background, lighting). The reference influences styling without overriding the product itself.

Base64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)

num_images
Type:integer
min:  
1
max:  
4
Default
Number of images to generate per request (1-4).

output_format
Type:string
enum
Default
Specifies the desired output image format.

png: Delivers the highest quality image, ideal for use cases such as content creation where quality is paramount.
jpeg: Provides a faster response with a slightly compressed image, more suitable for real-time applications.
values
png
jpeg
prompt
Type:string
Default
Optional natural-language description of the desired packshot styling. If empty, the model picks a sensible commercial default for the detected product.

Examples: "clean white background flat-lay", "soft studio lighting on a beige pedestal", "isolated on a marble surface"

resolution
Type:string
enum
Default
Resolution setting for the output image.

values
1k
2k
4k
return_base64
Type:boolean
Default
When set to true, the API will return the generated image as a base64-encoded string instead of a CDN URL. The base64 string will be prefixed according to the output_format (e.g., data:image/png;base64,... or data:image/jpeg;base64,...). This option offers enhanced privacy as user-generated outputs are not stored on our servers when return_base64 is enabled.

seed
Type:integer
min:  
0
max:  
4294967295
Default
Sets random operations to a fixed state. Use the same seed to reproduce results with the same inputs, or different seed to force different results.


PredictionResponse​Copy link
error
Type:string
nullable
required
Example
Error message if prediction failed to start

id
Type:string
required
Example
Unique prediction identifier


StatusResponse​Copy link
error
Type:object
nullable
required
Error information if prediction failed, null otherwise

Structured error object with name and message fields


error
id
Type:string
required
Example
The unique prediction ID

status
Type:string
enum
required
Example
Current status of the prediction

values
starting
in_queue
processing
completed
failed
canceled
time_out
output
nullable
Generated media - for images, outputs are either CDN URLs or base64 (when requested); for videos, outputs are CDN MP4 URLs


One of
array string[]
Type:array string[]
Example
Array of CDN URLs to generated media (images or videos)


ErrorResponse​Copy link
error
Type:string
enum
required
Error type identifier

values
InternalServerError
BadRequest
NotFound
RateLimitExceeded
UnauthorizedAccess
OutOfCredits
ConcurrencyLimitExceeded
message
Type:string
required
Example
Human-readable error message



API Fundamentals
This page explains the fundamental concepts and patterns that are consistent across all FASHN API endpoints. Understanding these concepts will help you integrate any current or future endpoint.

Let your coding agent do the integration
Install the FASHN agent skill and Claude Code, Codex, Cursor, or another agent can wire these patterns into your project for you: npx skills add fashn-ai/fashn-skill.

Authentication
All API requests require authentication using a Bearer token in the Authorization header:


Authorization: Bearer YOUR_API_KEY
You can obtain your API key from the Developer API Dashboard ↗.

Request Pattern
All FASHN model endpoints follow a consistent request pattern to the same /v1/run endpoint:

POST
https://api.fashn.ai/v1/run
Request Examples
cURL
JavaScript
Python

curl -X POST https://api.fashn.ai/v1/run \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer YOUR_API_KEY" \
     -d '{
           "model_name": "endpoint-specific-model-name",
           "inputs": {
             // endpoint-specific parameters
           }
         }'
Universal Request Properties
model_name
Required
string
Specifies which model/endpoint to use for processing. Each endpoint has its own unique model name.

inputs
Required
object
Contains all the input parameters for the selected model. The structure of this object varies by endpoint.

Response Pattern
Initial Response
When you submit a request to /v1/run, you'll receive an immediate response with a prediction ID:

Response

{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "error": null
}
Status Polling
Use the prediction ID to poll for status and results:

GET
https://api.fashn.ai/v1/status/{id}
Response States
Poll for the status of a specific prediction using its ID.

status
'starting' | 'in_queue' | 'processing' | 'completed' | 'failed'
The current state of your prediction:

starting - Prediction is being initialized
in_queue - Prediction is waiting to be processed
processing - Model is actively generating your result
completed - Generation finished successfully, output available
failed - Generation failed, check error details
Response Headers
x-fashn-credits-used: Indicates how many credits were consumed for that prediction.
Example Status Responses
In Progress:

Response

{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "status": "processing",
  "error": null
}
Completed:

Response

{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "status": "completed",
  "output": [
    "https://cdn.fashn.ai/123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1/output_0.png"
  ],
  "error": null
}
Output Availability Time Limits
CDN URLs (default): Available for 72 hours after completion
Base64 outputs (when return_base64: true): Available for 60 minutes after completion
Learn more in the Data Retention & Privacy section.

Failed:

Response

{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "status": "failed",
  "error": {
    "name": "ImageLoadError",
    "message": "Error loading model image: Invalid URL format"
  }
}
Error Handling
At a high level there are two kinds of errors you may see. For detailed guidance and the full list of error codes, see the Error Handling page.

API-Level Errors
These are request validation or auth failures that happen before a prediction ID is issued. They return an HTTP error code and a short payload. Example:

Response

// HTTP 401 UnauthorizedAccess
{
  "error": "UnauthorizedAccess",
  "message": "Unauthorized: Invalid token"
}
No id or status is returned because the request never entered processing.

Runtime Errors
These happen during model execution after a prediction ID was returned. You’ll see them when polling /v1/status/{id} with status: "failed". Some runtime errors are common across endpoints (for example, malformed image URLs), while others are endpoint-specific validations; see Error Handling for details. Example:

Response

{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "status": "failed",
  "error": {
    "name": "ImageLoadError",
    "message": "Error loading model image: Invalid URL format"
  }
}
Credits & Pricing
Credits are the billing unit for all FASHN API endpoints. Pricing is charged per successful output, and the exact cost depends on the endpoint and selected options.

Billing Basics
Failed predictions do not consume credits.
Pricing is applied per output. If you request multiple outputs, the per-output cost is multiplied accordingly.
Depending on the endpoint, pricing may be fixed per output, vary based on parameters such as resolution, generation_mode, or duration, or include optional surcharges such as face_reference.
Each endpoint page includes its own pricing summary in Model Specifications and, where needed, a detailed Credit Cost section. For a centralized overview, see the API pricing guide: Credit Costs ↗.

Rate Limits
These are the default rate limits that apply to all endpoints unless stated otherwise in the specific endpoint documentation:

Endpoint	Limit
/v1/run	50 requests per 60 seconds
/v1/status	50 requests per 10 seconds
Concurrency Limits
The API has a default concurrency limit of 6 requests per limit. This means you can have up to 6 concurrent requests being processed at any given time.

Rate Limit Adjustments
Our API rate limits are in place to ensure fair usage and prevent misuse of our services. However, we understand that legitimate applications may require higher limits as they grow. If your app's usage nears the specified rate limits, and this usage is justified by your application's needs, we will gladly increase your rate limit. Please reach out to our support@fashn.ai to discuss your specific requirements.

Endpoint Lifecycle
All FASHN API endpoints are tagged with a lifecycle state to help you understand their stability and integration recommendations:

stable - Mature endpoints that developers can trust will remain backwards-compatible. Any changes to these endpoints will maintain backwards compatibility.
preview - Should be stable functionality with reliable integration support, but noticeable improvements to the underlying pipeline might still occur before final release.
experimental - Supported endpoints that are still a work in progress. Underlying models or schema can change as we refine the technology.
deprecated - Endpoints that are no longer supported and will be discontinued. Migration to newer alternatives is required.
You'll find the lifecycle state listed in each endpoint's "Model Specifications" section to help you make informed integration decisions.

Webhooks
Instead of polling for status, you can configure webhooks to receive notifications when predictions complete. See the Webhooks Guide for setup instructions.

Error Handling
Understanding how the API reports errors helps you respond quickly and keep your integration resilient. There are two categories:

API-level errors: The request was rejected before a prediction ID was issued.
Runtime errors: The request was accepted, but the model failed during execution while you were polling or waiting on a webhook.
API-Level Errors
These errors return an HTTP status code and do not include an id or status because the request never entered processing. They are typically caused by auth, validation, or quota issues.

Response

// HTTP 401 UnauthorizedAccess
{
  "error": "UnauthorizedAccess",
  "message": "Unauthorized: Invalid token"
}
Code	Error	Cause	How to fix
400	BadRequest	Invalid request format	Check JSON structure and required parameters.
401	UnauthorizedAccess	Invalid or missing API key	Verify the Authorization: Bearer YOUR_API_KEY header.
404	NotFound	Resource not found	Confirm the endpoint URL and prediction ID.
429	RateLimitExceeded	Too many requests in the window	Add client-side throttling or backoff.
429	ConcurrencyLimitExceeded	Too many concurrent predictions	Wait for in-flight jobs to finish before sending new ones.
429	OutOfCredits	No API credits remaining	Refill credits before retrying.
500	InternalServerError	Server-side error	Retry with backoff; contact support if it persists.
Retries and idempotency
If you retry after an API-level error, send the same payload. Because no prediction ID was issued, duplicate processing is not a risk.

Runtime Errors
Runtime errors appear with status: "failed" when you poll /v1/status/{id} (HTTP 200) or receive webhook payloads. The response includes the prediction ID and an error object.

Response

{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "status": "failed",
  "error": {
    "name": "ImageLoadError",
    "message": "Error loading model image: Invalid URL format"
  }
}
Common runtime errors
Most runtime issues fall into a handful of shared cases across endpoints. Start with these before checking model-specific validation rules.

Name	Cause	How to fix
ImageLoadError	The API could not fetch or decode an input image or asset.	Use publicly accessible URLs with correct image Content-Type, or prefix base64 with data:image/<format>;base64, and confirm the data is valid.
ContentModerationError	An input image or text prompt violated content policies.	Replace or adjust the input to comply with content policies ↗. If the endpoint supports moderation controls (for example, moderation_level), choose the lowest level that still meets your safety requirements.
InputValidationError	Parameters were invalid or inconsistent.	Follow the error message to correct field values or required combinations before retrying.
ThirdPartyError	An upstream provider refused or failed the request.	Retry with backoff. Some upstream services (e.g. captioning, translation) may silently block content; if retries continue to fail, treat it like a content policy block and adjust inputs accordingly.
UnavailableError	A service needed to fulfill the request was temporarily overloaded or unavailable.	Retry with backoff.
PipelineError	An unexpected failure occurred inside the pipeline.	Retry with backoff.
Endpoint-specific runtime errors
Some models add extra validation tied to their workflow (for example, pose detection on virtual try-on or LoRA loading for variation). Refer to the Runtime Errors section on each endpoint page for those model-specific names and fixes.

Retries and support
Failed predictions do not consume credits.
If you still see runtime failures after aligning inputs to the schema and retrying with backoff, contact support@fashn.ai with the prediction ID so we can investigate.

Webhooks
Webhooks allow you to receive asynchronous notifications when a process completes. Instead of polling an endpoint to check the status, webhooks push updates directly to your specified URL.

How to Use Webhooks
To use webhooks with our API, simply append the webhook_url parameter to your /run request:


POST https://api.fashn.ai/v1/run?webhook_url=https://your-server.com/webhook
When the process completes, our system will send a POST request to your specified webhook URL with the complete response payload.

Webhook Retry Mechanism
Our system implements a robust retry mechanism to ensure webhook delivery:

If a webhook delivery fails (non-2xx response), we automatically retry
The system attempts up to 5 retries
Retries occur within a timespan of approximately 5 minutes
Example: Using Webhooks with the /run Endpoint
Based on the /run endpoint from the Virtual Try-On API, here's how to implement webhooks:


// Request to start a process with webhook notification
fetch(
  "https://api.fashn.ai/v1/run?webhook_url=https://your-server.com/webhook",
  {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: "Bearer YOUR_API_KEY",
    },
    body: JSON.stringify({
      model_name: "tryon-v1.6",
      inputs: {
        model_image: "http://example.com/path/to/model.jpg",
        garment_image: "http://example.com/path/to/garment.jpg",
      },
    }),
  },
);
Success Webhook Payload
When the process completes successfully, your webhook URL will receive a POST request with a payload similar to:


{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "status": "completed",
  "output": [
    "https://cdn.staging.fashn.ai/123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1/output_0.png"
  ],
  "error": null
}
Error Webhook Payload
When the process has failed, your webhook URL will receive a POST request with a payload similar to:


{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "status": "failed",
  "error": {
    "name": "ImageLoadError",
    "message": "Error loading model image: The URL's Content-Type is not an image. Content-Type: text/plain;charset=UTF-8"
  }
}
Runtime Errors
To learn more about runtime errors and how to handle them, check out our Runtime Errors guide.

Best Practices
Implement Idempotency: Your webhook handler should be idempotent to handle potential duplicate deliveries.
Respond Quickly: Your webhook endpoint should respond with a 2xx status code as quickly as possible. Process the webhook data asynchronously if needed.
Verify Webhooks: Consider implementing a verification mechanism to ensure webhooks are coming from our service.
Monitor Webhook Failures: Set up monitoring for webhook failures to detect any issues with your endpoint.
Troubleshooting
If you're not receiving webhook notifications:

Verify your webhook URL is publicly accessible
Check that your server responds with a 2xx status code
Test your webhook endpoint with a tool like Webhook.site ↗
For additional support, contact our team at support@fashn.ai.

Data Retention & Privacy
This guide consolidates all information about FASHN's data retention policies and privacy features to help you build data-sensitive applications with confidence.

This guide focuses on our Virtual Try-On endpoint, since it is our most privacy-sensitive use-case. However, the principles outlined here can be implemented in all other endpoints where applicable.

What FASHN Stores vs. What We Don't
What We Store
Request metadata: Who sent the API request, what the inputs were (request body), and when the request was made (timestamp).
Image URLs: The URLs you provide for model_image and garment_image are saved as part of the request body
Base64 placeholders: For base64 inputs, we store <base64> in request history, not the actual string
What We Don't Store
Input image files: Never stored on our servers, regardless of input method
Base64 image data: The actual base64 strings are never retained
Output images: Outputs returned through our CDN are automatically deleted after 72 hours (when using return_base64: true, outputs are kept in memory for 60 minutes only)
Key Privacy Insight
Storing image URLs does not compromise privacy if your URLs expire. Although FASHN saves the URLs you submit, once those URLs have expired, your images are no longer accessible through them.

Data Retention Timeline and Purpose
Output availability depends on your chosen delivery method:

CDN Delivery (Default)
Image outputs are temporarily stored for up to 72 hours for the following purposes:

Dashboard Preview: To allow you to conveniently preview your API outputs through the API dashboard.
Data Transfer Window: To provide sufficient time for you to transfer the data to your own storage, or to support use cases that do not require long-term storage.
Support & Troubleshooting: To enable us to assist effectively in the event that issues are reported with the outputs.
Content Moderation & Abuse Prevention: To allow us to conduct content moderation, review policy compliance, and investigate potential misuse of the technology.
After 72 hours, image outputs are automatically deleted and CDN URLs become inaccessible.

Base64 Delivery (return_base64: true)
For enhanced privacy, base64 outputs are kept in-memory only for 60 minutes after completion. After this time limit:

The status endpoint will return "<base64>_expired" instead of the actual base64 data
No persistent storage occurs during this 60-minute window
Your request history ↗ remains visible in the web app interface for monitoring and debugging purposes, showing:

Request parameters and metadata
URLs (but images at those URLs may be expired/inaccessible)
<base64> placeholders for base64 inputs
Status and error information
Important
Your data is never used for training or improving our AI models in any form.

Privacy-Enhanced Options
FASHN provides several API parameters to enhance privacy for data-sensitive applications:

Privacy Parameters

Best Practices for Data-Sensitive Applications
Choose the privacy strategy that best fits your application's requirements:

URL Expiry Strategy (Recommended)
Most effective approach for balanced privacy and performance. While FASHN stores URLs in request history, this becomes privacy-neutral when URLs expire.

Implementation:

Configure URL expiry: Set your image hosting to make URLs inaccessible after your required timeframe
Use signed URLs: Employ temporary, signed URLs that automatically expire
cURL
JavaScript
Python

curl -X POST https://api.fashn.ai/v1/run \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer YOUR_API_KEY_HERE" \
     -d '{
           "model_name": "tryon-v1.6",
           "inputs": {
             "model_image": "https://your-cdn.com/signed-url?expires=1735689600",
             "garment_image": "https://your-cdn.com/signed-url?expires=1735689600",
             "return_base64": true
           }
         }'
Privacy benefits: URLs become inaccessible after expiry, no output images stored

Base64 Strategy (Maximum Privacy)
For highly sensitive content where any URL storage is unacceptable. Only <base64> placeholders appear in request history, never actual image data.

cURL
JavaScript
Python

curl -X POST https://api.fashn.ai/v1/run \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer YOUR_API_KEY_HERE" \
     -d '{
           "model_name": "tryon-v1.6",
           "inputs": {
             "model_image": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABgAAD...",
             "garment_image": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABgAAD...",
             "return_base64": true,
             "output_format": "png"
           }
         }'
Privacy benefits: Zero image data touches FASHN's storage systems—all data stays within your API request/response cycle

Hybrid Approach
For applications with mixed privacy requirements:

cURL
JavaScript
Python

curl -X POST https://api.fashn.ai/v1/run \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer YOUR_API_KEY_HERE" \
     -d '{
           "model_name": "tryon-v1.6",
           "inputs": {
             "model_image": "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABgAAD...",
             "garment_image": "https://your-cdn.com/catalog-image.jpg",
             "return_base64": true
           }
         }'
Use standard URLs for non-sensitive images (product catalogs) and base64 for sensitive images (customer photos).

PythonThis guide shows you how to get started with FASHN's API using our official Python SDK. The SDK handles authentication, request/response parsing, error handling, and polling automatically.
For detailed documentation and how to use the FASHN API, please refer to:

API Reference
Troubleshooting Guide
GitHub Repository

Let your coding agent do the integrationInstall the FASHN agent skill and Claude Code, Codex, Cursor, or another agent can wire this SDK into your project for you: npx skills add fashn-ai/fashn-skill.
Installation
First, install the FASHN Python SDK:
pipuvpoetrypip install fashn
Generate an API Key
Go to the Developer API dashboard and click Create new API key.
Store your key securely 🔒You won't be able to view it again after closing the window.
Quick Start with the SDK
The SDK's subscribe method handles the entire prediction lifecycle automatically - it submits your request, polls for completion, and returns the final result. You can use any model_name from our API Reference section with their respective input parameters.
Synchronous
import os
from fashn import Fashn
 
client = Fashn(
    api_key=os.environ.get("FASHN_API_KEY"), # This is the default and can be omitted
)
 
result = client.predictions.subscribe(
    model_name="tryon-v1.6",
    inputs={
        "garment_image": "https://example.com/garment.jpg",
        "model_image": "https://example.com/model.jpg",
    },
)
 
print("Generation completed!")
print("Result:", result)
print("Credits used:", result.credits_used)
Async
import os
import asyncio
from fashn import AsyncFashn
 
async def main():
    client = AsyncFashn(
        api_key=os.environ.get("FASHN_API_KEY"),  # This is the default and can be omitted
    )
 
    result = await client.predictions.subscribe(
        model_name="tryon-v1.6",
        inputs={
            "garment_image": "https://example.com/garment.jpg",
            "model_image": "https://example.com/model.jpg",
        },
    )
 
    print("Generation completed!")
    print("Result:", result)
    print("Credits used:", result.credits_used)
 
asyncio.run(main())
Response
The subscribe method returns a response with these attributes:

id: Prediction ID.
status: Current state of the prediction.
output: Generated outputs when the prediction completes successfully.
error: Error details when status is failed.
credits_used: Number of credits consumed for that prediction. Present only when status is completed.

Error Handling
The FASHN API has two distinct types of errors that you need to handle in different places. For a complete list of all error types and status codes, see the API Fundamentals Error Handling section.
import os
import fashn
from fashn import Fashn
 
client = Fashn(
    api_key=os.environ.get("FASHN_API_KEY"),  # This is the default and can be omitted
)
 
try:
    result = client.predictions.subscribe(
        model_name="tryon-v1.6",
        inputs={
            "model_image": "https://example.com/model.jpg",
            "garment_image": "https://example.com/garment.jpg",
        },
    )
 
    # 1. Check for Runtime Errors (during model execution). Status can be failed, canceled or time_out.
    if result.status != "completed":
        print("Runtime Error - Status:", result.status)
        if result.error:
            print("Error message:", result.error.message)
    else:
        # 2. Success case (status is completed)
        print("Generation completed successfully!")
        print("Generated:", result.output)
 
except fashn.APIError as e:
    # 3. Handle API-Level Errors (before request processing)
    print("API-Level Error - Status:", e.status_code)
    print("Message:", e.message)
except Exception as e:
    # Network or unexpected error
    print("Network or unexpected error:", e)
API-Level Errors (handled in except blocks):

Occur before your request is accepted for processing
Examples: invalid API key (401), rate limits (429), bad request format (400)
Thrown as exceptions with e.status_code and e.message

Runtime Errors (check result.status):

Occur during model execution after successful request submission
Examples: image loading failures, content moderation, pose detection issues
Available in result.error fields when present

Configuration
Advanced configuration options (retries, timeouts, proxies, custom HTTP client) are available in our open source GitHub repository: fashn-python-sdk.
Advanced Usage
The SDK provides methods to submit a request and fetch the status of a request separately. If you choose this workflow you would need to:

Submit a request
Poll for the status of the request until it is completed

NoteThe subscribe method described above already implements this workflow with good defaults and better error handling.
We only recommend using this workflow if you have a specific use case that requires it.
Submit a request
Submit a request to the API and get a prediction ID.
import os
from fashn import Fashn
 
client = Fashn(api_key=os.environ.get("FASHN_API_KEY"))
 
response = client.predictions.run(
    model_name="tryon-v1.6",
    inputs={
        "model_image": "https://example.com/model.jpg",
        "garment_image": "https://example.com/garment.jpg",
    },
)
 
print("Prediction ID:", response.id)
Fetch request status
Use the prediction ID returned from the run method to fetch the status of the request.
import os
from fashn import Fashn
 
client = Fashn(api_key=os.environ.get("FASHN_API_KEY"))
 
status = client.predictions.status(
    "9dafef71-6e90-4bc9-ac05-d0d97c612722"  # Prediction ID
)
 
print("Prediction Status:", status.status)



Try-On MaxTry-On Max is our recommended virtual try-on endpoint, built for AI fashion photoshoots and publishable e-commerce content. It places products onto model images with enhanced fidelity, producing images suitable for PDPs, catalogs, and marketing assets.
This endpoint supports clothing, shoes, hats, jewelry, bags, and other wearable fashion items.

Model Specifications
Model Name: tryon-max
Lifecycle: experimental
Processing Time: 20s–120s (see below)
Output Formats: PNG, JPEG
Delivery Methods: URL or Base64 encoding
Credits: 2-5 per output image depending on resolution and generation_mode

Request
Generate try-on images by submitting your product and model images to the universal /v1/run endpoint:
POSThttps://api.fashn.ai/v1/runRequest ExamplescURLJavaScriptPythoncurl -X POST https://api.fashn.ai/v1/run \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer YOUR_API_KEY" \
     -d '{
           "model_name": "tryon-max",
           "inputs": {
             "product_image": "https://example.com/garment.jpg",
             "model_image": "https://example.com/person.jpg"
           }
         }'Response200Returns a prediction ID for status polling:Response{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "error": null
}
Request Parameters
Required Parameters
product_imageRequiredimage URL | base64URL or base64 encoded image of the product (garment, accessory, etc.) to place on the model.Base64 FormatBase64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)
model_imageRequiredimage URL | base64URL or base64 encoded image of the person to wear the product. The try-on process preserves the model's identity, pose, and styling while seamlessly integrating the product.Base64 FormatBase64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)
Optional Parameters
promptstringOptional instructions to customize the try-on result. Use this to adjust how the product is worn or make minor styling changes.Examples: "remove scarf", "tuck in shirt", "roll up sleeves", "open jacket".Default: Empty string (uses intelligent defaults based on the images)
resolution'1k' | '2k' | '4k'Output resolution tier. '1k' produces ~1 megapixel output, '2k' ~4 megapixels, and '4k' ~16 megapixels. Exact output dimensions depend on this tier and the image aspect ratio.Default: '1k'
generation_mode'balanced' | 'quality'Sets the generation quality level. 'quality' produces the most detailed and
realistic output but takes longer to process and costs more credits.
'balanced' offers a middle ground between speed and quality. If omitted,
FASHN selects generation_mode automatically. For tryon-max, omitted
generation_mode is currently billed as 'balanced' at all resolutions.
seedintegerSets random operations to a fixed state. Use the same seed to reproduce results with the same inputs, or a different seed to force different results.Default: 42
Range: 0 to 2^32 - 1
num_imagesintegerNumber of images to generate in a single request. Must be between 1 and 4. Additional images consume more compute (and credits) and can increase processing time.Default: 1
output_format'png' | 'jpeg'Specifies the output image format.
png: Lossless quality, best for further editing or when maximum fidelity is needed.
jpeg: Smaller file size with slight compression, suitable for direct web use.
Default: png
return_base64booleanWhen set to true, the API will return the generated image as a base64-encoded string instead of a CDN URL. The base64 string will be prefixed according to the output_format (e.g., data:image/png;base64,... or data:image/jpeg;base64,...).This option offers enhanced privacy as user-generated outputs are not stored on our servers when return_base64 is enabled.Default: false
Credit Cost
generation_mode \ resolution1k2k4kbalanced234quality345
Additional pricing rules:

num_images multiplies the total cost by the number of outputs requested.
If generation_mode is omitted, automatic pricing applies.

Processing Time
Processing time depends on both resolution and generation_mode. The fastest configuration (balanced + 1k) typically completes in under 30 seconds, while the most intensive (quality + 4k) can take up to 120 seconds. Actual latency may vary with current server load.
Response Polling
After submitting your request, poll the status endpoint using the returned prediction ID. See API Fundamentals for complete polling details.
Successful Response
When your try-on generation completes successfully, the status endpoint will return:
{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "status": "completed",
  "output": [
    "https://cdn.fashn.ai/123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1/output_0.png"
  ],
  "error": null
}
The output array contains URLs to your generated try-on images with the product seamlessly placed on the model.
Runtime Errors
Runtime errors for Try-On Max use the shared set in Error Handling.
Related Guides

Prompting in FASHN ↗ - Learn how to write effective prompts for best results
Image Preprocessing Best Practices - Optimize your input images for better results
Data Retention & Privacy - Understand how FASHN handles your data


Product to ModelPowered by best-in-class image editing AI, the Product to Model endpoint transforms product images into people wearing those products, with optional guidance from an inspiration image, background, or face reference.
This endpoint is designed specifically for wearable fashion items such as clothing, shoes, hats, jewelry, bags, and accessories.

Model Specifications
Model Name: product-to-model
Lifecycle: preview
Processing Time: 20s–120s (see below)
Output Formats: PNG, JPEG
Delivery Methods: URL or Base64 encoding
Credits: 1-5 per output image depending on resolution and generation_mode (+3 per output image with face_reference)

Combining a product with an existing model imageTo combine a product with an existing person image, use the
tryon-max endpoint. The model_image parameter
on this endpoint is deprecated and cannot be combined with image_prompt,
background_reference, or face_reference.
Request
Generate product-to-model images by submitting your product image to the universal /v1/run endpoint:
POSThttps://api.fashn.ai/v1/runRequest ExamplescURLJavaScriptPythoncurl -X POST https://api.fashn.ai/v1/run \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer YOUR_API_KEY" \
     -d '{
           "model_name": "product-to-model",
           "inputs": {
             "product_image": "http://example.com/path/to/product.jpg",
             "prompt": "professional office setting",
             "output_format": "png",
             "return_base64": false
           }
         }'Response200Returns a prediction ID for status polling:Response{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "error": null
}
Request Parameters
product_imageRequiredimage URL | base64URL or base64 encoded image of the product to be worn. Supports clothing,
accessories, shoes, and other wearable fashion items.
image_promptimage URL | base64Optional URL or base64 encoded inspiration image that guides pose, environment, and lighting while keeping the product centered in the final output.Default: None
face_referenceimage URL | base64Optional face identity reference to guide who the generated person should look like. When provided, the pipeline refines identity to match the reference while keeping product fidelity.Default: None
face_reference_mode'match_base' | 'match_reference'Controls how the identity from face_reference influences pose and expression.-match_reference favors the reference face’s pose and expression for maximum resemblance.-match_base gives more weight to the prompt (or system default prompt if omitted) when generating the person's pose and expression.Default: match_reference
promptstringAdditional instructions for person appearance, styling preferences, or background.Examples: "man with tattoos", "tucked-in", "open jacket", "rolled-up sleeves", "studio background".Default: None
aspect_ratiostringDesired aspect ratio for the output image. If omitted, the generation inherits the aspect ratio from the most specific image supplied (background_reference → image_prompt → product_image). Provide an explicit ratio to override that default even when using these image references.Supported ratios: "1:1", "3:4", "4:3", "9:16", "16:9", "2:3", "3:2", "4:5", "5:4"Default: Aspect ratio of the most specific image supplied
resolution'1k' | '2k' | '4k'Output resolution tier. '1k' produces ~1 megapixel output, '2k' ~4 megapixels, and '4k' ~16 megapixels. Exact output dimensions depend on this tier and the image aspect ratio.Default: '1k'
generation_mode'fast' | 'balanced' | 'quality'Sets the generation quality level. 'quality' produces the most detailed and
realistic output but takes longer to process and costs more credits. 'fast'
prioritizes speed and lower cost. If omitted, FASHN selects generation_mode
automatically. For product-to-model, omitted generation_mode is currently
billed as 'fast' at 1k and as 'balanced' at 2k or 4k.
background_referenceimage URL | base64Background image used as the backdrop for generation. Ensures location consistency across generations. If a person appears in the image, they will be ignored and only the background will be used.When provided alongside image_prompt, image_prompt governs the model's appearance, pose, and styling, while background_reference anchors the scene.Default: None
seedintegerSeed for reproducible results. Must be between 0 and 2^32-1.Default: 42
num_imagesintegerNumber of images to generate in a single request. Must be between 1 and 4. Additional images consume more compute (and credits) and can increase processing time.Default: 1
output_formatstringOutput image format.
"png" - PNG format, original quality
"jpeg" - JPEG format, smaller file size
Default: "png"
return_base64booleanWhen set to true, the API will return the generated image as a base64-encoded string instead of a CDN URL. The base64 string will be prefixed data:image/png;base64,....This option offers enhanced privacy as user-generated outputs are not stored on our servers when return_base64 is enabled.Default: false
model_imageDeprecatedimage URL | base64URL or base64 encoded image of the person to wear the product. When provided, the endpoint adds the product to the existing person instead of generating a new one.This parameter is deprecated. It cannot be combined with image_prompt, background_reference, or face_reference, which are designed to compose freely with each other but conflict with a fixed model image. For combining a product image with a specific person, use the tryon-max endpoint instead.Default: None
Credit Cost
generation_mode \ resolution1k2k4kfast123balanced234quality345
Additional pricing rules:

face_reference adds +3 credits per output image.
num_images multiplies the total cost by the number of outputs requested.
If generation_mode is omitted, automatic pricing applies.

Processing Time
Processing time depends on both resolution and generation_mode. The fastest configuration (fast + 1k) typically completes in under 20 seconds, while the most intensive (quality + 4k) can take up to 120 seconds. Actual latency may vary with current server load.
Response Polling
After submitting your request, poll the status endpoint using the returned prediction ID. See API Fundamentals for complete polling details.
Successful Response
When your product-to-model generation completes successfully, the status endpoint will return:
{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "status": "completed",
  "output": [
    "https://cdn.fashn.ai/123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1/output_0.png"
  ],
  "error": null
}
Runtime Errors
Runtime errors for Product to Model use the shared set in Error Handling.
Related Guides

Prompting in FASHN ↗ - Learn how to write effective prompts for best results
Image Preprocessing Best Practices - Optimize your input images for better results
Data Retention & Privacy - Understand how FASHN handles your data


Face to ModelThe Face to Model endpoint transforms face images into try-on ready upper-body avatars. It converts cropped headshots or selfies into full upper-body representations that can be used in virtual try-on applications when full-body photos are not available, while preserving facial identity.

Model Specifications
Model Name: face-to-model
Lifecycle: experimental
Processing Time: 20s–120s (see below)
Output Formats: PNG, JPEG
Delivery Methods: URL or Base64 encoding
Credits: 1-5 per output image depending on resolution and generation_mode

Request
Transform face images into professional model shots by submitting the face image to the universal /v1/run endpoint:
POSThttps://api.fashn.ai/v1/runRequest ExamplescURLJavaScriptPythoncurl -X POST https://api.fashn.ai/v1/run \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer YOUR_API_KEY" \
     -d '{
           "model_name": "face-to-model",
           "inputs": {
             "face_image": "http://example.com/path/to/headshot.jpg",
             "output_format": "jpeg"
           }
         }'Response200Returns a prediction ID for status polling:Response{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "error": null
}
Request Parameters
face_imageRequiredimage URL | base64URL or base64 encoded image of the face to transform into an upper-body
avatar. The AI will analyze facial features, hair, and skin tone to create a
representation suitable for virtual try-on applications.
promptstringOptional styling or body shape guidance for the avatar representation. Examples: "athletic build", "curvy figure", "slender frame".If you don't provide a prompt, the body shape will be inferred from the face image.
aspect_ratiostringDesired aspect ratio for the output image. Only vertical ratios are supported. Images will always be extended downward to fit the aspect ratio.Supported ratios: "1:1", "4:5", "3:4", "2:3", "9:16".Default: 2:3
resolution'1k' | '2k' | '4k'Output resolution tier. '1k' produces ~1 megapixel output, '2k' ~4 megapixels, and '4k' ~16 megapixels. Exact output dimensions depend on this tier and the image aspect ratio.Default: '1k'
generation_mode'fast' | 'balanced' | 'quality'Sets the generation quality level. 'quality' produces the most detailed and
realistic output but takes longer to process and costs more credits. 'fast'
prioritizes speed and lower cost. If omitted, FASHN selects generation_mode
automatically. For face-to-model, omitted generation_mode is currently
billed as 'fast' at 1k and as 'balanced' at 2k or 4k.
seedintegerSets random operations to a fixed state. Use the same seed to reproduce results with the same inputs, or different seed to force different results.Default: 42
num_imagesintegerNumber of images to generate in a single request. Must be between 1 and 4. Additional images consume more compute (and credits) and can increase processing time.Default: 1
output_formatstringSpecifies the output image format.
"png" - PNG format, original quality
"jpeg" - JPEG format, smaller file size
Default: "jpeg"
return_base64booleanWhen set to true, the API will return the generated image as a base64-encoded string instead of a CDN URL. The base64 string will be prefixed data:image/png;base64,....This option offers enhanced privacy as user-generated outputs are not stored on our servers when return_base64 is enabled.Default: false
Credit Cost
generation_mode \ resolution1k2k4kfast123balanced234quality345
Additional pricing rules:

num_images multiplies the total cost by the number of outputs requested.
If generation_mode is omitted, automatic pricing applies.

Processing Time
Processing time depends on both resolution and generation_mode. The fastest configuration (fast + 1k) typically completes in under 20 seconds, while the most intensive (quality + 4k) can take up to 120 seconds. Actual latency may vary with current server load.
Response Polling
After submitting your request, poll the status endpoint using the returned prediction ID. See API Fundamentals for complete polling details.
Successful Response
When your face-to-model avatar creation completes successfully, the status endpoint will return:
{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "status": "completed",
  "output": {
    "images": [
      "https://cdn.fashn.ai/123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1/output_0.png"
    ]
  },
  "error": null
}
The images array contains URLs to your upper-body avatars with preserved facial identity, ready for virtual try-on applications.
Runtime Errors
Runtime errors for Face to Model use the shared set in Error Handling.
Related Guides

Image Preprocessing Best Practices - Optimize your input images for better results
Data Retention & Privacy - Understand how FASHN handles your data


Model CreateModel Create enables you to generate realistic fashion models with simple, intuitive prompts or reference images.

Model Specifications
Model Name: model-create
Lifecycle: experimental
Processing Time: 20s–120s (see below)
Output Formats: PNG, JPEG
Delivery Methods: URL or Base64 encoding
Credits: 1-5 per output image depending on resolution and generation_mode (+3 per output image with face_reference)

Request
Generate fashion models by submitting your prompt and optional reference assets to the universal /v1/run endpoint:
POSThttps://api.fashn.ai/v1/runRequest ExamplescURLJavaScriptPythoncurl -X POST https://api.fashn.ai/v1/run \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer YOUR_API_KEY" \
     -d '{
           "model_name": "model-create",
           "inputs": {
             "prompt": "Full body shot, woman wearing a white t-shirt and dark blue biker shorts"
           }
         }'Response200Returns a prediction ID for status polling:Response{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "error": null
}
Request Parameters
Required Parameters
promptRequiredstringPrompt for the model image generation. Describes the desired fashion model,
clothing, pose, and scene.
Optional Parameters
image_referenceimage URL | base64Optional image to guide composition and pose. The AI won't copy the exact details from the image, but will use it as inspiration.You can control whether to copy just the pose or the exact silhouette using the prompt parameter with natural language.Base64 FormatBase64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>).
aspect_ratiostringDefines the width-to-height ratio of the generated image.When image_reference is provided, the output inherits the reference image's aspect ratio. Supply an explicit aspect_ratio to override that default.Supported ratios: "21:9", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "4:5", "5:4", "1:1".Default: 1:1
face_referenceimage URL | base64Optional portrait image that locks in a specific identity across generations.
When face_reference is used, output resolution is capped at 2K regardless of the requested resolution tier.
Adds 3 credits per image.
Adds roughly 20-30 seconds of processing time.
Use this to achieve model consistency across generations without training a custom checkpoint.
face_reference_mode'match_base' | 'match_reference'Controls how the provided face_reference shapes pose and expression.-match_base prioritizes the prompt and base generation, keeping the original pose while adapting the reference face to those instructions.-match_reference aligns the generated model closely with the reference face’s
pose, gaze, and expression for maximum resemblance.Default: match_reference
resolution'1k' | '2k' | '4k'Output resolution tier. '1k' produces ~1 megapixel output, '2k' ~4 megapixels, and '4k' ~16 megapixels. Exact output dimensions depend on this tier and the image aspect ratio.Default: '1k'
generation_mode'fast' | 'balanced' | 'quality'Sets the generation quality level. 'quality' produces the most detailed and
realistic output but takes longer to process and costs more credits. 'fast'
prioritizes speed and lower cost. If omitted, FASHN selects generation_mode
automatically. For model-create, omitted generation_mode is currently
billed as 'fast' at 1k and as 'balanced' at 2k or 4k.
seedintegerSets random operations to a fixed state. Use the same seed to reproduce results with the same inputs, or different seed to force different results.Default: 42
Range: 0 to 2^32 - 1
num_imagesintegerNumber of images to generate per request. Must be between 1 and 4. Additional images consume more compute (and credits) and can increase processing time.Default: 1
output_format'png' | 'jpeg'Specifies the desired output image format.-png: Delivers the highest quality image, ideal for use cases such as content creation where quality is paramount.-jpeg: Provides a faster response with a slightly compressed image, more
suitable for real-time applications.Default: png
return_base64booleanWhen set to true, the API returns the generated image as a base64 string instead of a CDN URL. The base64 output is prefixed according to output_format (e.g., data:image/png;base64,... or data:image/jpeg;base64,...).Enables stricter privacy because images are never uploaded to our CDN and are only available for 60 minutes after completion.Default: false
Credit Cost
generation_mode \ resolution1k2k4kfast123balanced234quality345
Additional pricing rules:

face_reference adds +3 credits per output image.
num_images multiplies the total cost by the number of outputs requested.
If generation_mode is omitted, automatic pricing applies.

Processing Time
Processing time depends on both resolution and generation_mode. The fastest configuration (fast + 1k) typically completes in under 20 seconds, while the most intensive (quality + 4k) can take up to 120 seconds. Actual latency may vary with current server load.
Response Polling
After submitting your request, poll the status endpoint using the returned prediction ID. See API Fundamentals for complete polling details.
Successful Response
When your model creation completes successfully, the status endpoint will return:
{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "status": "completed",
  "output": [
    "https://cdn.fashn.ai/123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1/output_0.png"
  ],
  "error": null
}
The output array contains URLs to your generated fashion model images based on your prompt and optional reference parameters.
Runtime Errors
Runtime errors for Model Create use the shared set in Error Handling.
Related Guides
For detailed implementation guidance and best practices:

Image Preprocessing Best Practices - Optimize your reference images


Model SwapModel Swap enables you to change the identity of fashion models in existing images while preserving clothing and outfit details exactly as they appear. Transform skin tone, facial features, and hair while maintaining the garments, pose, and styling perfectly intact.
For consistent photoshoots, an optional premium face reference capability lets you swap to a specific identity and achieve repeatable, campaign‑ready results across sets.

Model Specifications
Model Name: model-swap
Lifecycle: experimental
Processing Time: 20s–120s (see below)
Credits: 1-5 per output image depending on resolution and generation_mode (+3 per output image with face_reference)

Request
Transform fashion model identity while preserving clothing by submitting the source image (and optionally a face reference) to the universal /v1/run endpoint:
POSThttps://api.fashn.ai/v1/runRequest ExamplescURLJavaScriptPythoncurl -X POST https://api.fashn.ai/v1/run \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer YOUR_API_KEY" \
     -d '{
           "model_name": "model-swap",
           "inputs": {
             "model_image": "https://example.com/fashion-model.jpg",
             "prompt": "Asian woman with blue hair"
           }
         }'Response200Returns a prediction ID for status polling:Response{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "error": null
}
Request Parameters
Required Parameters
model_imageRequiredimage URL | base64Source fashion model image containing the clothing and pose to preserve. The model's identity (face, skin tone, hair) will be transformed while keeping the outfit exactly as shown.Base64 FormatBase64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)
Optional Parameters
promptstringText guidance for identity or scene adjustments. If omitted, the system generates an appropriate prompt based on image analysis.Default: Empty string (automatic prompt)
face_referenceimage URL | base64Optional reference image to guide identity. When provided, the pipeline refines the model swap so both the body and face are aligned with the reference.Default: None
face_reference_mode'match_base' | 'match_reference'Additional fine control for identity guidance when face_reference is provided.-match_base keeps the original photo’s head angle, gaze, and expression while applying the reference identity.-match_reference favors the reference face’s pose and expression for maximum
resemblance.Default: match_reference
resolution'1k' | '2k' | '4k'Output resolution tier. '1k' produces ~1 megapixel output, '2k' ~4 megapixels, and '4k' ~16 megapixels. Exact output dimensions depend on this tier and the image aspect ratio.Default: '1k'
generation_mode'fast' | 'balanced' | 'quality'Sets the generation quality level. 'quality' produces the most detailed and
realistic output but takes longer to process and costs more credits. 'fast'
prioritizes speed and lower cost. If omitted, FASHN selects generation_mode
automatically. For model-swap, omitted generation_mode is currently billed
as 'fast' at 1k and as 'balanced' at 2k or 4k.
seedintegerSets random operations to a fixed state. Use the same seed to reproduce results with the same inputs, or different seed to force different results.Default: 42
Range: 0 to 2^32 - 1
num_imagesintegerNumber of images to generate per request. Must be between 1 and 4.Default: 1
output_format'png' | 'jpeg'Specifies the desired output image format.-png: Delivers the highest quality image, ideal for use cases such as content creation where quality is paramount.-jpeg: Provides a faster response with a slightly compressed image, more
suitable for real-time applications.Default: png
return_base64booleanWhen set to true, the API will return the generated image as a base64-encoded string instead of a CDN URL. The base64 string will be prefixed according to the output_format (e.g., data:image/png;base64,... or data:image/jpeg;base64,...).This option offers enhanced privacy as user-generated outputs are not stored on our servers when return_base64 is enabled.Default: false
Credit Cost
generation_mode \ resolution1k2k4kfast123balanced234quality345
Additional pricing rules:

face_reference adds +3 credits per output image.
num_images multiplies the total cost by the number of outputs requested.
If generation_mode is omitted, automatic pricing applies.

Processing Time
Processing time depends on both resolution and generation_mode. The fastest configuration (fast + 1k) typically completes in under 20 seconds, while the most intensive (quality + 4k) can take up to 120 seconds. Actual latency may vary with current server load.
Response Polling
After submitting your request, poll the status endpoint using the returned prediction ID. See API Fundamentals for complete polling details.
Successful Response
When your model swap completes successfully, the status endpoint will return:
{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "status": "completed",
  "output": [
    "https://cdn.fashn.ai/123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1/output_0.png"
  ],
  "error": null
}
The output array contains URLs to your processed images with the transformed model identity while preserving the original clothing and styling.
Runtime Errors
Runtime errors for Model Swap use the shared set in Error Handling.
Related Guides
For detailed implementation guidance and best practices:

Prompting in FASHN ↗ - Learn how to write effective prompts for best results
Image Preprocessing Best Practices - Optimize your source images for identity transformation


EditEdit is a versatile post-processing endpoint that preserves identity and product fidelity while executing freeform instructions. Use it to change poses or viewpoints for extra angles, style a shot with accessories or lighting, or fix issues in Product to Model or Model Swap outputs.

Model Specifications
Model Name: edit
Lifecycle: experimental
Processing Time: 20s–120s (see below)
Credits: 1-5 per output image depending on resolution and generation_mode

Request
Refine images by submitting the source image and edit instructions to the universal /v1/run endpoint:
POSThttps://api.fashn.ai/v1/runRequest ExamplescURLJavaScriptPythoncurl -X POST https://api.fashn.ai/v1/run \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer YOUR_API_KEY" \
     -d '{
           "model_name": "edit",
           "inputs": {
             "image": "https://example.com/model.jpg",
             "prompt": "turn the model slightly to the left, add a black leather crossbody bag, soft daylight studio lighting"
           }
         }'Response200Returns a prediction ID for status polling:Response{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "error": null
}
Request Parameters
imageRequiredimage URL | base64Source image to refine. The model preserves subject identity and product
details while applying the requested edits.
promptRequiredstringFreeform instructions for the edits you want to apply, ideal for pose or view
adjustments, styling (accessories, lighting, environment), or small fixes to
existing outputs.
maskimage URL | base64Optional mask image that guides the edit toward specific regions. White pixels (255) mark areas to prioritize, black pixels (0) mark areas to preserve. The model may still adjust nearby pixels to keep the image coherent, so treat the mask as a strong hint rather than strict inpainting.The mask must have the same dimensions as the source image.
image_contextimage URL | base64Optional reference image that provides visual context to guide the edit. Use
this when the desired result cannot be fully described in words alone.
Examples include a specific background scene, complex pose, or texture
pattern.
resolution'1k' | '2k' | '4k'Output resolution tier. '1k' produces ~1 megapixel output, '2k' ~4 megapixels, and '4k' ~16 megapixels. Exact output dimensions depend on this tier and the image aspect ratio.Default: '1k'
generation_mode'fast' | 'balanced' | 'quality'Sets the generation quality level. 'quality' produces the most detailed and
realistic output but takes longer to process and costs more credits. 'fast'
prioritizes speed and lower cost. If omitted, FASHN selects generation_mode
automatically. For edit, omitted generation_mode is currently billed as
'fast' at 1k and as 'balanced' at 2k or 4k.
seedintegerSets random operations to a fixed state. Use the same seed to reproduce results with the same inputs, or different seed to force different results.Default: 42
Range: 0 to 2^32 - 1
num_imagesintegerNumber of images to generate in a single request. Must be between 1 and 4. Additional images consume more compute (and credits) and can increase processing time.Default: 1
output_format'png' | 'jpeg'Specifies the output image format.-png: Delivers the highest quality image, ideal for use cases such as content creation where quality is paramount.-jpeg: Provides a faster response with a slightly compressed image, more
suitable for real-time applications.Default: png
return_base64booleanWhen set to true, the API will return the generated image as a base64-encoded string instead of a CDN URL. The base64 string will be prefixed according to the output_format (e.g., data:image/png;base64,... or data:image/jpeg;base64,...).This option offers enhanced privacy as user-generated outputs are not stored on our servers when return_base64 is enabled.Default: false
Credit Cost
generation_mode \ resolution1k2k4kfast123balanced234quality345
Additional pricing rules:

num_images multiplies the total cost by the number of outputs requested.
If generation_mode is omitted, automatic pricing applies.

Processing Time
Processing time depends on both resolution and generation_mode. The fastest configuration (fast + 1k) typically completes in under 20 seconds, while the most intensive (quality + 4k) can take up to 120 seconds. Actual latency may vary with current server load.
Response Polling
After submitting your request, poll the status endpoint using the returned prediction ID. See API Fundamentals for complete polling details.
Successful Response
When your edit completes successfully, the status endpoint will return:
{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "status": "completed",
  "output": [
    "https://cdn.fashn.ai/123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1/output_0.png"
  ],
  "error": null
}
The output array contains URLs to your edited images, which follow your instructions while preserving product and subject fidelity.
Runtime Errors
Edit shares the common runtime errors in Error Handling.
Related Guides
For detailed implementation guidance and best practices:

Prompting in FASHN ↗ - Learn how to write effective prompts for best results
Image Preprocessing Best Practices - Optimize your source images for editing


ReframeReframe intelligently adjusts image aspect ratios using AI-powered content analysis. The model analyzes your image and automatically decides whether to expand (outpaint/zoom-out) or crop (zoom-in) to reach the target aspect ratio while preserving important content.

Model Specifications
Model Name: reframe
Lifecycle: experimental
Processing Time: 20s–120s (see below)
Credits: 1-5 per output image depending on resolution and generation_mode

Request
Reframe images by submitting the source image and target aspect ratio to the universal /v1/run endpoint:
POSThttps://api.fashn.ai/v1/runRequest ExamplescURLJavaScriptPythoncurl -X POST https://api.fashn.ai/v1/run \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer YOUR_API_KEY" \
     -d '{
           "model_name": "reframe",
           "inputs": {
             "image": "https://example.com/portrait.jpg",
             "aspect_ratio": "16:9"
           }
         }'Response200Returns a prediction ID for status polling:Response{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "error": null
}
Request Parameters
imageRequiredimage URL | base64Source image to reframe to a new aspect ratio. The AI analyzes the image content and intelligently decides whether to expand or crop based on subject position, content density, and edge details.Base64 FormatBase64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)
aspect_ratioRequired'21:9' | '1:1' | '4:3' | '3:2' | '2:3' | '5:4' | '4:5' | '3:4' | '16:9' | '9:16'Target aspect ratio for the reframed image. The AI determines whether expansion or cropping is more appropriate based on the current image content and dimensions.Supported Aspect Ratios
resolution'1k' | '2k' | '4k'Output resolution tier. '1k' produces ~1 megapixel output, '2k' ~4 megapixels, and '4k' ~16 megapixels. Exact output dimensions depend on this tier and the image aspect ratio.Default: '1k'
generation_mode'fast' | 'balanced' | 'quality'Sets the generation quality level. 'quality' produces the most detailed and
realistic output but takes longer to process and costs more credits. 'fast'
prioritizes speed and lower cost. If omitted, FASHN selects generation_mode
automatically. For reframe, omitted generation_mode is currently billed as
'fast' at 1k and as 'balanced' at 2k or 4k.
num_imagesintegerNumber of images to generate in a single run. Image generation has a random element, so generating multiple images increases the chances of getting a good result.Default: 1
Range: 1 to 4
seedintegerSets random operations to a fixed state. Use the same seed to reproduce results with the same inputs, or different seed to force different results.Default: 42
Range: 0 to 2^32 - 1
output_format'png' | 'jpeg'Specifies the output image format.-png: Delivers the highest quality image, ideal for use cases such as content creation where quality is paramount.-jpeg: Provides a faster response with a slightly compressed image, more
suitable for real-time applications.Default: png
return_base64booleanWhen set to true, the API will return the generated image as a base64-encoded string instead of a CDN URL. The base64 string will be prefixed according to the output_format (e.g., data:image/png;base64,... or data:image/jpeg;base64,...).This option offers enhanced privacy as user-generated outputs are not stored on our servers when return_base64 is enabled.Default: false
Credit Cost
generation_mode \ resolution1k2k4kfast123balanced234quality345
Additional pricing rules:

num_images multiplies the total cost by the number of outputs requested.
If generation_mode is omitted, automatic pricing applies.

Processing Time
Processing time depends on both resolution and generation_mode. The fastest configuration (fast + 1k) typically completes in under 20 seconds, while the most intensive (quality + 4k) can take up to 120 seconds. Actual latency may vary with current server load.
Response Polling
After submitting your request, poll the status endpoint using the returned prediction ID. See API Fundamentals for complete polling details.
Successful Response
When your reframe operation completes successfully, the status endpoint will return:
{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "status": "completed",
  "output": [
    "https://cdn.fashn.ai/123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1/output_0.png"
  ],
  "error": null
}
The output array contains URLs to your reframed images, adjusted to the target aspect ratio.
Runtime Errors
Reframe shares the common runtime errors in Error Handling.
In addition, Reframe may return:
ErrorDescriptionInputValidationErrorImage already matches target aspect ratio
Related Guides
For detailed implementation guidance and best practices:

Image Preprocessing Best Practices - Optimize your source images for reframing operations


Image to VideoImage to Video turns a single image into a short motion clip, with tasteful camera work and model movements tailored for fashion. Provide an image and optional instructions to produce engaging 5–10 second videos at up to 1080p.

Model Specifications
Model Name: image-to-video
Lifecycle: experimental
Duration Options: 5s, 10s
Resolutions: 480p, 720p, 1080p
Output: MP4 video URLs
Credits: 1-12 per output video depending on resolution and duration

Request
Animate a single image into a short video via the universal /v1/run endpoint:
POSThttps://api.fashn.ai/v1/runRequest ExamplescURLJavaScriptPythoncurl -X POST https://api.fashn.ai/v1/run \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer YOUR_API_KEY" \
     -d '{
           "model_name": "image-to-video",
           "inputs": {
             "image": "https://example.com/photo.jpg",
             "duration": 5,
             "resolution": "1080p"
           }
         }'Response200Returns a prediction ID for status polling:Response{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "error": null
}
Request Parameters
Required Parameters
imageRequiredimage URL | base64Source image to animate into a short video.Base64 FormatBase64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)
Optional Parameters
promptstringOptional motion guidance. Detailed prompting is not recommended because motion is difficult to control precisely. For the best results, leave this field empty and allow the system to plan motion automatically. If you choose to include guidance, keep it short and concrete, for example: "raising hand to touch face".Default: empty string (automatic motion)
duration5 | 10Duration of the generated video in seconds.Default: 5
resolution480p | 720p | 1080pTarget video resolution used by the internal video engine.Default: 1080p
end_imageimage URL | base64Optional image to use as the final frame of the generated video. When provided, the video smoothly transitions from image (start frame) to end_image (end frame) over the clip duration.Resolution ConstraintOnly supported with resolution: "1080p". Other resolutions are rejected with a validation error.Base64 FormatBase64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)
Credit Cost
duration \ resolution480p720p1080p5s13610s2612
Response Polling
After submitting your request, poll the status endpoint using the returned prediction ID. See API Fundamentals for complete polling details.
Successful Response
When your video completes successfully, the status endpoint will return:
{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "status": "completed",
  "output": [
    "https://cdn.fashn.ai/123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1/output_0.mp4"
  ],
  "error": null
}
The output array contains URLs to your generated MP4 video(s). The number of items reflects the workflow’s output (currently 1 video per request).
Runtime Errors
Runtime errors for Image to Video use the shared set in Error Handling.
Related Guides

API Fundamentals - Authentication, requests, and status polling
Data Retention & Privacy - Understand how FASHN handles your data
Image Preprocessing Best Practices - Improve input quality for better results


Background RemoveBackground Remove enables you to cleanly remove backgrounds from images, creating transparent PNG cutouts of foreground subjects. This classic background removal tool automatically detects and preserves the main subject while eliminating the background.

Model Specifications
Model Name: background-remove
Lifecycle: experimental
Processing Time: 1-3 seconds
Supported Resolution: up to 4MP
Credits: 1 credit per output image

Request
Remove image backgrounds by submitting the source image to the universal /v1/run endpoint:
POSThttps://api.fashn.ai/v1/runRequest ExamplescURLJavaScriptPythoncurl -X POST https://api.fashn.ai/v1/run \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer YOUR_API_KEY" \
     -d '{
           "model_name": "background-remove",
           "inputs": {
             "image": "https://example.com/portrait.jpg"
           }
         }'Response200Returns a prediction ID for status polling:Response{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "error": null
}
Request Parameters
Required Parameters
imageRequiredimage URL | base64Source image to remove the background from. The AI will automatically detect the main subject and create a clean cutout with transparent background.Base64 FormatBase64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)
Optional Parameters
return_base64booleanWhen set to true, the API will return the generated image as a base64-encoded string instead of a CDN URL. The base64 string will be prefixed data:image/png;base64,....This option offers enhanced privacy as user-generated outputs are not stored on our servers when return_base64 is enabled.Default: false
Response Polling
After submitting your request, poll the status endpoint using the returned prediction ID. See API Fundamentals for complete polling details.
Successful Response
When your background removal completes successfully, the status endpoint will return:
{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "status": "completed",
  "output": [
    "https://cdn.fashn.ai/123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1/output_0.png"
  ],
  "error": null
}
The output array contains either URLs or, if return_base64 is set to true, base64-encoded strings of your processed PNG images with backgrounds removed.
Runtime Errors
Runtime errors for Background Remove use the shared set in Error Handling.
Related Guides
For detailed implementation guidance and best practices:

Image Preprocessing Best Practices - Optimize your source images for background removal


FASHN Virtual Try-On v1.6Virtual Try-On v1.6 is a fast, lightweight virtual try-on model optimized for real-time e-commerce integrations. It delivers reliable results in 5-8 seconds at 1 credit per image.

Need studio-grade realism?Try-On Max is our recommended virtual try-on endpoint, offering higher resolution (up to 4K), broader item support (shoes, hats, jewelry, bags), and prompt-based customization. Use v1.6 when speed and cost are your primary concerns.

Model Specifications
Model Name: tryon-v1.6
Lifecycle: stable
Processing Resolution: 864×1296 pixels
Processing Time:

Performance: 5 seconds
Balanced: 8 seconds
Quality: 12–17 seconds (variable depending on input resolution)


Credits: 1 credit per output image

Request
Generate a virtual try-on by submitting your model and garment images to the universal /v1/run endpoint:
POSThttps://api.fashn.ai/v1/runRequest ExamplescURLJavaScriptPythoncurl -X POST https://api.fashn.ai/v1/run \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer YOUR_API_KEY" \
     -d '{
           "model_name": "tryon-v1.6",
           "inputs": {
             "model_image": "http://example.com/path/to/model.jpg",
             "garment_image": "http://example.com/path/to/garment.jpg"
           }
         }'Response200Returns a prediction ID for status polling:Response{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "error": null
}
Request Parameters
Required Parameters
model_imageRequiredimage URL | base64Primary image of the person on whom the virtual try-on will be performed.
garment_imageRequiredimage URL | base64Reference image of the clothing item to be tried on the model_image.
Base64 FormatBase64 images must include the proper prefix (e.g., data:image/jpg;base64,<YOUR_BASE64>)
Optional Parameters
category'auto' | 'tops' | 'bottoms' | 'one-pieces'Use auto to enable automatic classification of the garment type. For flat-lay or ghost mannequin images, the system detects the garment type automatically. For on-model images, full-body shots default to a full outfit swap. For focused shots (upper or lower body), the system selects the most likely garment type (tops or bottoms).Default: auto
segmentation_freebooleanDirect garment fitting without clothing segmentation, enabling bulkier garment try-ons with improved preservation of body shape and skin texture. Set to false if original garments are not removed properly.Default: true
moderation_level'conservative' | 'permissive' | 'none'Sets the content moderation level for garment images.-conservative enforces stricter modesty standards suitable for culturally sensitive contexts. Blocks underwear, swimwear, and revealing outfits.-permissive allows swimwear, underwear, and revealing garments, while still
blocking explicit nudity.-none disables all content moderationDefault: permissive
Responsible Use NoticeThis technology is designed for ethical virtual try-on applications. Misuse—such as generating inappropriate imagery without consent—violates our Terms of Service ↗.Setting moderation_level: none does not remove your responsibility for ethical and lawful use. Violations may result in service denial.
garment_photo_typeauto | flat-lay | modelSpecifies the type of garment photo to optimize internal parameters for better performance. 'model' is for photos of garments on a model, 'flat-lay' is for flat-lay or ghost mannequin images, and 'auto' attempts to automatically detect the photo type.Default: auto
modeperformance | balanced | qualitySpecifies the mode of operation.-performance mode is faster but may compromise quality-balanced mode is a perfect middle ground between speed and quality-quality mode is slower, but delivers the highest quality results.Default: balanced
seedintSets random operations to a fixed state. Use the same seed to reproduce
results with the same inputs, or different seed to force different results.Default: 42Min: 0 Max: 2^32 - 1
num_samplesintNumber of images to generate in a single run. Image generation has a random
element in it, so trying multiple images at once increases the chances of
getting a good result.Default: 1 Min: 1 Max: 4
output_format'png' | 'jpeg'Specifies the desired output image format.-png: Delivers the highest quality image, ideal for use cases such as content creation where quality is paramount.-jpeg: Provides a faster response with a slightly compressed image, more
suitable for real-time applications like consumer virtual try-on experiences.Default: png
return_base64booleanWhen set to true, the API will return the generated image as a base64-encoded string instead of a CDN URL. The base64 string will be prefixed according to the output_format (e.g., data:image/png;base64,... or data:image/jpeg;base64,...).This option offers enhanced privacy as user-generated outputs are not stored on our servers when return_base64 is enabled.Default: false
Response Polling
After submitting your request, poll the status endpoint using the returned prediction ID. See API Fundamentals for complete polling details.
Successful Response
When your virtual try-on completes successfully, the status endpoint will return:
{
  "id": "123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1",
  "status": "completed",
  "output": [
    "https://cdn.fashn.ai/123a87r9-4129-4bb3-be18-9c9fb5bd7fc1-u1/output_0.png"
  ],
  "error": null
}
The output array contains URLs to your generated try-on images showing the model wearing the specified garment. The number of images depends on the num_samples parameter (default: 1).
Runtime Errors
Try-On shares the common runtime errors in Error Handling. Additional endpoint-specific errors:
NameCauseSolutionPoseErrorThe pipeline was unable to detect a body pose in either the model image or the garment image (when garment_photo_type: "model").Improve model or garment photo quality following the model photo guidelines ↗.
Related Guides
For detailed implementation guidance and best practices specific to Virtual Try-On:

Try-On Parameters Guide - Detailed parameter optimization for try-on models
Python Quickstart Guide - Complete Python implementation examples
JavaScript Quickstart Guide - Frontend integration patterns
Image Preprocessing Best Practices - Optimize your input images for better results
Data Retention & Privacy - Understand how FASHN handles your data




Credits BalanceThe Credits endpoint allows you to retrieve your current FASHN API credits balance. The response includes your total credits, API subscription credits (if you have an active subscription), and any additional on-demand credits you've purchased.
Credit Usage
Subscription Credits: Included with your monthly API plan
On-Demand Credits: Additional credits purchased separately
Total Credits: Combined balance of subscription + on-demand credits

Request
Check your current credits balance by making a GET request to the credits endpoint:
GEThttps://api.fashn.ai/v1/creditsCall this endpoint whenever you need to know how many credits you have remaining.Request ExamplescURLJavaScriptPythoncurl -X GET https://api.fashn.ai/v1/credits \
     -H "Authorization: Bearer YOUR_API_KEY"Response200Example response payloadResponse{
  "credits": {
    "total": 234,
    "subscription": 100,
    "on_demand": 134
  }
}
Response Fields
creditsobjectContainer object for all credit information.totalintegerYour total available credits (subscription + on-demand credits combined).subscriptionintegerCredits included with your current API subscription plan. These credits reset monthly based on your billing cycle.on_demandintegerAdditional credits purchased separately from your subscription. These credits are consumed after subscription credits.
Rate Limits
The credits endpoint has its own specific rate limit:
EndpointLimit/v1/credits30 requests per 10 seconds
For other endpoints, see the default rate limits in API Fundamentals.



Try-On ParametersModel Image
image URL | base64
model_image is the primary image of the person on whom the virtual try-on will be performed. You can provide the image as a publicly accessible URL or a base64 string.

💡 Mode TipsUse mode: performance to quickly test and find model and garment combinations that work well. Once you're satisfied, switch to mode: quality to produce a final high-quality result ready for publishing.
*Tips for selecting the best model image and avoiding common issues.
Garment Image
image URL | base64
garment_image is the reference image of the clothing item to be tried on the model_image. The image can be provided as a URL or a base64 string. FASHN supports a variety of garment photo types, as shown below:

*Infographic displaying supported garment image types ranked from best (left)
to worst (right).
💡 Image Handling TipsRead Image Preprocessing Best Practices to ensure your requests reach our servers fast and without issues
Common Image IssuesFor Image URLs:
Ensure the URL is publicly accessible without permission restrictions.
Confirm the Content-Type header matches the image format (e.g., image/jpeg, image/png).
For Base64 Images:
Prefix the string with data:image/<format>;base64, where <format> is the image type (e.g., jpeg, png).

Category
'auto' | 'tops' | 'bottoms' | 'one-pieces'
Specifies the type of garment in the garment_image to apply to the model_image. If the garment image includes multiple items (e.g., a t-shirt and jeans), use this parameter to select which item to apply.

auto (recommended): Automatically determines the garment category. For flat-lay or ghost mannequin images, garment type detection is automatic. For on-model images, full-body shots default to swapping the entire outfit, and focused shots (upper or lower body) select the most likely garment type (tops or bottoms).
tops: Specifies garments for the upper body (e.g., shirts, blouses).
bottoms: Specifies garments for the lower body (e.g., pants, skirts).
one-pieces: Specifies single-piece garments or full-body garments (e.g., dresses, jumpsuits).


*Examples of try-on results for categories 'tops', 'bottoms', and
'one-pieces'.
Mode
performance | balanced | quality
The mode parameter determines the trade-off between processing speed and output quality:

performance: Fastest, with reduced image quality.
balanced: A middle ground, offering a good balance between speed and quality.
quality: Slowest, delivering the highest-quality results.


*Side-by-side comparison of results for 'performance', 'balanced', and
'quality' modes.
💡 Mode TipsUse mode: performance to quickly test and find model and garment combinations that work well. Once you're satisfied, switch to mode: quality to produce a final high-quality result ready for publishing.
Garment Photo Type
auto | model | flat-lay
Defines the garment photo type for optimal performance:

model: Photos of garments on a model.
flat-lay: Flat-lay or ghost mannequin images.
auto: Automatically detects the photo type.

flat-lay is required for precise handling of flat-lay images where elements like back neck labels or size tags should be excluded.

*Comparison of 'flat-lay' and 'model' configurations with flat-lay input.
Number of Samples
integer
The num_samples parameter specifies how many images to generate in a single run. By increasing num_samples, you can explore multiple variations simultaneously, improving the likelihood of achieving a desirable result.
Because num_samples introduces diversity within a batch, its practical effect is similar to running multiple trials with different seeds. However, when used with the same seed value, the results remain reproducible for a given num_samples count.
💡 FASHN TipGreat try-on results might just be a seed change away! Conversely, a poor outcome doesn't necessarily mean the input combination won't work—sometimes a simple seed change can make all the difference. Use num_samples: 2-4 along with mode: performance to quickly test multiple seeds and assess how sensitive your inputs are to seed variation.
Seed
integer
Default: 42
Min: 0, Max: 2^32 - 1
The seed parameter is used to set the random operations within the image generation process to a fixed state. This is crucial for reproducibility:

Use the same seed value with the same inputs to consistently generate the exact same try-on result.
Use a different seed value with the same inputs to force different variations of the try-on result. This is useful for exploring different aesthetic outcomes without changing your core model_image or garment_image.

Segmentation Free
boolean
Default: true
When set to true, this parameter enables direct garment fitting without requiring explicit clothing segmentation from the input images. This is particularly useful for achieving a more natural look with bulkier garments, as it aims to preserve the model's body shape and skin texture more effectively. If you observe issues where the original garments are not properly removed in the try-on result, and it is critical for your use-case, set this to false.
Moderation Level
'conservative' | 'permissive' | 'none'
Default: permissive
This parameter allows you to set the content moderation standards for the garment images processed by the API.

conservative: Enforces stricter modesty standards, suitable for culturally sensitive contexts. It is designed to block images of underwear, swimwear, and revealing outfits.
permissive: This is the default setting. It allows images of swimwear, underwear, and revealing garments, but still blocks explicit nudity.
none: Disables all content moderation.

Responsible Use NoticeThis technology is designed for ethical and appropriate virtual try-on applications. Misuse—such as generating inappropriate imagery of individuals without consent—violates our Terms of Service.Setting moderation_level: none does not absolve users from their responsibility to ensure ethical and lawful use. Violations may result in service denial.
Output Format
'png' | 'jpeg'
Default: png
This parameter specifies the desired format of the generated output image:

png: Delivers the highest quality image, making it ideal for use cases where image fidelity is paramount, such as content creation, marketing materials, or high-resolution displays.
jpeg: Provides a faster response time with a slightly compressed image. This format is more suitable for real-time applications like consumer-facing virtual try-on experiences where speed is a priority over uncompressed quality.

Return Base64
boolean
Default: false
When set to true, the API will return the generated image directly as a base64-encoded string in the response body, instead of providing a CDN (Content Delivery Network) URL. The base64 string will be appropriately prefixed according to the chosen output_format (e.g., data:image/png;base64,... or data:image/jpeg;base64,...).
This option offers enhanced privacy, as it means user-generated outputs are not stored on Fashn.ai's servers when return_base64 is enabled, giving users more control over their data.



Try-On Python QuickstartCheck out our SDKWe suggest using our Python SDK rather than the manual method described below. Find more details in the Python SDK documentation.
Below is a minimal Python snippet to demonstrate how to:

POST to the /run endpoint with your input data.
Poll the /status/<ID> endpoint until the prediction is completed.
Retrieve the final results from the "output" field.

For detailed documentation (including advanced parameters and usage), please refer to:

Virtual Try-On v1.6 Documentation
tryon-gradio-app (interactive Gradio UI example)
ComfyUI-FASHN (node-based workflow integration)


Minimal Python Example
This snippet demonstrates a basic request using model and garment image URLs. You can also adapt the code to send local images in Base64 format.
import os
import time
import requests
 
# 1. Set up the API key and base URL
API_KEY = os.getenv("FASHN_API_KEY")
assert API_KEY, "Please set the FASHN_API_KEY environment variable."
BASE_URL = "https://api.fashn.ai/v1"
 
# 2. POST request to /run
input_data = {
    "model_name": "tryon-v1.6",
    "inputs": {
        "model_image": "https://v3.fal.media/files/panda/jRavCEb1D4OpZBjZKxaH7_image_2024-12-08_18-37-27%20Large.jpeg",
        "garment_image": "https://v3.fal.media/files/elephant/qXMQpeM6fVOlg7bZs0dEh_fashn-tshirt-2.png"
    }
}
headers = {"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"}
run_response = requests.post(f"{BASE_URL}/run", json=input_data, headers=headers)
run_data = run_response.json()
prediction_id = run_data.get("id")
print("Prediction started, ID:", prediction_id)
 
# 3. Poll /status/<ID>
while True:
    status_response = requests.get(f"{BASE_URL}/status/{prediction_id}", headers=headers)
    status_data = status_response.json()
 
    if status_data["status"] == "completed":
        print("Prediction completed.")
        # 4. The "output" field contains the final image URLs
        print(status_data["output"])
        break
 
    elif status_data["status"] in ["starting", "in_queue", "processing"]:
        print("Prediction status:", status_data["status"])
        time.sleep(3)
 
    else:
        print("Prediction failed:", status_data.get("error"))
        break



        TroubleshootingUse this guide to identify and resolve common issues when working with the FASHN API.
IssueCauseSolutionAPI results differ from the Web AppThe Web App preprocesses images before sending them to the API, which can lead to different outputs if the same steps are not followed externally.Preprocessing: See Image Preprocessing Best Practices for instructions on replicating the Web App's steps to ensure consistent results.Error Code 500 (Server Error)Commonly caused by an oversized payload (e.g., high-resolution, base64-encoded images), preventing the request from reaching our API.Reduce Payload: See Image Preprocessing Best Practices for recommended steps to avoid large payloads.

Image Preprocessing Best PracticesTo ensure optimal performance and consistent outputs when using the FASHN API, it’s important to preprocess your images. By following these guidelines, you can prevent issues like large payloads or inconsistent results.

Recommended Steps


Resize

Resize images to fit within the maximum resolution supported by the endpoint you're using:

1K endpoints (e.g., Try-On v1.6): max 2000px on the longest edge
4K endpoints (e.g., Product to Model with resolution: '4k'): max 6000px on the longest edge


Maintain aspect ratio to avoid distortion.
Use a quality-preserving downsampling technique (e.g., LANCZOS or INTER_AREA) for best results.



Convert to JPEG

Use a quality setting of around 95 to balance file size and image clarity.



Upload to a CDN

Instead of embedding large base64 strings in your request, upload the processed image to a CDN, and provide the image URL in your API request




Following these best practices helps ensure that your requests reach our servers without issues, leading to faster response times and more consistent results with the FASHN Web App.

