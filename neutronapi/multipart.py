"""
Thread-safe multipart form parser for handling concurrent file uploads.
"""
import asyncio
import io
import re
import email.message
from typing import Dict, Any, Optional, Tuple, List
from concurrent.futures import ThreadPoolExecutor
import threading


class MultipartField:
    """Represents a single field in a multipart form."""
    
    def __init__(self, name: str, value: bytes, filename: Optional[str] = None, 
                 content_type: Optional[str] = None, headers: Optional[Dict[str, str]] = None):
        self.name = name
        self.value = value
        self.filename = filename
        self.content_type = content_type
        self.headers = headers or {}
    
    @property
    def is_file(self) -> bool:
        """Check if this field represents a file upload."""
        return self.filename is not None
    
    def get_string_value(self, encoding: str = 'utf-8') -> str:
        """Get the field value as a string."""
        if isinstance(self.value, bytes):
            return self.value.decode(encoding)
        return str(self.value)


class ThreadSafeMultipartParser:
    """Thread-safe parser for multipart/form-data content."""
    
    def __init__(self, max_workers: int = None):
        # Use performance config for optimal settings
        if max_workers is None:
            from .performance_config import get_performance_config
            config = get_performance_config()
            max_workers = config.get_multipart_config()['max_workers']
            
        self.max_workers = max_workers
        self._thread_pool = ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.RLock()
    
    async def parse(self, body: bytes, content_type: str) -> Dict[str, MultipartField]:
        """
        Parse multipart form data asynchronously.
        
        Args:
            body: The raw request body
            content_type: The Content-Type header value
            
        Returns:
            Dictionary of field names to MultipartField objects
        """
        loop = asyncio.get_event_loop()
        
        # Use thread pool for CPU-intensive parsing
        return await loop.run_in_executor(
            self._thread_pool, 
            self._parse_multipart_sync, 
            body, 
            content_type
        )
    
    def _parse_multipart_sync(self, body: bytes, content_type: str) -> Dict[str, MultipartField]:
        """Synchronous multipart parsing in thread pool."""
        with self._lock:
            try:
                # Extract boundary from content type
                boundary = self._extract_boundary(content_type)
                if not boundary:
                    raise ValueError("No boundary found in content type")
                
                # Split body by boundary
                parts = self._split_by_boundary(body, boundary)
                
                # Parse each part
                fields = {}
                for part in parts:
                    if not part.strip():
                        continue
                    
                    field = self._parse_part(part)
                    if field:
                        fields[field.name] = field
                
                return fields
                
            except Exception as e:
                raise ValueError(f"Failed to parse multipart data: {str(e)}")
    
    def _extract_boundary(self, content_type: str) -> Optional[str]:
        """Extract boundary from content type header."""
        # Parse content type to extract boundary
        msg = email.message.EmailMessage()
        msg['content-type'] = content_type
        
        boundary = msg.get_param('boundary')
        if boundary:
            # Remove quotes if present
            return boundary.strip('"')
        
        # Fallback: regex extraction
        match = re.search(r'boundary=([^;]+)', content_type)
        if match:
            return match.group(1).strip('"')
        
        return None
    
    def _split_by_boundary(self, body: bytes, boundary: str) -> List[bytes]:
        """Split body by multipart boundary."""
        boundary_bytes = f'--{boundary}'.encode()
        end_boundary_bytes = f'--{boundary}--'.encode()
        
        # Split by boundary
        parts = body.split(boundary_bytes)
        
        # Remove first empty part and last part if it's the end boundary
        if parts:
            parts = parts[1:]  # Remove empty first part
        
        # Remove the final boundary marker
        result_parts = []
        for part in parts:
            if part.startswith(b'--'):
                break  # This is the end boundary
            result_parts.append(part)
        
        return result_parts
    
    def _parse_part(self, part: bytes) -> Optional[MultipartField]:
        """Parse a single multipart part."""
        if not part or len(part) < 4:
            return None
        
        # Split headers and body
        try:
            header_end = part.find(b'\r\n\r\n')
            if header_end == -1:
                header_end = part.find(b'\n\n')
                if header_end == -1:
                    return None
                header_section = part[:header_end]
                body_section = part[header_end + 2:]
            else:
                header_section = part[:header_end]
                body_section = part[header_end + 4:]
            
            # Parse headers
            headers = self._parse_headers(header_section)
            
            # Extract field name and filename from Content-Disposition
            content_disposition = headers.get('content-disposition', '')
            name = self._extract_field_name(content_disposition)
            filename = self._extract_filename(content_disposition)
            
            if not name:
                return None
            
            # Get content type
            content_type = headers.get('content-type')
            
            # Remove trailing CRLF from body
            if body_section.endswith(b'\r\n'):
                body_section = body_section[:-2]
            elif body_section.endswith(b'\n'):
                body_section = body_section[:-1]
            
            return MultipartField(
                name=name,
                value=body_section,
                filename=filename,
                content_type=content_type,
                headers=headers
            )
            
        except Exception as e:
            return None
    
    def _parse_headers(self, header_section: bytes) -> Dict[str, str]:
        """Parse headers from a multipart section."""
        headers = {}
        try:
            header_text = header_section.decode('utf-8', errors='ignore')
            for line in header_text.split('\n'):
                line = line.strip()
                if not line:
                    continue
                
                if ':' in line:
                    key, value = line.split(':', 1)
                    headers[key.strip().lower()] = value.strip()
        except Exception:
            pass
        
        return headers
    
    def _extract_field_name(self, content_disposition: str) -> Optional[str]:
        """Extract field name from Content-Disposition header."""
        # Look for name="field_name"
        match = re.search(r'name="([^"]*)"', content_disposition)
        if match:
            return match.group(1)
        
        # Look for name=field_name (without quotes)
        match = re.search(r'name=([^;]+)', content_disposition)
        if match:
            return match.group(1).strip()
        
        return None
    
    def _extract_filename(self, content_disposition: str) -> Optional[str]:
        """Extract filename from Content-Disposition header."""
        # Look for filename="file.txt"
        match = re.search(r'filename="([^"]*)"', content_disposition)
        if match:
            return match.group(1)
        
        # Look for filename=file.txt (without quotes)
        match = re.search(r'filename=([^;]+)', content_disposition)
        if match:
            return match.group(1).strip()
        
        return None
    
    async def shutdown(self):
        """Shutdown the thread pool."""
        self._thread_pool.shutdown(wait=True)


