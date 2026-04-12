from fastapi import APIRouter, HTTPException

from ..core.markdown import strip_markdown
from ..core.models import PreprocessRequest, PreprocessResponse

router = APIRouter()


@router.post("/preprocess", response_model=PreprocessResponse)
async def preprocess(req: PreprocessRequest):
    text = strip_markdown(req.markdown)
    if not text:
        raise HTTPException(400, "Empty text after preprocessing")
    return PreprocessResponse(text=text)
