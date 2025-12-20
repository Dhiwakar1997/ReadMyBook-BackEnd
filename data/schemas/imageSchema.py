from documentSchema import Document
from pydantic import BaseModel


class GetAllImagesResponse(BaseModel):
    image_dict: dict[str, str]

class GetImageResponse(BaseModel):
    image_url: str