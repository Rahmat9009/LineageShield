from abc import ABC, abstractmethod
from app.models import ChangeRequest, ContextGraph


class ContextProvider(ABC):
    name: str

    @abstractmethod
    async def build_context(self, request: ChangeRequest) -> ContextGraph:
        raise NotImplementedError
