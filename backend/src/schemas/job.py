from pydantic import BaseModel, Field
class JobInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    dataset_id: int
    params: dict = Field(default_factory=dict)
    # 可选：绑定已发布的可试验人群批次，绑定后受资格约束
    audience_build_id: int | None = Field(default=None)
