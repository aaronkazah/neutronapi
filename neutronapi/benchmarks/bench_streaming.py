"""Ad-hoc NeutronAPI streaming benchmark harness.

Run explicitly; this file is intentionally outside normal test discovery.
"""

from __future__ import annotations

import asyncio
import time

from neutronapi.base import API
from neutronapi.responses import StreamingResponse


class StreamingBenchAPI(API):
    resource = "/bench"
    name = "bench"

    @API.endpoint("/upload", methods=["PUT"], request_body_mode="streamed")
    async def upload(self, scope, receive, send, **kwargs):
        total = 0
        async for chunk in kwargs["stream"]:
            total += len(chunk)
        return await self.response({"bytes": total})

    @API.endpoint("/download", methods=["GET"], response_body_mode="streamed")
    async def download(self, scope, receive, send, **kwargs):
        async def body():
            for _ in range(1024):
                yield b"x" * 1024

        return StreamingResponse(body(), headers={"content-type": "application/octet-stream"})


async def main():
    start = time.perf_counter()
    api = StreamingBenchAPI()
    elapsed = time.perf_counter() - start
    print(f"Initialized {api.name} benchmark API in {elapsed:.6f}s")


if __name__ == "__main__":
    asyncio.run(main())
