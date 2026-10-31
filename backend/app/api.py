"""HTTP routes. Every request value is parsed here (app.validation) before it
reaches the conversion code; every exception leaves as ``{"code", "detail"}``."""
from __future__ import annotations

import logging
import shutil
import uuid

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from app import convert
from app.config import OUTPUT_PATH, UPLOAD_PATH
from app.errors import ApiError, DependencyMissing, EbookInputError, ErrorCode
from app.metadata import get_metadata
from app.models import ConversionResponse
from app.validation import (
    ext_from_filename,
    inside,
    parse_download_id,
    parse_file_ids,
    parse_source_ext,
    parse_target_format,
    sanitize_download_name,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

UTF8_NAMES = ("utf-8", "utf-8-sig")


# Handlers are plain ``def``: the work inside is heavy and synchronous (OCR,
# LibreOffice, pandoc); FastAPI runs plain functions in a thread pool, so the
# event loop keeps answering other requests meanwhile.

@router.get("/health")
def health():
    """Liveness probe used by the container healthcheck."""
    return {"status": "ok"}


@router.post("/upload")
def upload_file(file: UploadFile = File(...)):
    file_id = str(uuid.uuid4())
    ext = ext_from_filename(file.filename).value
    save_path = str(inside(UPLOAD_PATH, f"{file_id}.{ext}"))
    with open(save_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    meta = get_metadata(save_path, ext)
    return {"id": file_id, "ext": ext, "original_name": file.filename, "meta": meta}


@router.post("/convert", response_model=ConversionResponse, response_model_exclude_none=True)
def convert_document(file_id: str = Form(...), source_ext: str = Form(...),
                     target_format: str = Form(...), txt_smart: bool = Form(True),
                     pdf_docx_mode: str = Form(None)):
    ids = parse_file_ids(file_id)
    source = parse_source_ext(source_ext).value
    target = parse_target_format(target_format)
    in_paths = [inside(UPLOAD_PATH, f"{fid}.{source}") for fid in ids]
    if not all(p.is_file() for p in in_paths):
        raise ApiError(404, ErrorCode.FILE_NOT_FOUND, "File not found")

    merge = len(ids) > 1
    out_name = (f"merged_{uuid.uuid4()}" if merge else f"converted_{ids[0]}") + f".{target.out_ext}"
    job = convert.Job(
        in_paths=[str(p) for p in in_paths], out_path=str(inside(OUTPUT_PATH, out_name)),
        source=source, target=target.value, out_ext=target.out_ext,
        txt_smart=txt_smart, pdf_docx_mode=pdf_docx_mode, file_id=ids[0])
    try:
        convert.run(job, merge=merge)
        return _response(out_name, job)
    except EbookInputError as e:
        # DRM, KFX, not a Kindle book, no audio...: the reason is the user's to see
        raise ApiError(422, e.code, str(e)) from e
    except DependencyMissing as e:
        logger.exception("Conversion %s -> %s needs a missing dependency", source, target.value)
        raise ApiError(500, e.code, str(e)) from e
    except Exception as e:  # any engine failure: answered as 500, logged with traceback
        logger.exception("Conversion %s -> %s failed", source, target.value)
        raise ApiError(500, ErrorCode.CONVERSION_FAILED, str(e)) from e


def _response(out_name: str, job: convert.Job) -> ConversionResponse:
    out = job.outcome
    encoding = out.source_encoding
    if encoding and encoding.lower().replace("_", "-") in UTF8_NAMES:
        encoding = None
    return ConversionResponse(
        download_id=out_name,
        meta=get_metadata(job.out_path, job.out_ext),
        warnings=out.warnings,
        warning="; ".join(out.warnings) or None,
        engine=out.engine,
        layout=out.layout or None,
        ocr_mode=out.ocr_mode,
        source_encoding=encoding,
    )


@router.get("/download/{download_id}")
def download_file(download_id: str, name: str = None):
    download_id = parse_download_id(download_id)
    path = inside(OUTPUT_PATH, download_id)
    if not path.is_file():
        raise ApiError(404, ErrorCode.FILE_NOT_FOUND, "No such result")
    out_name = sanitize_download_name(name) or f"LocalSuite_{download_id}"
    return FileResponse(str(path), filename=out_name)


def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content=exc.body())


def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={
        "code": ErrorCode.INVALID_REQUEST.value, "detail": jsonable_encoder(exc.errors())})
