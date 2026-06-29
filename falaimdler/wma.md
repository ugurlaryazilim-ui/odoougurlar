> ## Documentation Index
> Fetch the complete documentation index at: https://fal.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# World Model Accelerator (WMA)

> Experimental fal primitive for interactive world models over a peer-to-peer WebRTC stream between your runners and end users.

<Warning>
  WMA is experimental and the public API may change. First-party client libraries for the browser and native platforms are not yet released.
</Warning>

WMA is fal's interface for running interactive world models over a bidirectional WebRTC stream. A runner on fal accepts a WebRTC session, produces video frames, and ships them back to a browser or native client while the session stays open. fal hosts a bridge at `wma.fal.run` that the client first talks to, but the bridge is only used to establish the connection. Once signaling is done, media flows peer-to-peer between the runner and the client.

There are two ways to build a WMA app depending on how much of the transport layer you want to own:

* **`fal.RealtimeApp`** is the high-level abstraction. You handle frames in Python and fal handles the WebRTC plumbing, session lifecycle, and batching helpers.
* **`fal.App` with a `/start-session` endpoint** is the raw path. You pick your own WebRTC library and run the SDP exchange yourself. The WMA bridge POSTs the client's offer to this endpoint and streams the response back, holding the HTTP connection open for the full lifetime of the session.

## Using `fal.RealtimeApp`

`fal.RealtimeApp` is the fastest way to get a world model running. You define an `on_connect` handler, attach a track to the session, and let fal manage the rest.

```python theme={null}
from typing import TypedDict
from fal.wma import RealtimeApp, BatchedFnTrack


class SessionParams(TypedDict, total=False):
    prompt: str


class InfiniteWorlds(RealtimeApp):
    async def on_connect(self, event_handler, session_params: SessionParams):
        @event_handler.on("track")
        def on_track(track):
            if track.kind != "video":
                return

            event_handler.add_track(
                BatchedFnTrack(
                    track,
                    batch_size=4,
                    fn=lambda frames: do_inference(frames, session_params),
                )
            )
```

### `on_connect(event_handler, session_params)`

`on_connect` is called once per incoming session. It gives you two objects:

