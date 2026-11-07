"""Seam 1 against the contract: real HTTP responses checked against ``api/dist/openapi.yaml``.

The contract (TypeSpec -> OpenAPI, ``mise run generate``) is the source of truth. Every
(operation, status) pair it declares has a scenario below that drives the real app (temporary
SQLite file, fixed clock) until it really answers that status. Each exchange is checked twice:

* the response status is declared for the operation and the body passes the response schema;
* the request body passes the request schema (or, in a ``validation_error`` scenario, is
  rejected by it, so the contract and the implementation agree on what is invalid).

Schemas are checked strictly: a field the contract does not declare is a mismatch too (OpenAPI
allows extra properties by default, which would hide a leaked or misspelled field).

A status added to the contract without a scenario fails
``test_every_declared_status_has_a_scenario``.
"""

import copy
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from openapi_core import OpenAPI
from openapi_core.exceptions import OpenAPIError
from openapi_core.testing import MockRequest, MockResponse

from tests.conftest import ClientFactory

CONTRACT = Path(__file__).resolve().parents[2] / "api" / "dist" / "openapi.yaml"
SERVER = "http://localhost:8000"
MSK = timezone(timedelta(hours=3))
# Thursday 5 November 2026, 10:00 in Moscow.
NOW = datetime(2026, 11, 5, 10, 0, tzinfo=MSK)
HTTP_METHODS = ("get", "post", "put", "patch", "delete")


def load_contract() -> dict[str, Any]:
    if not CONTRACT.exists():
        pytest.fail(f"{CONTRACT} is missing: run `mise run generate` (`mise run test` does it)")
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def forbid_extra_properties(node: Any) -> None:
    """Every object schema of the contract gets ``additionalProperties: false``, in place."""
    if isinstance(node, dict):
        if node.get("type") == "object" and "additionalProperties" not in node:
            node["additionalProperties"] = False
        for child in node.values():
            forbid_extra_properties(child)
    elif isinstance(node, list):
        for child in node:
            forbid_extra_properties(child)


def declared_operations(contract: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (method.upper(), path): operation
        for path, item in contract["paths"].items()
        for method, operation in item.items()
        if method in HTTP_METHODS
    }


def error_codes(contract: dict[str, Any], schema: dict[str, Any]) -> set[str | None]:
    """The ``code`` values a response schema allows; ``None`` when it has no ``code`` (success)."""
    if "$ref" in schema:
        node: Any = contract
        for part in schema["$ref"].removeprefix("#/").split("/"):
            node = node[part]
        return error_codes(contract, node)
    variants = schema.get("anyOf") or schema.get("oneOf")
    if variants:
        return set().union(*(error_codes(contract, variant) for variant in variants))
    code = schema.get("properties", {}).get("code")
    return set(code["enum"]) if code else {None}


def declared_cases(contract: dict[str, Any]) -> set[tuple[str, str, int, str | None]]:
    """Every (method, path, status, error code) the contract declares; code is None on success."""
    cases = set()
    for (method, path), operation in declared_operations(contract).items():
        for status, response in operation["responses"].items():
            schema = response.get("content", {}).get("application/json", {}).get("schema", {})
            for code in error_codes(contract, schema):
                cases.add((method, path, int(status), code))
    return cases


@pytest.fixture(scope="module")
def contract() -> dict[str, Any]:
    return load_contract()


@pytest.fixture(scope="module")
def openapi(contract: dict[str, Any]) -> OpenAPI:
    strict = copy.deepcopy(contract)
    forbid_extra_properties(strict)
    return OpenAPI.from_dict(strict)


@dataclass(frozen=True)
class Exchange:
    method: str
    path: str  # the contract's path template, e.g. /api/event-types/{id}
    status: int
    code: str | None
    body: Any


