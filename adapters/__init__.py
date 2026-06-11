"""Infrastructure adapter layer.

Three layers, strictly separated:

  - ``adapters.base``  — abstract interfaces (ABCs). The only adapter package
    that Layer 1 (``agents/``) is permitted to import.
  - ``adapters.local`` / ``adapters.gcp`` / ``adapters.aws`` — concrete
    implementations (Layer 3). These may import cloud-provider SDKs.
  - ``adapters.factory`` — selects and instantiates the concrete
    implementation for the active ``CLOUD_TARGET``.

No agent ever imports a concrete implementation directly. All adapter access
flows through :mod:`adapters.factory`.
"""
