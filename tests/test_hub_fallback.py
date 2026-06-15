import json

from agentlas_cloud.networking import init_networking
from agentlas_cloud.networking.hub_fallback import search_hub
from agentlas_cloud.networking.tokenize import tokenize


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def mcp_payload(results):
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"results": results}, ensure_ascii=False),
                }
            ]
        },
    }


def test_hub_search_trims_reranks_projects_and_caches(tmp_path, monkeypatch):
    home = tmp_path / "networking"
    init_networking(home)
    calls = []
    results = [
        {
            "slug": f"privacy-feedback-pipeline-{i}",
            "name": "Privacy Feedback Pipeline" if i else "Privacy Feedback Eval Pipeline Builder",
            "nameEn": "Privacy Feedback Pipeline",
            "tagline": "long field should not be returned",
            "manifestUrl": "https://example.test/manifest",
            "kind": "cloud-callable",
            "callable": True,
            "routingReady": False,
            "trustGrade": "A",
            "installCount": 0,
        }
        for i in range(20)
    ]
    results.append(
        {
            "slug": "feature-recommendation-agent",
            "name": "Feature Recommendation Agent",
            "nameEn": "Feature Recommendation Agent",
            "kind": "cloud-callable",
            "callable": True,
            "routingReady": True,
            "trustGrade": "A",
            "installCount": 12,
            "verifiedInvocations": 12,
        }
    )

    def fake_urlopen(request, timeout):
        calls.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse(mcp_payload(results))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    query_tokens = tokenize("agentlas 새기능 추천좀")
    first = search_hub(query_tokens, home=home)
    second = search_hub(query_tokens, home=home)

    assert len(calls) == 1
    assert first["status"] == "ok"
    assert first["limit"] == 10
    assert second["cached"] is True
    assert first["query"] == "agentlas 새기능 기능 추천"
    assert len(first["results"]) <= 10
    assert first["results"][0]["slug"] == "feature-recommendation-agent"
    assert "manifestUrl" not in first["results"][0]
    assert "tagline" not in first["results"][0]
    assert sum(1 for item in first["results"] if item["slug"].startswith("privacy-feedback")) <= 1


def test_hub_search_surfaces_clarify_without_candidate_dump(tmp_path, monkeypatch):
    home = tmp_path / "networking"
    init_networking(home)

    def fake_urlopen(request, timeout):
        return FakeResponse(
            mcp_payload([])
            | {
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "action": "clarify",
                                    "reason": "low_confidence_or_broad_intent",
                                    "questionKo": "어떤 작업을 맡길까요?",
                                    "suggestions": [
                                        {"slug": "generic-agent", "name": "Generic", "nameEn": "Generic", "kind": "install-only"}
                                    ],
                                },
                                ensure_ascii=False,
                            ),
                        }
                    ]
                }
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = search_hub(tokenize("agent routing tokenizer trust"), home=home)

    assert result["status"] == "clarify"
    assert result["reason"] == "low_confidence_or_broad_intent"
    assert result["questionKo"] == "어떤 작업을 맡길까요?"
    assert result["suggestions"][0]["slug"] == "generic-agent"
