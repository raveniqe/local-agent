from typing import Protocol


class ChatClient(Protocol):
    """
    Defines the interface required by components that communicate
    with a chat model.
    """

    def chat(self, model: str, prompt: str) -> str:
        """Return the model response for the supplied prompt."""
        ...
