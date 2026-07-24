import importlib.util
import os
import sys
import types

# True when running inside a Docker container (/.dockerenv is created by Docker)
IN_DOCKER = os.path.exists('/.dockerenv')


def _install_platformgen_compat_shim() -> None:
    """Provide `platformgen.*` imports when only the legacy `auger` package exists."""
    if "platformgen" in sys.modules:
        return
    try:
        if importlib.util.find_spec("platformgen") is not None:
            return
    except Exception:
        return

    shim = types.ModuleType("platformgen")
    shim.__file__ = __file__
    shim.__package__ = "platformgen"
    shim.__path__ = list(__path__)
    shim.IN_DOCKER = IN_DOCKER
    sys.modules["platformgen"] = shim


_install_platformgen_compat_shim()
