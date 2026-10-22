"""Recovery stays active when the latency feature is disabled."""

from dataclasses import dataclass

from .block_status import PeerBlockStatus
from .paths import identity_directory as recovery_directory

__all__ = ["RecoveryApi", "RecoveryChanged", "RecoveryStatus", "recovery_directory"]


@dataclass(frozen=True)
class RecoveryStatus:
    state: str = "disabled"
    peers: tuple[PeerBlockStatus, ...] = ()


@dataclass(frozen=True)
class RecoveryChanged:
    status: RecoveryStatus


class RecoveryApi:
    @property
    def status(self) -> RecoveryStatus:
        raise NotImplementedError

    def set_enabled(self, enabled: bool) -> None:
        """Authorize new holds; false requests restoration without killing recovery."""
        raise NotImplementedError

    def pending(self, account: str, target: str) -> bool:
        """A pending communication transaction prevents a concurrent commendation."""
        raise NotImplementedError
