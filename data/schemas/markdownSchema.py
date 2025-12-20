from documentSchema import Document
from pydantic import BaseModel

class Markdown(Document):
    markdown_url: str

class GetMarkdownResponse(BaseModel):
    document: Markdown