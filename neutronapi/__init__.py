"""NeutronAPI public package exports."""

from importlib import import_module

__version__ = "0.6.6"

_EXPORTS = {
    "API": ("neutronapi.base", "API"),
    "Response": ("neutronapi.base", "Response"),
    "StreamingResponse": ("neutronapi.responses", "StreamingResponse"),
    "Endpoint": ("neutronapi.base", "Endpoint"),
    "Application": ("neutronapi.application", "Application"),
    "Background": ("neutronapi.background", "Background"),
    "Task": ("neutronapi.background", "Task"),
    "TaskFrequency": ("neutronapi.background", "TaskFrequency"),
    "TaskPriority": ("neutronapi.background", "TaskPriority"),
    "Status": ("neutronapi.http", "Status"),
    "exceptions": ("neutronapi.exceptions", None),
}

__all__ = ["__version__", *_EXPORTS.keys()]


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module 'neutronapi' has no attribute '{name}'")

    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name)
    value = module if attr_name is None else getattr(module, attr_name)
    globals()[name] = value
    return value
