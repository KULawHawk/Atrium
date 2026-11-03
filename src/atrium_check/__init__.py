"""Atrium contract-registry checker.

Atrium owns the contracts that cross APEX tool boundaries. The registry
(``registry/contracts.v1.json``) names every contract, the member repo and file
that carries it, and the sha256 of that file. This package reads the registry
plus local checkouts of the member repos and reports every way they disagree.

Standard library only. Read-only except ``repin --apply`` (Constitution
Principle 3: plan first, apply second).
"""

from atrium_check.check import Finding, check, load_registry

__all__ = ["Finding", "check", "load_registry"]
__version__ = "0.1.0"
