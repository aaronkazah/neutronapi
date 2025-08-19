"""
Start command using uvicorn with all options support.
"""
import os
import sys
from typing import List


class Command:
    def __init__(self):
        self.help = "Start the ASGI server"

    def handle(self, args: List[str]) -> None:
        """
        Start ASGI server with uvicorn.
        
        Usage:
            python manage.py start                        # Development mode with reload
            python manage.py start --production           # Production mode (auto workers, optimized)
            python manage.py start --production --workers 8  # Production with custom workers
            python manage.py start --host 0.0.0.0         # Custom host
            python manage.py start --port 8080            # Custom port
        
        Production mode automatically sets:
        - Multiple workers (CPU count * 2 + 1)
        - Host 0.0.0.0 (accept external connections)
        - Optimized event loop and HTTP parser
        - Warning-level logging
        - No auto-reload
        
        All options can be overridden. Supports all uvicorn options.
        """
        
        try:
            import uvicorn
        except ImportError:
            print("Error: uvicorn is required to run the server.")
            print("Install it with: pip install uvicorn")
            sys.exit(1)
        
        # Import the application
        try:
            from apps.entry import app
        except ImportError:
            print("Error: Could not import app from apps.entry")
            print("Make sure apps/entry.py exists and defines an 'app' variable.")
            sys.exit(1)
        
        # Check for production mode
        production_mode = False
        if "--production" in args:
            production_mode = True
            args = [arg for arg in args if arg != "--production"]  # Remove --production flag
        
        # Default settings
        if production_mode:
            # Production defaults - optimized for deployment
            import multiprocessing
            cpu_count = multiprocessing.cpu_count()
            workers = cpu_count * 2 + 1  # Common formula for async apps
            
            defaults = {
                "host": "0.0.0.0",
                "port": 8000,
                "reload": False,
                "workers": workers,
                "access_log": True,
                "log_level": "warning",  # Less verbose in production
                "loop": "uvloop",  # Faster event loop if available
                "http": "httptools",  # Faster HTTP parser if available
            }
            print(f"Starting production server with {workers} workers...")
        else:
            # Development defaults
            defaults = {
                "host": "127.0.0.1", 
                "port": 8000,
                "reload": True,
                "access_log": True,
                "log_level": "info",
            }
            print("Starting development server with auto-reload...")
        
        # Parse uvicorn-style arguments
        uvicorn_kwargs = defaults.copy()
        
        i = 0
        while i < len(args):
            arg = args[i]
            
            if arg == "--help":
                print(self.handle.__doc__)
                print("\nUvicorn options:")
                os.system("uvicorn --help")
                return
            elif arg == "--host":
                if i + 1 < len(args):
                    uvicorn_kwargs["host"] = args[i + 1]
                    i += 1
                else:
                    print("Error: --host requires a value")
                    return
            elif arg == "--port":
                if i + 1 < len(args):
                    try:
                        uvicorn_kwargs["port"] = int(args[i + 1])
                        i += 1
                    except ValueError:
                        print(f"Error: Invalid port '{args[i + 1]}'")
                        return
                else:
                    print("Error: --port requires a value")
                    return
            elif arg == "--reload":
                uvicorn_kwargs["reload"] = True
            elif arg == "--no-reload":
                uvicorn_kwargs["reload"] = False
            elif arg == "--workers":
                if i + 1 < len(args):
                    try:
                        uvicorn_kwargs["workers"] = int(args[i + 1])
                        uvicorn_kwargs["reload"] = False  # Can't use reload with workers
                        i += 1
                    except ValueError:
                        print(f"Error: Invalid workers '{args[i + 1]}'")
                        return
                else:
                    print("Error: --workers requires a value")
                    return
            elif arg == "--log-level":
                if i + 1 < len(args):
                    uvicorn_kwargs["log_level"] = args[i + 1]
                    i += 1
                else:
                    print("Error: --log-level requires a value")
                    return
            elif arg == "--access-log":
                uvicorn_kwargs["access_log"] = True
            elif arg == "--no-access-log":
                uvicorn_kwargs["access_log"] = False
            elif arg == "--loop":
                if i + 1 < len(args):
                    uvicorn_kwargs["loop"] = args[i + 1]
                    i += 1
                else:
                    print("Error: --loop requires a value")
                    return
            elif arg == "--http":
                if i + 1 < len(args):
                    uvicorn_kwargs["http"] = args[i + 1]
                    i += 1
                else:
                    print("Error: --http requires a value")
                    return
            elif arg == "--ws":
                if i + 1 < len(args):
                    uvicorn_kwargs["ws"] = args[i + 1]
                    i += 1
                else:
                    print("Error: --ws requires a value")
                    return
            elif arg == "--lifespan":
                if i + 1 < len(args):
                    uvicorn_kwargs["lifespan"] = args[i + 1]
                    i += 1
                else:
                    print("Error: --lifespan requires a value")
                    return
            elif arg == "--ssl-keyfile":
                if i + 1 < len(args):
                    uvicorn_kwargs["ssl_keyfile"] = args[i + 1]
                    i += 1
                else:
                    print("Error: --ssl-keyfile requires a value")
                    return
            elif arg == "--ssl-certfile":
                if i + 1 < len(args):
                    uvicorn_kwargs["ssl_certfile"] = args[i + 1]
                    i += 1
                else:
                    print("Error: --ssl-certfile requires a value")
                    return
            elif arg.startswith("--"):
                print(f"Warning: Unrecognized option '{arg}', ignoring")
            else:
                # Assume it's host:port format
                if ":" in arg:
                    host, port_str = arg.split(":", 1)
                    uvicorn_kwargs["host"] = host
                    try:
                        uvicorn_kwargs["port"] = int(port_str)
                    except ValueError:
                        print(f"Error: Invalid port in '{arg}'")
                        return
                else:
                    try:
                        uvicorn_kwargs["port"] = int(arg)
                    except ValueError:
                        print(f"Error: Invalid address '{arg}'")
                        return
            
            i += 1
        
        # Show startup message
        mode = "production" if production_mode else "development"
        print(f"Starting {mode} server at http://{uvicorn_kwargs['host']}:{uvicorn_kwargs['port']}/")
        if uvicorn_kwargs.get("reload"):
            print("Auto-reload enabled. Quit with CONTROL-C.")
        else:
            print("Quit the server with CONTROL-C.")
        
        # Run the server
        try:
            uvicorn.run(app, **uvicorn_kwargs)
        except KeyboardInterrupt:
            print("\nServer stopped.")
        except Exception as e:
            print(f"Error starting server: {e}")
            sys.exit(1)