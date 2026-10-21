import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import Conflict, DomainError, Forbidden, InvalidRequest, NotFound, Unprocessable, domain_error_response
from app.main import app as solscore_app


@pytest.mark.parametrize(
    ("error", "status_code"),
    [(InvalidRequest, 400), (Forbidden, 403), (NotFound, 404), (Conflict, 409), (Unprocessable, 422)],
)
def test_a_domain_error_becomes_its_http_status_with_the_symfony_body(error, status_code):
    app = FastAPI()
    app.add_exception_handler(DomainError, domain_error_response)

    @app.get("/failing")
    def failing():
        raise error("Message métier")

    response = TestClient(app).get("/failing")

    assert response.status_code == status_code
    assert response.json() == {"errors": "Message métier"}


def test_the_api_converts_domain_errors():
    assert solscore_app.exception_handlers[DomainError] is domain_error_response
