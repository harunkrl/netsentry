"""KPortWatch — Compatibility shim.

The ``DaemonController`` has been refactored into the ``backend.daemon``
package.  This module re-exports it so that existing imports continue to
work during the transition.
"""

from backend.daemon.controller import DaemonController

__all__ = ["DaemonController"]
