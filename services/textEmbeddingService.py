from openai import OpenAI
import json

client = OpenAI()
EMBED_MODEL = "text-embedding-3-large"
EMBED_DIM = 3072

class TextEmbeddingService:
    def __init__(self):
        self.client = client
        self.model = EMBED_MODEL
        self._encoder = None

    def _get_encoder(self):
        if self._encoder is not None:
            return self._encoder

        try:
            import tiktoken  # type: ignore

            try:
                self._encoder = tiktoken.encoding_for_model(self.model)
            except Exception:
                # Some embedding model names may not be recognized by tiktoken yet.
                self._encoder = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self._encoder = None

        return self._encoder

    def _estimate_tokens(self, text: str) -> int:
        #print(f"estimating tokens for text: {text}")
        encoder = self._get_encoder()
        if encoder is None:
            # Conservative fallback when tiktoken isn't available.
            # Typical English averages ~4 chars/token; we round up and ensure >= 1.
            return max(1, (len(text) + 3) // 4)
        result = encoder.encode(text or "")
        return len(result)

    def _sanitize_text(self, text: str) -> str:
        """Clean text of characters that cause OpenAI API to reject input."""
        if not text:
            return ""
        # Remove NULL bytes
        text = text.replace('\x00', '')
        # Remove other control characters (except newlines and tabs)
        text = ''.join(char for char in text if char == '\n' or char == '\t' or not (0 <= ord(char) < 32))
        # Remove invalid surrogate pairs
        text = text.encode('utf-8', errors='surrogatepass').decode('utf-8', errors='replace')
        return text.strip()

    def _embed_batch(self, batch_texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Texts should already be sanitized by load_chunk."""
        if not batch_texts:
            return []
        
        try:
            response = self.client.embeddings.create(
                model=self.model,
                input=batch_texts,
            )
            return [item.embedding for item in response.data]
        except Exception as e:
            # Log the problematic batch for debugging
            print(f"[ERROR] OpenAI API error: {e}")
            print(f"[DEBUG] Batch size: {len(batch_texts)}")
            # Print first few texts to help debug
            for i, text in enumerate(batch_texts[:3]):
                preview = repr(text[:100]) if len(text) > 100 else repr(text)
                print(f"[DEBUG] Text {i} (len={len(text)}): {preview}")
            raise

    def load_chunk(self, metadata: dict) -> tuple[list[str], list[dict]]:
        chunks = []
        payloads = []
        for content in metadata.get('contents', []):
            # Skip if text is missing, None, empty, or whitespace-only
            text_value = content.get('text', '')
            if not text_value or not str(text_value).strip():
                continue

            if content['type'] in {'list_item', 'code_block', 'paragraph'}:
                cleaned = content.get('cleaned_text', '')
                # Sanitize the text
                cleaned = self._sanitize_text(cleaned)
                if not cleaned:
                    continue
                chunks.append(cleaned)
                content['text'] = cleaned
                if 'cleaned_text' in content:
                    del content['cleaned_text']
                payloads.append(content)
            elif content['type'] == 'table':
                table_dict = {"header": content.get('header', []), "rows": content.get('rows', [])}
                table_text_str = json.dumps(table_dict)
                # Sanitize table text (shouldn't have issues, but be safe)
                table_text_str = self._sanitize_text(table_text_str)
                if not table_text_str:
                    continue
                chunks.append(table_text_str)
                content['text'] = table_text_str
                payloads.append(content)
        
        print(f"[load_chunk] Loaded {len(chunks)} valid chunks from {len(metadata.get('contents', []))} contents")
        return chunks, payloads
    
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        # OpenAI limits:
        # - Max 2048 inputs per request
        # - Max ~300k tokens per request (we use 250k for safety margin)
        max_inputs_per_request = 2048
        max_request_tokens = 250_000

        embeddings: list[list[float]] = []
        batch: list[str] = []
        batch_tokens = 0

        for text in texts:
            text_tokens = self._estimate_tokens(text)
            if text_tokens > max_request_tokens:
                raise ValueError(
                    f"Single text is too large to embed in one request ({text_tokens} tokens). "
                    "Chunk it earlier before calling embed_texts."
                )

            # Flush batch if adding this text would exceed token OR input count limits
            should_flush = batch and (
                (batch_tokens + text_tokens) > max_request_tokens or
                len(batch) >= max_inputs_per_request
            )
            
            if should_flush:
                print(f"[embed_texts] Processing batch: {len(batch)} texts, {batch_tokens} tokens")
                embeddings.extend(self._embed_batch(batch))
                batch = [text]
                batch_tokens = text_tokens
            else:
                batch.append(text)
                batch_tokens += text_tokens

        if batch:
            print(f"[embed_texts] Processing final batch: {len(batch)} texts, {batch_tokens} tokens")
            embeddings.extend(self._embed_batch(batch))

        print(f"[embed_texts] Total embeddings generated: {len(embeddings)}")
        return embeddings

    def embed_single_text(self, text: str) -> list[float]:
        response = self.client.embeddings.create(
            model=self.model,
            input=text,
        )
        return response.data[0].embedding