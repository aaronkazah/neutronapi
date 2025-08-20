from io import BytesIO
from typing import Callable, Iterable, Optional, Tuple

import gzip

try:
    import brotlicffi as _brotli
    _BROTLI_IMPL = "brotlicffi"
except ImportError:
    try:
        import brotli as _brotli
        _BROTLI_IMPL = "brotli"
    except ImportError:
        _brotli = None
        _BROTLI_IMPL = None

HeaderList = Iterable[Tuple[bytes, bytes]]


class _BrotliStreamCompressor:
    def __init__(self, quality: int = 5, mode: str = "text", lgwin: Optional[int] = None):
        if _BROTLI_IMPL == "brotlicffi":
            # brotlicffi expects integer mode constants
            mode_val = _brotli.MODE_TEXT if mode == "text" else _brotli.MODE_GENERIC
            params = {"quality": quality, "mode": mode_val}
            if lgwin is not None:
                params["lgwin"] = lgwin
            self._c = _brotli.Compressor(**params)
        elif _BROTLI_IMPL == "brotli":
            params = {"quality": quality, "mode": _brotli.MODE_TEXT if mode == "text" else _brotli.MODE_GENERIC}
            if lgwin is not None:
                params["lgwin"] = lgwin
            self._c = _brotli.Compressor(**params)
        else:
            raise ImportError("No brotli implementation available")

    def compress(self, data: bytes) -> bytes:
        if not data:
            return b""
        out = self._c.process(data)
        return out or b""

    def flush(self, finish: bool = False) -> bytes:
        return self._c.flush() if finish else b""


def _brotli_one_shot(data: bytes, quality: int = 5, mode: str = "text", lgwin: Optional[int] = None) -> bytes:
    if _BROTLI_IMPL == "brotlicffi":
        # brotlicffi expects integer mode constants
        mode_val = _brotli.MODE_TEXT if mode == "text" else _brotli.MODE_GENERIC
        params = {"quality": quality, "mode": mode_val}
        if lgwin is not None:
            params["lgwin"] = lgwin
        return _brotli.compress(data, **params)
    elif _BROTLI_IMPL == "brotli":
        params = {"quality": quality, "mode": _brotli.MODE_TEXT if mode == "text" else _brotli.MODE_GENERIC}
        if lgwin is not None:
            params["lgwin"] = lgwin
        return _brotli.compress(data, **params)
    else:
        raise ImportError("No brotli implementation available")


