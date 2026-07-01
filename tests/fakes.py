"""Client Anthropic finto per testare l'orchestratore senza rete ne' crediti API."""
import json
from types import SimpleNamespace


class FakeResponse:
    def __init__(self, text):
        self.content = [SimpleNamespace(text=text)]


class FakeClient:
    """`script`: lista di dict, uno per chiamata attesa, restituiti in ordine come JSON.
    Registra ogni `messages.create(**kwargs)` in `self.calls` per ispezione nei test."""

    def __init__(self, script):
        self.script = [json.dumps(item, ensure_ascii=False) for item in script]
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.script:
            raise AssertionError("FakeClient: nessuna risposta rimasta nello script "
                                  "(l'orchestratore ha chiamato l'agente piu' volte del previsto)")
        return FakeResponse(self.script.pop(0))
