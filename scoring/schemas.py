from pydantic import BaseModel


class AnalyzeRequest(BaseModel):
    text: str
    language: str = "ja"


class AnalyzeResponse(BaseModel):
    level: int       # 1-10 (L1-L10)
    band: str        # N5 / N4 / N3 / N2 / N1
    confidence: str  # low / medium / high