class Api:
    """The real app behind a client that checks every exchange against the contract."""

    def __init__(self, client: TestClient, openapi: OpenAPI, contract: dict[str, Any]) -> None:
        self.client = client
        self.openapi = openapi
        self.operations = declared_operations(contract)

    def call(
        self,
        method: str,
        template: str,
        body: dict[str, Any] | None = None,
        *,
        request_is_valid: bool = True,
        **path_params: str,
    ) -> Exchange:
        """Send one request. ``request_is_valid=False`` expects the contract to reject the body."""
        assert (method, template) in self.operations, f"{method} {template} is not in the contract"
        url = template.format(**path_params)
        payload = None if body is None else json.dumps(body).encode()
        request = MockRequest(SERVER, method, url, data=payload)
        if request_is_valid:
            self.openapi.validate_request(request)
        else:
            with pytest.raises(OpenAPIError):
                self.openapi.validate_request(request)

        response = self.client.request(method, url, content=payload, headers=_json_headers(payload))

        answer = MockResponse(
            response.content,
            status_code=response.status_code,
            content_type=response.headers.get("content-type", "").lower(),
        )
        # Raises when the status is not declared for the operation or the body breaks the schema.
        self.openapi.validate_response(request, answer)
        data = response.json()
        code = data.get("code") if isinstance(data, dict) else None
        return Exchange(method, template, response.status_code, code, data)

    def create_event_type(self, slug: str = "intro", minutes: int = 30) -> dict[str, Any]:
        body = {"id": slug, "name": "Intro", "description": "Hi", "durationMinutes": minutes}
        exchange = self.call("POST", "/api/admin/event-types", body)
        assert exchange.status == 201
        return exchange.body

    def book(self, slug: str = "intro", start: str = "2026-11-06T10:00:00+03:00") -> Exchange:
        body = {
            "eventTypeId": slug,
            "start": start,
            "guestName": "Ada Lovelace",
            "guestEmail": "ada@example.com",
        }
        return self.call("POST", "/api/bookings", body)


def _json_headers(payload: bytes | None) -> dict[str, str]:
    return {} if payload is None else {"content-type": "application/json"}


ScenarioRun = Callable[[ClientFactory, Callable[[TestClient], Api], Path], Exchange]


@dataclass(frozen=True)
class Scenario:
    method: str
    path: str
    status: int
    code: str | None
    run: ScenarioRun

    @property
    def id(self) -> str:
        return f"{self.method} {self.path} {self.status} {self.code or ''}".strip()


SCENARIOS: list[Scenario] = []


def scenario(
    method: str, path: str, status: int, code: str | None = None
) -> Callable[[ScenarioRun], ScenarioRun]:
    def register(run: ScenarioRun) -> ScenarioRun:
        SCENARIOS.append(Scenario(method, path, status, code, run))
        return run

    return register


# --- scenarios: each returns the exchange that produced the declared status --------------------


@scenario("GET", "/health", 200)
def health(make_client, wrap, tmp_path):
    return wrap(make_client(now=NOW)).call("GET", "/health")


@scenario("GET", "/api/calendar", 200)
def calendar(make_client, wrap, tmp_path):
    return wrap(make_client(now=NOW)).call("GET", "/api/calendar")


@scenario("GET", "/api/event-types", 200)
def list_event_types(make_client, wrap, tmp_path):
    api = wrap(make_client(now=NOW))
    api.create_event_type()
    return api.call("GET", "/api/event-types")


@scenario("GET", "/api/event-types/{id}", 200)
def get_event_type(make_client, wrap, tmp_path):
    api = wrap(make_client(now=NOW))
    api.create_event_type()
    return api.call("GET", "/api/event-types/{id}", id="intro")


@scenario("GET", "/api/event-types/{id}", 404, "event_type_not_found")
def get_missing_event_type(make_client, wrap, tmp_path):
    return wrap(make_client(now=NOW)).call("GET", "/api/event-types/{id}", id="nope")


@scenario("GET", "/api/event-types/{id}/slots", 200)
def get_slots(make_client, wrap, tmp_path):
    api = wrap(make_client(now=NOW))
    api.create_event_type()
    api.book()
    return api.call("GET", "/api/event-types/{id}/slots", id="intro")


@scenario("GET", "/api/event-types/{id}/slots", 404, "event_type_not_found")
def get_slots_of_missing_event_type(make_client, wrap, tmp_path):
    return wrap(make_client(now=NOW)).call("GET", "/api/event-types/{id}/slots", id="nope")


@scenario("POST", "/api/admin/event-types", 201)
def create_event_type(make_client, wrap, tmp_path):
    body = {"id": "intro", "name": "Intro call", "durationMinutes": 30}
    return wrap(make_client(now=NOW)).call("POST", "/api/admin/event-types", body)


@scenario("POST", "/api/admin/event-types", 409, "event_type_exists")
def create_duplicate_event_type(make_client, wrap, tmp_path):
    api = wrap(make_client(now=NOW))
    api.create_event_type()
    body = {"id": "intro", "name": "Again", "durationMinutes": 15}
    return api.call("POST", "/api/admin/event-types", body)