class StreamingMultipartParser:
    """Streaming parser for very large multipart uploads."""
    
    def __init__(self, max_memory_size: int = 1024 * 1024):  # 1MB
        self.max_memory_size = max_memory_size
    
    async def parse_streaming(self, receive, content_type: str) -> Dict[str, MultipartField]:
        """
        Parse multipart data from a streaming source.
        
        Args:
            receive: ASGI receive callable
            content_type: Content-Type header value
            
        Returns:
            Dictionary of field names to MultipartField objects
        """
        boundary = self._extract_boundary(content_type)
        if not boundary:
            raise ValueError("No boundary found in content type")
        
        # Read data in chunks and parse incrementally
        buffer = b''
        fields = {}
        
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            
            chunk = message.get("body", b"")
            more_body = message.get("more_body", False)
            
            buffer += chunk
            
            # Process complete parts from buffer
            boundary_bytes = f'--{boundary}'.encode()
            
            while boundary_bytes in buffer:
                part_end = buffer.find(boundary_bytes)
                if part_end > 0:
                    part_data = buffer[:part_end]
                    buffer = buffer[part_end + len(boundary_bytes):]
                    
                    # Parse this part if it's complete
                    field = self._parse_part_streaming(part_data)
                    if field:
                        fields[field.name] = field
                else:
                    break
            
            if not more_body:
                break
        
        # Process any remaining data in buffer
        if buffer.strip():
            field = self._parse_part_streaming(buffer)
            if field:
                fields[field.name] = field
        
        return fields
    
    def _extract_boundary(self, content_type: str) -> Optional[str]:
        """Extract boundary from content type header."""
        msg = email.message.EmailMessage()
        msg['content-type'] = content_type
        boundary = msg.get_param('boundary')
        return boundary.strip('"') if boundary else None
    
    def _parse_part_streaming(self, part: bytes) -> Optional[MultipartField]:
        """Parse a multipart part from streaming data."""
        if not part or len(part) < 4:
            return None
        
        try:
            # Find header/body separator
            header_end = part.find(b'\r\n\r\n')
            if header_end == -1:
                header_end = part.find(b'\n\n')
                if header_end == -1:
                    return None
                header_section = part[:header_end]
                body_section = part[header_end + 2:]
            else:
                header_section = part[:header_end]
                body_section = part[header_end + 4:]
            
            # Parse headers
            headers = {}
            header_text = header_section.decode('utf-8', errors='ignore')
            for line in header_text.split('\n'):
                line = line.strip()
                if ':' in line:
                    key, value = line.split(':', 1)
                    headers[key.strip().lower()] = value.strip()
            
            # Extract field info
            content_disposition = headers.get('content-disposition', '')
            name_match = re.search(r'name="([^"]*)"', content_disposition)
            filename_match = re.search(r'filename="([^"]*)"', content_disposition)
            
            if not name_match:
                return None
            
            name = name_match.group(1)
            filename = filename_match.group(1) if filename_match else None
            content_type = headers.get('content-type')
            
            # Clean up body
            if body_section.endswith(b'\r\n'):
                body_section = body_section[:-2]
            elif body_section.endswith(b'\n'):
                body_section = body_section[:-1]
            
            return MultipartField(
                name=name,
                value=body_section,
                filename=filename,
                content_type=content_type,
                headers=headers
            )
            
        except Exception:
            return None


# Global parser instance
_parser = None

def get_multipart_parser() -> ThreadSafeMultipartParser:
    """Get the global multipart parser instance."""
    global _parser
    if _parser is None:
        _parser = ThreadSafeMultipartParser()
    return _parser


async def parse_multipart_form(body: bytes, content_type: str) -> Dict[str, MultipartField]:
    """Convenience function to parse multipart form data."""
    parser = get_multipart_parser()
    return await parser.parse(body, content_type)