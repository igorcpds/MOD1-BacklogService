import json
import threading
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy.orm import Session

from backlog_service.config import Settings
from backlog_service.database import create_database_engine, init_schema
from backlog_service.repository import StoryRepository
from backlog_service.service import StoriesService


@pytest.fixture
def access_payload():
    role_permissions = {
        "developer": [
            "project:read",
            "project:members:read",
            "backlog:read",
            "backlog:update_status",
        ],
        "product_owner": [
            "project:read",
            "project:update",
            "project:members:read",
            "backlog:read",
            "backlog:create",
            "backlog:update",
            "backlog:update_status",
        ],
        "project_manager": [
            "project:read",
            "project:update",
            "project:members:read",
            "project:members:manage",
            "backlog:read",
            "backlog:create",
            "backlog:update",
            "backlog:update_status",
        ],
        "owner": [
            "project:read",
            "project:update",
            "project:delete",
            "project:members:read",
            "project:members:manage",
            "backlog:read",
            "backlog:create",
            "backlog:update",
            "backlog:update_status",
        ],
    }

    def payload(project_id, user_id, *, roles=("owner",)):
        return {
            "project_id": str(project_id),
            "user_id": str(user_id),
            "is_owner": roles == ("owner",) or roles == ["owner"],
            "roles": sorted(roles),
            "permissions": sorted({p for role in roles for p in role_permissions[role]}),
        }

    return payload


@pytest.fixture
def project_id():
    return UUID("11111111-1111-4111-8111-111111111111")


@pytest.fixture
def actor_id():
    return UUID("22222222-2222-4222-8222-222222222222")


@pytest.fixture
def settings(tmp_path):
    return Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'stories.db'}")


@pytest.fixture
def engine(settings):
    engine = create_database_engine(settings)
    init_schema(engine, settings.database_schema)
    yield engine
    engine.dispose()


@pytest.fixture
def service(engine):
    with Session(engine, expire_on_commit=False) as session:
        yield StoriesService(
            StoryRepository(session), clock=lambda: datetime(2026, 10, 11, tzinfo=UTC)
        )


@pytest.fixture
def issuer():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    public.update(kid="test-key", alg="RS256", use="sig")
    state = {"payload": {"keys": [public]}, "status": 200, "requests": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state["requests"] += 1
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(state["payload"]).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    owner = uuid4()

    def token(*, sub=None, updates=None, omit=(), headers=None, signing_key=None):
        now = int(time.time())
        claims = dict(
            sub=str(sub or owner),
            iss="mod1-auth-local",
            aud="engenharia-software-api",
            iat=now,
            exp=now + 1800,
            jti=str(uuid4()),
        )
        claims.update(updates or {})
        for name in omit:
            claims.pop(name)
        return jwt.encode(
            claims,
            signing_key or key,
            algorithm="RS256",
            headers={"kid": "test-key", "typ": "JWT", **(headers or {})},
        )

    yield {
        "key": key,
        "state": state,
        "token": token,
        "owner": owner,
        "settings": Settings(
            database_url="sqlite:///:memory:",
            jwks_url=f"http://127.0.0.1:{server.server_port}/jwks",
            _env_file=None,
        ),
    }
    server.shutdown()
    server.server_close()
    thread.join()
