from __future__ import annotations

from typing import Dict, List, Optional, Any


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
        import json
        try:
            data = json.loads(raw_body.decode("utf-8")) if raw_body else {}
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

    async def parse(self, scope, receive, *, raw_body: bytes, headers: Dict[bytes, bytes]) -> Dict:
        # Minimal multipart parsing via cgi
        import cgi
        from io import BytesIO
        environ = {
            "REQUEST_METHOD": scope.get("method", "POST"),
            "CONTENT_TYPE": (headers.get(b"content-type") or b"").decode("utf-8"),
            "CONTENT_LENGTH": str(len(raw_body)),
        }
        fp = BytesIO(raw_body)
        try:
            form = cgi.FieldStorage(fp=fp, environ=environ, keep_blank_values=True)
        except Exception:
            from neutronapi.api import exceptions
            raise exceptions.ValidationError("Invalid multipart form data")

        data: Dict[str, object] = {}
        file_bytes: Optional[bytes] = None
        filename: Optional[str] = None
        file_content_type: Optional[str] = None

        for key in form.keys():
            item = form[key]
            if getattr(item, "filename", None):
                if file_bytes is None:  # capture first file for convenience
                    file_bytes = item.file.read()
                    filename = item.filename
                    file_content_type = getattr(item, "type", None)
            else:
                data[key] = item.value

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

        # If it looks like JSON, also parse it
        ctype = (headers.get(b"content-type") or b"").split(b";", 1)[0].strip().lower()
        if ctype == b"application/json" and raw_body:
            try:
                import json
                parsed = json.loads(raw_body.decode("utf-8"))
                result["body"] = parsed
            except Exception:
                result["body"] = raw_body  # Fallback to raw if JSON parsing fails
        else:
            result["body"] = raw_body

        return result
