from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.funcionario import PapelFuncionario


class FuncionarioCreate(BaseModel):
    nome: str
    email: EmailStr
    senha: str
    papel: PapelFuncionario = PapelFuncionario.OPERADOR


class FuncionarioRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nome: str
    email: str
    papel: PapelFuncionario
    ativo: bool


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    funcionario: FuncionarioRead
