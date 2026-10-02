import httpx


class OllamaClient:
    """
    Simple HTTP client for communicating with a local Ollama server.

    The client sends chat requests to the Ollama API and returns
    the assistant message content as a string.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout

    def chat(self, model: str, prompt: str) -> str:
        """
        Send a prompt to the specified Ollama model and return its response text.
        """
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "stream": False,
        }

        response = httpx.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=self.timeout,
        )

        response.raise_for_status()
        data = response.json()
        return data["message"]["content"]
