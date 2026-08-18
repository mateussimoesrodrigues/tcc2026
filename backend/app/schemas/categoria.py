from pydantic import BaseModel, ConfigDict


class CategoriaCreate(BaseModel):
    nome: str
    descricao: str | None = None


class CategoriaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nome: str
    descricao: str | None = None