@scenario("POST", "/api/admin/event-types", 422, "validation_error")
def create_invalid_event_type(make_client, wrap, tmp_path):
    body = {"id": "Not A Slug", "name": "", "durationMinutes": 7}
    return wrap(make_client(now=NOW)).call(
        "POST", "/api/admin/event-types", body, request_is_valid=False
    )


@scenario("POST", "/api/admin/event-types", 503, "service_busy")
def create_event_type_while_the_database_is_locked(make_client, wrap, tmp_path):
    database = tmp_path / "busy.db"
    api = wrap(make_client(now=NOW, database_path=database, lock_timeout_seconds=0.2))
    other = sqlite3.connect(database, isolation_level=None, check_same_thread=False)
    other.execute("BEGIN IMMEDIATE")  # another server process holds the write lock
    try:
        body = {"id": "intro", "name": "Intro call", "durationMinutes": 30}
        return api.call("POST", "/api/admin/event-types", body)
    finally:
        other.execute("ROLLBACK")
        other.close()


@scenario("POST", "/api/bookings", 201)
def create_booking(make_client, wrap, tmp_path):
    api = wrap(make_client(now=NOW))
    api.create_event_type()
    return api.book()


@scenario("POST", "/api/bookings", 409, "slot_taken")
def book_a_taken_slot(make_client, wrap, tmp_path):
    api = wrap(make_client(now=NOW))
    api.create_event_type()
    assert api.book().status == 201
    return api.book()


@scenario("POST", "/api/bookings", 422, "validation_error")
def create_invalid_booking(make_client, wrap, tmp_path):
    body = {"eventTypeId": "intro", "start": "tomorrow", "guestName": "", "guestEmail": "x"}
    return wrap(make_client(now=NOW)).call("POST", "/api/bookings", body, request_is_valid=False)


@scenario("POST", "/api/bookings", 422, "invalid_slot")
def book_an_off_grid_start(make_client, wrap, tmp_path):
    api = wrap(make_client(now=NOW))
    api.create_event_type()
    return api.book(start="2026-11-06T10:10:00+03:00")


@scenario("POST", "/api/bookings", 503, "service_busy")
def book_while_the_database_is_locked(make_client, wrap, tmp_path):
    database = tmp_path / "busy.db"
    api = wrap(make_client(now=NOW, database_path=database, lock_timeout_seconds=0.2))
    api.create_event_type()
    other = sqlite3.connect(database, isolation_level=None, check_same_thread=False)
    other.execute("BEGIN IMMEDIATE")  # another server process holds the write lock
    try:
        return api.book()
    finally:
        other.execute("ROLLBACK")
        other.close()


@scenario("GET", "/api/admin/bookings", 200)
def list_bookings(make_client, wrap, tmp_path):
    api = wrap(make_client(now=NOW))
    api.create_event_type()
    api.book()
    return api.call("GET", "/api/admin/bookings")


# --- tests --------------------------------------------------------------------------------------


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda item: item.id)
def test_the_app_answers_as_the_contract_declares(
    scenario: Scenario,
    make_client: ClientFactory,
    openapi: OpenAPI,
    contract: dict[str, Any],
    tmp_path: Path,
) -> None:
    def wrap(client: TestClient) -> Api:
        return Api(client, openapi, contract)

    exchange = scenario.run(make_client, wrap, tmp_path)

    assert (exchange.method, exchange.path, exchange.status, exchange.code) == (
        scenario.method,
        scenario.path,
        scenario.status,
        scenario.code,
    )


def test_every_declared_status_has_a_scenario(contract: dict[str, Any]) -> None:
    covered = {(item.method, item.path, item.status, item.code) for item in SCENARIOS}

    declared = declared_cases(contract)
    assert declared - covered == set(), "the contract declares responses no scenario exercises"
    assert covered - declared == set(), "scenarios exercise responses the contract does not declare"


def test_the_app_implements_exactly_the_contracts_operations(
    client: TestClient, contract: dict[str, Any]
) -> None:
    implemented = {
        (method.upper(), path)
        for path, item in client.get("/openapi.json").json()["paths"].items()
        for method in item
        if method in HTTP_METHODS
    }

    assert implemented == set(declared_operations(contract))


def test_the_apps_own_schema_declares_the_contracts_statuses(
    client: TestClient, contract: dict[str, Any]
) -> None:
    def statuses(document: dict[str, Any]) -> dict[tuple[str, str], set[str]]:
        return {
            (method.upper(), path): set(operation["responses"])
            for path, item in document["paths"].items()
            for method, operation in item.items()
            if method in HTTP_METHODS
        }

    assert statuses(client.get("/openapi.json").json()) == statuses(contract)
