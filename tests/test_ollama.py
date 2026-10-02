import httpx
import pytest

from local_agent.ollama import OllamaClient


class FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {
            "message": {
                "content": "Cześć!",
            }
        }


class FakeErrorResponse:
    def raise_for_status(self):
        raise httpx.HTTPStatusError(
            "500 Internal Server Error",
            request=httpx.Request(
                "POST",
                "http://127.0.0.1:11434/api/chat",
            ),
            response=httpx.Response(500),
        )


def fake_error_post(*args, **kwargs):
    return FakeErrorResponse()


def test_chat_returns_message_content(monkeypatch):
    called_with = {}

    def fake_post(url, json, timeout):
        called_with["url"] = url
        called_with["json"] = json
        called_with["timeout"] = timeout

        return FakeResponse()

    monkeypatch.setattr(
        "local_agent.ollama.httpx.post",
        fake_post,
    )

    client = OllamaClient()
    result = client.chat(
        model="qwen3:1.7b",
        prompt="hello",
    )

    assert called_with["url"] == "http://127.0.0.1:11434/api/chat"
    assert called_with["timeout"] == 120.0

    assert called_with["json"]["model"] == "qwen3:1.7b"
    assert called_with["json"]["messages"][0]["content"] == "hello"
    assert called_with["json"]["stream"] is False

    assert result == "Cześć!"


def test_chat_raises_for_http_error(monkeypatch):
    monkeypatch.setattr(
        "local_agent.ollama.httpx.post",
        fake_error_post,
    )

    client = OllamaClient()

    with pytest.raises(httpx.HTTPStatusError):
        client.chat(model="qwen3:1.7b", prompt="hello")
