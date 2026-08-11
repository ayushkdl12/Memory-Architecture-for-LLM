import httpx
import pytest

from app.services.ollama import OllamaLLM


def _make_llm(handler) -> OllamaLLM:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(base_url="http://localhost:11434", transport=transport)
    return OllamaLLM(base_url="http://localhost:11434", http=http)


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/api/embed":
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2], [0.3, 0.4]]})
    if path == "/api/chat":
        assert request.read().decode().find("llama3.2:3b") >= 0
        return httpx.Response(
            200, json={"message": {"content": '[{"memory_type": "FACT","subject": "user"}]'}}
        )
    if path == "/v1/chat/completions":
        payload = (
            b'data: {"choices":[{"delta":{"content":"Hello "}}]}\n\n'
            b'data: {"choices":[{"delta":{"content":"world"}}]}\n\n'
            b"data: [DONE]\n\n"
        )
        return httpx.Response(
            200,
            content=payload,
            headers={"Content-Type": "text/event-stream"},
        )
    return httpx.Response(404)


def test_embed_local():
    llm = _make_llm(_handler)
    assert llm.embed(["a", "b"]) == [[0.1, 0.2], [0.3, 0.4]]


def test_complete_json_local():
    llm = _make_llm(_handler)
    data = llm.complete_json("Extract atoms")
    assert data == [{"memory_type": "FACT", "subject": "user"}]


def test_stream_chat_local():
    llm = _make_llm(_handler)
    stream = llm.stream_chat(
        system="be nice",
        turns=[{"role": "user", "content": "hi"}],
        new_user_text="hello",
    )
    out = "".join(chunk.text for chunk in stream)
    assert out == "Hello world"


def test_ready_check_raises_clear_error():
    def boom(request):
        raise httpx.ConnectError("connection refused", request=request)

    llm = _make_llm(boom)
    from app.services.llm import LLMError

    with pytest.raises(LLMError, match="Cannot reach Ollama"):
        llm._require()