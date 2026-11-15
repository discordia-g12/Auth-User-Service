import json

import httpx
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.clients.auth0_management import Auth0ManagementClient
from app.clients.suspension_denylist import SuspensionDenylist, email_key, identity_key
from app.exceptions import IdentityProviderUnavailableError, SuspensionDenylistUnavailableError

# ---------- Auth0 Management API ----------


class Auth0Stub:
    def __init__(self, patch_status: int = 200, token_status: int = 200):
        self.patch_status = patch_status
        self.token_status = token_status
        self.token_requests = 0
        self.patches: list[tuple[str, dict, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/token":
            self.token_requests += 1
            assert json.loads(request.content)["grant_type"] == "client_credentials"
            return httpx.Response(self.token_status, json={"access_token": "mgmt-token", "expires_in": 3600})
        path = request.url.raw_path.decode()
        self.patches.append((path, json.loads(request.content), request.headers["Authorization"]))
        return httpx.Response(self.patch_status, json={})


def _client(stub: Auth0Stub, secret: str = "s3cret", clock=lambda: 0.0) -> Auth0ManagementClient:
    return Auth0ManagementClient(
        domain="tenant.auth0.com",
        client_id="m2m",
        client_secret=secret,
        transport=httpx.MockTransport(stub),
        clock=clock,
    )


@pytest.mark.asyncio
async def test_blocks_user_with_management_token():
    stub = Auth0Stub()

    await _client(stub).set_blocked("google-oauth2|1", True)

    [(path, body, auth)] = stub.patches
    assert path == "/api/v2/users/google-oauth2%7C1"
    assert body == {"blocked": True}
    assert auth == "Bearer mgmt-token"


@pytest.mark.asyncio
async def test_reuses_token_until_it_expires():
    stub = Auth0Stub()
    now = [0.0]
    client = _client(stub, clock=lambda: now[0])

    await client.set_blocked("auth0|1", True)
    await client.set_blocked("auth0|2", True)
    assert stub.token_requests == 1

    now[0] = 3600.0
    await client.set_blocked("auth0|3", True)
    assert stub.token_requests == 2


@pytest.mark.asyncio
async def test_identity_unknown_to_auth0_is_skipped():
    await _client(Auth0Stub(patch_status=404)).set_blocked("auth0|gone", True)


@pytest.mark.asyncio
@pytest.mark.parametrize("stub", [Auth0Stub(patch_status=500), Auth0Stub(token_status=401)])
async def test_auth0_errors_are_503(stub):
    with pytest.raises(IdentityProviderUnavailableError):
        await _client(stub).set_blocked("auth0|1", True)


@pytest.mark.asyncio
async def test_missing_credentials_is_503():
    with pytest.raises(IdentityProviderUnavailableError):
        await _client(Auth0Stub(), secret="").set_blocked("auth0|1", True)


@pytest.mark.asyncio
async def test_unreachable_auth0_is_503():
    def boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = Auth0ManagementClient(
        domain="tenant.auth0.com", client_id="m2m", client_secret="s", transport=httpx.MockTransport(boom)
    )
    with pytest.raises(IdentityProviderUnavailableError):
        await client.set_blocked("auth0|1", True)


# ---------- Lista de bloqueados en el Redis del Gateway ----------


class FakePipeline:
    def __init__(self, redis: "FakeRedis"):
        self.redis = redis
        self.ops: list[tuple[str, str, int | None]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def set(self, key: str, value: str, ex: int | None = None):
        self.ops.append((key, value, ex))

    async def execute(self):
        if self.redis.fail:
            raise RedisConnectionError("down")
        for key, _value, ex in self.ops:
            self.redis.store[key] = ex


class FakeRedis:
    def __init__(self):
        self.store: dict[str, int | None] = {}
        self.fail = False

    def pipeline(self, transaction: bool = True):
        return FakePipeline(self)

    async def delete(self, *keys: str):
        if self.fail:
            raise RedisConnectionError("down")
        for key in keys:
            self.store.pop(key, None)


def test_key_format_matches_the_gateway():
    # Gateway/auth0_validator.lua busca exactamente estas claves
    assert identity_key("auth0|1") == "suspended:sub:auth0|1"
    assert email_key("  Ana@Mail.COM ") == "suspended:email:ana@mail.com"


@pytest.mark.asyncio
async def test_identities_expire_with_the_token_but_the_email_stays():
    redis = FakeRedis()

    await SuspensionDenylist(redis, ttl_seconds=900).add(["auth0|1", "google-oauth2|2"], "Ana@mail.com")

    assert redis.store == {
        "suspended:sub:auth0|1": 900,
        "suspended:sub:google-oauth2|2": 900,
        "suspended:email:ana@mail.com": None,
    }


@pytest.mark.asyncio
async def test_remove_deletes_every_key():
    redis = FakeRedis()
    denylist = SuspensionDenylist(redis, ttl_seconds=900)
    await denylist.add(["auth0|1"], "ana@mail.com")

    await denylist.remove(["auth0|1"], "ana@mail.com")

    assert redis.store == {}


@pytest.mark.asyncio
async def test_redis_errors_are_503():
    redis = FakeRedis()
    redis.fail = True
    denylist = SuspensionDenylist(redis, ttl_seconds=900)

    with pytest.raises(SuspensionDenylistUnavailableError):
        await denylist.add(["auth0|1"], "ana@mail.com")
    with pytest.raises(SuspensionDenylistUnavailableError):
        await denylist.remove(["auth0|1"], "ana@mail.com")
