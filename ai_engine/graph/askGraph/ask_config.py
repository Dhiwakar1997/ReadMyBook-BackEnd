"""Configuration constants for the ask (RAG chat) graph."""
ASK_GRAPH_CONFIG = {
    "chat_model": "openai:gpt-4.1",
    "chat_temperature": 0.7,
    "refiner_model": "openai:gpt-4.1-mini",
    "refiner_temperature": 0,
    "eval_model": "gpt-4.1-mini",
    "eval_threshold": 0.65,
    "eval_sample_rate": 0.10,
}
