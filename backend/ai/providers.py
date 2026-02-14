from dataclasses import dataclass


@dataclass
class CompletionResult:
    text: str
    provider_used: str


@dataclass
class EmbeddingResult:
    vector: list[float]
    provider_used: str


class AIProvider:
    provider_name = "base"

    def generate_completion(self, prompt: str, model: str) -> CompletionResult:
        raise NotImplementedError

    def generate_embedding(self, text: str, model: str) -> EmbeddingResult:
        raise NotImplementedError


class LocalProvider(AIProvider):
    provider_name = "local"

    def generate_completion(self, prompt: str, model: str) -> CompletionResult:
        return CompletionResult(text=f"local:{prompt[:64]}", provider_used=self.provider_name)

    def generate_embedding(self, text: str, model: str) -> EmbeddingResult:
        seed = float((len(text) % 100) / 100)
        return EmbeddingResult(vector=[seed] * 8, provider_used=self.provider_name)


class CloudProvider(AIProvider):
    provider_name = "cloud"

    def generate_completion(self, prompt: str, model: str) -> CompletionResult:
        return CompletionResult(text=f"cloud:{prompt[:64]}", provider_used=self.provider_name)

    def generate_embedding(self, text: str, model: str) -> EmbeddingResult:
        seed = float((len(text) % 100) / 100)
        return EmbeddingResult(vector=[seed] * 8, provider_used=self.provider_name)


class HybridProvider(AIProvider):
    provider_name = "hybrid"

    def __init__(self):
        self.local = LocalProvider()
        self.cloud = CloudProvider()

    def generate_completion(self, prompt: str, model: str) -> CompletionResult:
        return self.local.generate_completion(prompt, model)

    def generate_embedding(self, text: str, model: str) -> EmbeddingResult:
        return self.local.generate_embedding(text, model)