class CompressionMiddleware:
    def __init__(
        self,
        app: Optional[Callable] = None,
        *,
        minimum_size: int = 500,
        path_prefix: Optional[str] = None,
        compress_all_types: bool = False,
        skip_incompressible: bool = True,
        br_quality: int = 5,
        br_mode: str = "text",
        br_lgwin: Optional[int] = None,
        gzip_level: int = 6,
    ):
        self.app = app
        self.minimum_size = minimum_size
        self.path_prefix = path_prefix
        self.compress_all_types = compress_all_types
        self.skip_incompressible = skip_incompressible
        self.br_quality = br_quality
        self.br_mode = br_mode
        self.br_lgwin = br_lgwin
        self.gzip_level = gzip_level

        self._incompressible_prefixes = (b"image/", b"video/", b"audio/",)
        self._incompressible_exact = {
            b"application/zip",
            b"application/x-zip-compressed",
            b"application/gzip",
            b"application/x-gzip",
            b"application/x-tar",
            b"application/pdf",
        }

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if self.path_prefix and not scope["path"].startswith(self.path_prefix):
            return await self.app(scope, receive, send)

        accept = _get_header(scope.get("headers", []), b"accept-encoding") or b""
        wants_br = _brotli is not None and b"br" in accept
        wants_gzip = b"gzip" in accept

        if not (wants_br or wants_gzip):
            return await self.app(scope, receive, send)

        state = {
            "status": 200,
            "headers": None,
            "method": scope.get("method", "GET").upper(),
            "eligible": False,
            "encoding": None,
            "buffer": BytesIO(),
            "gz_stream": None,
            "br_stream": None,
            "start_sent": False,
        }

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
                headers = list(message.get("headers", []))

                if state["method"] == "HEAD" or state["status"] in (
                        204, 304) or _has_header(headers, b"content-encoding"):
                    state["eligible"] = False
                else:
                    ctype = _get_header(headers, b"content-type")
                    state["eligible"] = self._should_compress(ctype)

                if state["eligible"]:
                    state["encoding"] = b"br" if wants_br else (b"gzip" if wants_gzip else None)

                if state["eligible"] and state["encoding"]:
                    headers = [(k, v) for (k, v) in headers if k != b"content-length"]
                    headers = _ensure_vary_accept_encoding(headers)

                state["headers"] = headers
                return

            if message["type"] == "http.response.body":
                body = message.get("body", b"")
                more = message.get("more_body", False)

                if not state["eligible"] or not state["encoding"]:
                    if not state["start_sent"]:
                        state["start_sent"] = True
                        await send({
                            "type": "http.response.start", "status": state["status"], "headers": state["headers"]
                        })
                    return await send(message)

                state["buffer"].write(body)

                if more:
                    if (state["br_stream"] is None and state["gz_stream"] is None and
                            state["buffer"].tell() >= self.minimum_size):
                        await _start_streaming(send, state, self)
                        data = state["buffer"].getvalue()
                        state["buffer"] = None
                        if state["encoding"] == b"br":
                            out = state["br_stream"].compress(data)
                            if out:
                                await send({"type": "http.response.body", "body": out, "more_body": True})
                        else:
                            state["gz_stream"].write(data)
                            await _drain_gzip(send, state["gz_stream"])
                    else:
                        if state["encoding"] == b"br" and state["br_stream"] is not None and body:
                            out = state["br_stream"].compress(body)
                            if out:
                                await send({"type": "http.response.body", "body": out, "more_body": True})
                        elif state["encoding"] == b"gzip" and state["gz_stream"] is not None and body:
                            state["gz_stream"].write(body)
                            await _drain_gzip(send, state["gz_stream"])

                    return await send({"type": "http.response.body", "body": b"", "more_body": True})

                if state["br_stream"] is None and state["gz_stream"] is None:
                    data = state["buffer"].getvalue()
                    if len(data) < self.minimum_size:
                        if not state["start_sent"]:
                            state["start_sent"] = True
                            await send({
                                "type": "http.response.start", "status": state["status"], "headers": state["headers"]
                            })
                        return await send({"type": "http.response.body", "body": data, "more_body": False})

                    if state["encoding"] == b"br":
                        out = _brotli_one_shot(data, quality=self.br_quality, mode=self.br_mode, lgwin=self.br_lgwin)
                    else:
                        out = gzip.compress(data, compresslevel=self.gzip_level)
                    headers = state["headers"] + [(b"content-encoding", state["encoding"]),
                                                  (b"content-length", str(len(out)).encode())]
                    state["start_sent"] = True
                    await send({"type": "http.response.start", "status": state["status"], "headers": headers})
                    return await send({"type": "http.response.body", "body": out, "more_body": False})
                else:
                    if state["encoding"] == b"br":
                        tail = state["br_stream"].flush(finish=True)
                        if tail:
                            await send({"type": "http.response.body", "body": tail, "more_body": True})
                    else:
                        state["gz_stream"].close()
                    return await send({"type": "http.response.body", "body": b"", "more_body": False})

        return await self.app(scope, receive, send_wrapper)

    def _should_compress(self, ctype: Optional[bytes]) -> bool:
        if self.compress_all_types:
            if not self.skip_incompressible:
                return True
            if not ctype:
                return True
            bare = ctype.split(b";", 1)[0].strip()
            if any(bare.startswith(p) for p in self._incompressible_prefixes):
                return False
            if bare in self._incompressible_exact:
                return False
            return True

        if not ctype:
            return False
        return (
            ctype.startswith(b"text/")
            or ctype.startswith(b"application/json")
            or ctype.startswith(b"application/javascript")
            or ctype.startswith(b"text/javascript")
            or ctype.startswith(b"text/css")
            or ctype.startswith(b"image/svg+xml")
            or ctype.startswith(b"application/xml")
            or ctype.startswith(b"application/xhtml+xml")
        )


def _get_header(headers: HeaderList, name: bytes) -> Optional[bytes]:
    for k, v in headers:
        if k == name:
            return v
    return None


def _has_header(headers: HeaderList, name: bytes) -> bool:
    return any(k == name for k, _ in headers)


def _ensure_vary_accept_encoding(headers: list[Tuple[bytes, bytes]]) -> list[Tuple[bytes, bytes]]:
    idx = next((i for i, (k, _) in enumerate(headers) if k == b"vary"), None)
    if idx is None:
        headers.append((b"vary", b"Accept-Encoding"))
    elif b"accept-encoding" not in headers[idx][1].lower():
        headers[idx] = (b"vary", headers[idx][1] + b", Accept-Encoding")
    return headers


async def _start_streaming(send, state, cfg: CompressionMiddleware):
    headers = state["headers"] + [(b"content-encoding", state["encoding"])]
    state["start_sent"] = True
    await send({"type": "http.response.start", "status": state["status"], "headers": headers})
    if state["encoding"] == b"br":
        state["br_stream"] = _BrotliStreamCompressor(quality=cfg.br_quality, mode=cfg.br_mode, lgwin=cfg.br_lgwin)
    else:
        gzbuf = BytesIO()
        state["gz_stream"] = gzip.GzipFile(fileobj=gzbuf, mode="wb", compresslevel=cfg.gzip_level)


async def _drain_gzip(send, gzfile: gzip.GzipFile):
    buf: BytesIO = gzfile.fileobj
    data = buf.getvalue()
    if data:
        buf.truncate(0)
        buf.seek(0)
        await send({"type": "http.response.body", "body": data, "more_body": True})
