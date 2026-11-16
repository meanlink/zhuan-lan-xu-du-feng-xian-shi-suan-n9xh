from pydantic import BaseModel, Field

# 编排中的一个引用步骤
class RefStep(BaseModel):
    key: str = Field(min_length=1, max_length=40)
    kind: str = Field(pattern='^(dataset|scheme)$')
    ref_id: int = Field(gt=0)
    op: str = Field(pattern='^(union|intersect|exclude)$')
    label: str = Field(default='', max_length=160)

class SchemeCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str = Field(default='', max_length=500)
    definition: list[RefStep] = Field(default_factory=list, max_length=20)

class SchemeUpdate(BaseModel):
    # 乐观锁：必须携带当前 revision，冲突返回 409
    revision: int
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=500)
    definition: list[RefStep] | None = Field(default=None, max_length=20)

class SchemePublish(BaseModel):
    revision: int

class BuildCreate(BaseModel):
    pass

class ArbitrationInput(BaseModel):
    chosen_source: str = Field(min_length=1, max_length=40)