* `event_handler` registers track and data-channel callbacks, and attaches outbound tracks back to the peer.
* `session_params` is a mutable dict shared with the client for the duration of the session. See [Session parameters](#session-parameters) below.

Register `track` callbacks on `event_handler` to react to the media the client publishes (for example, the browser webcam). Call `event_handler.add_track(...)` to push a track back to the peer.

### `BatchedFnTrack`

`BatchedFnTrack` is a custom track that buffers frames from a source track, groups them by `batch_size`, and runs your inference function on each batch. The function receives the batch and returns a numpy array or a Pillow image per frame, which WMA then encodes back into the outbound track.

```python theme={null}
BatchedFnTrack(
    source_track,        # the inbound track (e.g. the browser webcam)
    batch_size=4,        # number of frames to group before running fn
    fn=run_inference,    # callable over the batched frames
)
```

Use it when your model is cheaper to run in batches, or when you want the inference cadence decoupled from the inbound frame rate.

### Session parameters

`session_params` is a dynamic dict that mutates over the lifetime of a session. When the client sends a payload like `{"prompt": "..."}` over the data channel, the matching key on `session_params` updates in place. Your inference function can read the latest value on every batch without wiring up a separate queue.

Type it with `TypedDict` to document the fields your app consumes:

```python theme={null}
class SessionParams(TypedDict, total=False):
    prompt: str
    guidance_scale: float
```

Any field that is not sent by the client is simply absent, so treat `session_params` as partial and provide defaults at the call site.

## Using a raw `fal.App` with `/start-session`

If you want to use a specific WebRTC library, own your media pipeline, or drop WMA into an existing `fal.App`, skip `fal.RealtimeApp` and expose a `/start-session` endpoint. WMA treats this endpoint as a streaming endpoint: the first SSE event you yield is your SDP answer, and the HTTP response stays open for the entire session. When your peer connection closes or the client drops, the generator exits and everything tears down together.

This ties the session lifetime directly to the HTTP request lifetime. You don't track sessions in a dict, you don't manage heartbeats, and any cleanup you put in a `finally` block runs when the session ends, whether the peer closed cleanly or the client disconnected.

```python theme={null}
import asyncio
import json

import fal
from pydantic import BaseModel
from fastapi.responses import StreamingResponse


class OfferRequest(BaseModel):
    sdp: str
    type: str
    session_id: str


class GrayscaleTrack:
    """Wraps a video track and converts each frame to grayscale."""

    kind = "video"

    def __init__(self, track):
        self._track = track
        self.id = track.id

    async def recv(self):
        import av
        frame = await self._track.recv()
        img = frame.to_ndarray(format="bgr24")
        import numpy as np
        gray = np.mean(img, axis=2, keepdims=True).astype(np.uint8)
        img_gray = np.broadcast_to(gray, img.shape).copy()
        new_frame = av.VideoFrame.from_ndarray(img_gray, format="bgr24")
        new_frame.pts = frame.pts
        new_frame.time_base = frame.time_base
        return new_frame

    def stop(self):
        self._track.stop()


class GrayscaleDemo(fal.App, name="grayscale-demo"):
    requirements = ["aiortc", "numpy"]

    max_multiplexing = 10
    keepalive = 3600
    machine_type = "M"

    @fal.endpoint("/start-session")
    async def start_session(self, request: OfferRequest) -> StreamingResponse:
        from aiortc import RTCPeerConnection, RTCSessionDescription

        pc = RTCPeerConnection()
        dc = pc.createDataChannel("ping")

        @dc.on("message")
        def on_dc_message(message):
            d = json.loads(message)
            if d.get("type") == "ping":
                dc.send(json.dumps({"type": "pong", "client_ts": d["ts"]}))

        @pc.on("track")
        def on_track(track):
            if track.kind == "video":
                pc.addTrack(GrayscaleTrack(track))

        await pc.setRemoteDescription(
            RTCSessionDescription(sdp=request.sdp, type=request.type)
        )
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        closed = asyncio.Event()

        @pc.on("connectionstatechange")
        def _on_state_change():
            if pc.connectionState in ("closed", "failed", "disconnected"):
                closed.set()

        async def event_stream():
            try:
                # First event: hand the SDP answer back to the client.
                yield "data: " + json.dumps({
                    "sdp": pc.localDescription.sdp,
                    "type": pc.localDescription.type,
                    "session_id": request.session_id,
                }) + "\n\n"

                # Hold the request open while the peer connection is alive.
                # Emit an SSE comment every 15s so intermediaries don't
                # time the connection out.
                while not closed.is_set():
                    try:
                        await asyncio.wait_for(closed.wait(), timeout=15)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                await pc.close()

        return StreamingResponse(event_stream(), media_type="text/event-stream")
```

This path is for power users. You get full control over the ICE/SDP handshake, transceivers, codecs, and any custom data-channel protocol. The `PeerConnection` stays alive in the generator's local scope, so it is not garbage-collected while the stream is active. Put any teardown logic in the `finally` block so it runs whether the session ends naturally or the client drops mid-stream.

## Clients

First-party WMA client libraries for the browser and native platforms are not yet released. Until they ship, you can talk to the bridge directly from any WebRTC-capable client. The bridge lives at `wma.fal.run` and exposes two endpoints.

### `POST /session`

Creates a new WebRTC session. Send the SDP offer from your local `RTCPeerConnection` along with the `app_id` to route to. The bridge forwards the offer to a runner, collects the SDP answer, and returns it as JSON.

Wait for ICE gathering to finish before sending the offer. The bridge does not support trickle ICE, so the offer must contain all ICE candidates.

Request headers:

* `Authorization: Key <your-fal-key>`
* `Content-Type: application/json`

Request body:

```json theme={null}
{
  "app_id": "your-username/your-app",
  "sdp": "<offer SDP from RTCPeerConnection.createOffer()>",
  "type": "offer"
}
```

Response body:

```json theme={null}
{
  "session_id": "<uuid>",
  "sdp": "<answer SDP>",
  "type": "answer"
}
```

Apply the returned SDP as the remote description on your `RTCPeerConnection` and let ICE negotiate. Once the connection is established, media flows peer-to-peer between your client and the runner.

### `POST /session/heartbeat`

Keeps the session alive. The bridge expects a heartbeat at regular intervals. If heartbeats stop arriving, the bridge tears the session down: the runner's `/start-session` generator exits and its `finally` block runs.

Request headers:

* `Authorization: Key <your-fal-key>`
* `Content-Type: application/json`

Request body:

```json theme={null}
{
  "session_id": "<session_id from /session>"
}
```

Send heartbeats every 5 seconds. To end a session, stop sending heartbeats and close the peer connection.

### Reconnection

WMA sessions are not resumable. If the peer connection drops (ICE failure, network change, runner restart), start over: close the old `RTCPeerConnection`, stop any heartbeat timers, build a new peer connection, generate a fresh offer, and call `/session` again. Each call to `/session` spins up a new session on the runner.

### Browser example

The snippet below shows the full client flow in a browser. It connects the camera to a WMA app, receives the processed video back, and keeps the session alive with heartbeats.

```javascript theme={null}
const FAL_KEY = "your-fal-key";
const APP_ID = "your-username/your-app";
const WMA_URL = "https://wma.fal.run";

// 1. Create a peer connection and add the camera.
const pc = new RTCPeerConnection({
  iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
});

const stream = await navigator.mediaDevices.getUserMedia({ video: true });
stream.getTracks().forEach((track) => pc.addTrack(track, stream));

// Receive the processed video from the server.
pc.ontrack = (ev) => {
  remoteVideo.srcObject = ev.streams[0] ?? new MediaStream([ev.track]);
};

// The server may open a data channel for application-level messages
// (e.g. ping/pong latency probes or session parameter updates).
pc.ondatachannel = (ev) => {
  const dc = ev.channel;
  dc.onmessage = (msg) => {
    const data = JSON.parse(msg.data);
    // handle messages from the server
  };
};

// 2. Create the offer and wait for ICE candidates to be gathered.
const offer = await pc.createOffer();
await pc.setLocalDescription(offer);

await new Promise((resolve) => {
  if (pc.iceGatheringState === "complete") return resolve();
  const timeout = setTimeout(resolve, 5000);
  pc.onicegatheringstatechange = () => {
    if (pc.iceGatheringState === "complete") {
      clearTimeout(timeout);
      resolve();
    }
  };
});

// 3. Send the offer to the WMA bridge and apply the answer.
const resp = await fetch(WMA_URL + "/session", {
  method: "POST",
  headers: {
    "Authorization": "Key " + FAL_KEY,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    app_id: APP_ID,
    sdp: pc.localDescription.sdp,
    type: pc.localDescription.type,
  }),
});

const { session_id, sdp, type } = await resp.json();
await pc.setRemoteDescription(new RTCSessionDescription({ sdp, type }));

// 4. Keep the session alive with heartbeats.
const heartbeat = setInterval(() =>
  fetch(WMA_URL + "/session/heartbeat", {
    method: "POST",
    headers: {
      "Authorization": "Key " + FAL_KEY,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ session_id }),
  }),
  5000
);

// 5. Clean up when the connection ends.
function cleanup() {
  clearInterval(heartbeat);
  pc.close();
  stream.getTracks().forEach((t) => t.stop());
}

pc.onconnectionstatechange = () => {
  if (pc.connectionState === "failed" || pc.connectionState === "closed") {
    cleanup();
  }
};
```

## Related

<CardGroup cols={2}>
  <Card title="Deploy a Real-time World Model" icon="globe" href="/examples/video-generation/deploy-realtime-world-model">
    End-to-end example of a live world model running over WebRTC.
  </Card>

  <Card title="Realtime Endpoints" icon="bolt" href="/documentation/development/realtime">
    Lower-level realtime primitives built on fal's WebSocket infrastructure.
  </Card>
</CardGroup>
