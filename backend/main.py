"""Entry point: ``uvicorn main:app``. Creates the FastAPI app and wires it
together; the routes live in app/api.py, the conversions in app/convert.py."""
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_error_handler, router, validation_error_handler
from app.config import configure_logging
from app.errors import ApiError


def create_app() -> FastAPI:
    configure_logging()
    application = FastAPI(title="Local Doc Suite API")
    application.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1", "http://localhost"], allow_methods=["*"], allow_headers=["*"])
    application.add_exception_handler(ApiError, api_error_handler)
    application.add_exception_handler(RequestValidationError, validation_error_handler)
    application.include_router(router)
    return application


app = create_app()
