"""Importable entrypoint for the BioAI backend."""

import os
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


_backend_path = Path(__file__).with_name("main (3).py")
_spec = spec_from_file_location("bioai_backend", _backend_path)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"Unable to load backend from {_backend_path}")

_module = module_from_spec(_spec)
_spec.loader.exec_module(_module)

app = _module.app


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)