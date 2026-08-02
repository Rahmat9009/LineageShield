from abc import ABC, abstractmethod

from app.models import ChangeRequest, ContextGraph


class ProviderUnavailableError(RuntimeError):
    """Raised when a configured context provider cannot serve a request."""


class ContextProvider(ABC):
    name: str

    @abstractmethod
    async def build_context(self, request: ChangeRequest) -> ContextGraph:
        raise NotImplementedError

    async def healthcheck(self) -> tuple[bool, str]:
        return True, f"{self.name.title()} context provider is ready."
