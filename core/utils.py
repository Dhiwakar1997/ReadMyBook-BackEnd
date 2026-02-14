def get_context_block(data:dict) -> str:
        contexts = data.get("contexts", [])
        sources = data.get("sources", [])
        context_block = "\n\n".join(f"([Document id: {s}]) - {c}" for c, s in zip(contexts, sources))
        return context_block