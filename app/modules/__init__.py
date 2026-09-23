MODULE_REGISTRY = {}

MODULE_CATEGORIES = [
    "Time Domain",
    "Spectral",
    "Stereo & Phase",
    "Level & Dynamics",
]


def register_module(name, display_name, category="Other"):
    """Decorator to register a module class."""
    def decorator(cls):
        MODULE_REGISTRY[name] = {
            "class": cls,
            "display_name": display_name,
            "category": category,
        }
        return cls
    return decorator
