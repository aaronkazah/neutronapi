from __future__ import annotations

from io import BytesIO
from typing import Dict, List, Optional, Any

from multipart import parse_form

from neutronapi.encoders import json_loads


class BaseParser:
    """Base parser class for handling different content types."""
    
    media_types: List[str] = []

    def matches(self, headers: Dict[bytes, bytes]) -> bool:
        """Check if this parser can handle the given content type.
        
        Args:
            headers: Request headers
            
        Returns:
            True if parser can handle the content type
        """
        ctype = (headers.get(b"content-type") or b"").split(b";", 1)[0].strip().lower()
        return any(ctype == mt.encode() for mt in self.media_types)

    async def parse(self, scope: Dict[str, Any], receive: Any, *, raw_body: bytes, headers: Dict[bytes, bytes]) -> Dict[str, Any]:
        """Parse request body.
        
        Args:
            scope: ASGI scope
            receive: ASGI receive callable
            raw_body: Raw request body bytes
            headers: Request headers
            
        Returns:
            Parsed data dictionary
            
        Raises:
            NotImplementedError: Must be implemented by subclasses
        """
        raise NotImplementedError


class JSONParser(BaseParser):
    """Parser for application/json content type."""
    
    media_types = ["application/json"]

    async def parse(self, scope: Dict[str, Any], receive: Any, *, raw_body: bytes, headers: Dict[bytes, bytes]) -> Dict[str, Any]:
        """Parse JSON request body.
        
        Args:
            scope: ASGI scope
            receive: ASGI receive callable
            raw_body: Raw request body bytes
            headers: Request headers
            
        Returns:
            Dict with 'body' key containing parsed JSON data
            
        Raises:
            ValidationError: If JSON is malformed
        """
        try:
            data = json_loads(raw_body) if raw_body else {}
        except Exception:
            from neutronapi.api import exceptions
            raise exceptions.ValidationError("Invalid JSON body")
        return {"body": data}


class FormParser(BaseParser):
    media_types = ["application/x-www-form-urlencoded"]

    async def parse(self, scope, receive, *, raw_body: bytes, headers: Dict[bytes, bytes]) -> Dict:
        from urllib.parse import parse_qs
        try:
            parsed = parse_qs(raw_body.decode("utf-8")) if raw_body else {}
            # Normalize single-item lists to strings
            data = {k: v[0] if isinstance(v, list) and len(v) == 1 else v for k, v in parsed.items()}
        except Exception:
            from neutronapi.api import exceptions
            raise exceptions.ValidationError("Invalid form data")
        return {"body": data}


class MultiPartParser(BaseParser):
    media_types = ["multipart/form-data"]

    @staticmethod
    def _extract_boundary(headers: Dict[bytes, bytes]) -> Optional[bytes]:
        content_type = headers.get(b"content-type", b"")
        for part in content_type.split(b";")[1:]:
            name, _, value = part.strip().partition(b"=")
            if name.lower() != b"boundary":
                continue
            return value.strip().strip(b'"') or None
        return None

    @staticmethod
    def _extract_first_file_content_type(raw_body: bytes, boundary: bytes | None) -> Optional[str]:
        if not raw_body or not boundary:
            return None

        delimiter = b"--" + boundary
        for segment in raw_body.split(delimiter):
            part = segment.strip()
            if not part or part == b"--":
                continue

            header_block, separator, _ = part.partition(b"\r\n\r\n")
            if not separator:
                continue

            headers_by_name: Dict[bytes, bytes] = {}
            for header_line in header_block.split(b"\r\n"):
                name, _, value = header_line.partition(b":")
                if not value:
                    continue
                headers_by_name[name.strip().lower()] = value.strip()

            disposition = headers_by_name.get(b"content-disposition", b"")
            if b"filename=" not in disposition.lower():
                continue

            content_type = headers_by_name.get(b"content-type")
            if content_type:
                return content_type.decode("utf-8", "ignore")
            return None

        return None

    async def parse(self, scope, receive, *, raw_body: bytes, headers: Dict[bytes, bytes]) -> Dict:
        data: Dict[str, object] = {}
        file_bytes: Optional[bytes] = None
        filename: Optional[str] = None
        file_content_type: Optional[str] = None

        def on_field(field) -> None:
            key = (field.field_name or b"").decode("utf-8")
            value = field.value or b""
            data[key] = value.decode("utf-8")

        def on_file(file) -> None:
            nonlocal file_bytes, filename
            if file_bytes is not None:
                return
            filename = (file.file_name or b"").decode("utf-8") or None
            file.file_object.seek(0)
            file_bytes = file.file_object.read()

        try:
            parse_form(
                {
                    "Content-Type": headers.get(b"content-type", b""),
                    "Content-Length": str(len(raw_body)).encode("utf-8"),
                },
                BytesIO(raw_body),
                on_field,
                on_file,
            )
        except Exception:
            from neutronapi.api import exceptions
            raise exceptions.ValidationError("Invalid multipart form data")

        file_content_type = self._extract_first_file_content_type(
            raw_body,
            self._extract_boundary(headers),
        )

        out = {"body": data}
        if file_bytes is not None:
            out.update({
                "file": file_bytes,
                "filename": filename,
                "file_content_type": file_content_type,
            })
        return out


class BinaryParser(BaseParser):
    """Parser that always returns raw bytes, with optional JSON parsing."""

    media_types = ["*/*"]

    def matches(self, headers: Dict[bytes, bytes]) -> bool:
        """Always match - we want raw bytes regardless of content-type."""
        return True

    async def parse(self, scope: Dict[str, Any], receive: Any, *, raw_body: bytes, headers: Dict[bytes, bytes]) -> Dict[str, Any]:
        """Always return raw bytes, with optional parsed JSON if applicable.

        Args:
            scope: ASGI scope
            receive: ASGI receive callable
            raw_body: Raw request body bytes
            headers: Request headers

        Returns:
            Dict with 'raw' key containing raw bytes and 'body' key with parsed data
        """
        result = {"raw": raw_body or b""}

        # If content-type declares JSON, parse it strictly — no silent fallback
        ctype = (headers.get(b"content-type") or b"").split(b";", 1)[0].strip().lower()
        if ctype == b"application/json" and raw_body:
            try:
                parsed = json_loads(raw_body)
                result["body"] = parsed
            except Exception:
                from neutronapi.api import exceptions
                raise exceptions.ValidationError("Invalid JSON body")
        else:
            result["body"] = raw_body

        return result
