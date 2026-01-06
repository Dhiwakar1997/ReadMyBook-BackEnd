from openai import OpenAI

client = OpenAI()
EMBED_MODEL = "text-embedding-3-large"
EMBED_DIM = 3072

class TextEmbeddingService:
    def __init__(self):
        self.client = client
        self.model = EMBED_MODEL

    def load_chunk(self, metadata: dict) -> tuple[list[str], list[dict]]:
        chunks = [content['text'] for content in metadata.get('contents', []) if  content['type']in{'heading','paragraph'}]
        payloads = [content for content in metadata.get('contents', []) if content['type']in{'heading','paragraph'}]
        for payload in payloads:
            payload.pop('clean_text', None)
        return chunks, payloads
    
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        response = self.client.embeddings.create(
            model=self.model,
            input=texts,
        )
        return [item.embedding for item in response.data]

    def embed_single_text(self, text: str) -> list[float]:
        response = self.client.embeddings.create(
            model=self.model,
            input=text,
        )
        return response.data[0].embedding