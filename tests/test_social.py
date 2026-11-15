"""Grafo social: perfil público (#36), bloqueo (#43) y amistades (parte de #42)."""

from urllib.parse import quote

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import FriendRequestAlreadyPendingError
from app.models.friend_request import FriendRequest
from app.models.friendship import Friendship, ordered_pair
from app.models.outbox import OutboxEvent
from app.models.user import User
from app.models.user_block import UserBlock
from app.models.user_profile import UserProfile
from app.repositories.social_repository import SocialRepository
from app.repositories.user_repository import UserRepository
from app.schemas.social import FriendRequestCreate
from app.services.social_service import SocialService

ANA = "auth0|ana"
BETO = "auth0|beto"
CAMI = "google-oauth2|cami"
SUSPENDED = "auth0|suspendido"
ANA_ALIAS = "google-oauth2|ana-federada"

REQUESTS = "/api/v1/users/me/friend-requests"
FRIENDS = "/api/v1/users/me/friends"
BLOCKS = "/api/v1/users/me/blocks"


def as_user(user_id: str) -> dict[str, str]:
    return {"X-User-Id": user_id, "X-User-Email-Verified": "false"}


def profile_url(user_id: str) -> str:
    return f"/api/v1/users/{quote(user_id, safe='')}/profile"


def block_url(user_id: str) -> str:
    return f"{BLOCKS}/{quote(user_id, safe='')}"


def friend_url(user_id: str) -> str:
    return f"{FRIENDS}/{quote(user_id, safe='')}"


async def send(client: AsyncClient, actor: str, **payload):
    return await client.post(REQUESTS, json=payload, headers=as_user(actor))


async def befriend(client: AsyncClient, user_a: str, user_b: str) -> None:
    created = await send(client, user_a, user_id=user_b)
    assert created.status_code == 201
    accepted = await client.post(f"{REQUESTS}/{created.json()['id']}/accept", headers=as_user(user_b))
    assert accepted.status_code == 200


async def count(db: AsyncSession, model) -> int:
    db.expire_all()
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def relationship_of(client: AsyncClient, viewer: str, other: str) -> str:
    return (await client.get(profile_url(other), headers=as_user(viewer))).json()["relationship"]


@pytest_asyncio.fixture(autouse=True)
async def users(db_session: AsyncSession):
    for user_id, username in ((ANA, "ana"), (BETO, "beto"), (CAMI, "cami")):
        db_session.add(User(id=user_id, email=f"{username}@discordia.lol", is_active=True, is_suspended=False))
        db_session.add(
            UserProfile(
                user_id=user_id,
                username=username,
                display_name=username.title(),
                bio=f"bio de {username}",
                avatar_url=f"https://cdn/{username}.webp",
                custom_status="estudiando",
            )
        )
    db_session.add(User(id=SUSPENDED, email="sus@discordia.lol", is_active=True, is_suspended=True))
    db_session.add(UserProfile(user_id=SUSPENDED, username="suspendido", bio="no se ve", avatar_url="https://cdn/s"))
    db_session.add(
        OutboxEvent(
            aggregate_type="user_identity_alias",
            aggregate_id=ANA_ALIAS,
            event_type="user.identity_linked",
            payload={"primary_user_id": ANA},
        )
    )
    await db_session.commit()


class TestPublicProfile:
    async def test_shows_public_fields_and_never_the_email(self, client: AsyncClient):
        res = await client.get(profile_url(BETO), headers=as_user(ANA))

        assert res.status_code == 200
        data = res.json()
        assert data["user_id"] == BETO
        assert data["username"] == "beto"
        assert data["display_name"] == "Beto"
        assert data["bio"] == "bio de beto"
        assert data["avatar_url"] == "https://cdn/beto.webp"
        assert data["custom_status"] == "estudiando"
        assert data["relationship"] == "none"
        assert data["friend_request_id"] is None
        assert "email" not in data
        assert "beto@discordia.lol" not in res.text

    @pytest.mark.parametrize("target", [SUSPENDED, "auth0|no-existe"])
    async def test_suspended_or_unknown_is_404(self, client: AsyncClient, target: str):
        res = await client.get(profile_url(target), headers=as_user(ANA))

        assert res.status_code == 404
        assert res.json()["detail"] == "Profile not available."

    async def test_unauthenticated_is_401(self, client: AsyncClient):
        assert (await client.get(profile_url(BETO))).status_code == 401

    async def test_id_with_pipe_works_url_encoded_and_raw(self, client: AsyncClient):
        encoded = await client.get(f"/api/v1/users/{CAMI.replace('|', '%7C')}/profile", headers=as_user(ANA))
        raw = await client.get(f"/api/v1/users/{CAMI}/profile", headers=as_user(ANA))

        assert encoded.status_code == raw.status_code == 200
        assert encoded.json()["user_id"] == CAMI

    async def test_me_is_not_taken_for_an_id(self, client: AsyncClient):
        res = await client.get(FRIENDS, headers=as_user(ANA))
        assert res.status_code == 200
        assert res.json() == []

    async def test_alias_of_the_target_resolves_to_the_canonical_user(self, client: AsyncClient):
        res = await client.get(profile_url(ANA_ALIAS), headers=as_user(BETO))
        assert res.json()["user_id"] == ANA

    async def test_null_byte_in_id_is_404(self, client: AsyncClient):
        assert (await client.get("/api/v1/users/a%00b/profile", headers=as_user(ANA))).status_code == 404

    async def test_relationship_follows_each_state(self, client: AsyncClient):
        created = (await send(client, ANA, user_id=BETO)).json()
        request_id = created["id"]

        sent = (await client.get(profile_url(BETO), headers=as_user(ANA))).json()
        received = (await client.get(profile_url(ANA), headers=as_user(BETO))).json()
        assert (sent["relationship"], sent["friend_request_id"]) == ("request_sent", request_id)
        assert (received["relationship"], received["friend_request_id"]) == ("request_received", request_id)

        await client.post(f"{REQUESTS}/{request_id}/accept", headers=as_user(BETO))
        assert await relationship_of(client, ANA, BETO) == "friend"

        await client.put(block_url(BETO), headers=as_user(ANA))
        assert await relationship_of(client, ANA, BETO) == "blocked"

    async def test_being_blocked_shows_as_none(self, client: AsyncClient):
        await client.put(block_url(ANA), headers=as_user(BETO))

        assert await relationship_of(client, ANA, BETO) == "none"


class TestCallerIdentity:
    async def test_alias_acts_as_the_canonical_user(self, client: AsyncClient, db_session: AsyncSession):
        res = await send(client, ANA_ALIAS, user_id=BETO)

        assert res.status_code == 201
        stored = (await db_session.execute(select(FriendRequest))).scalar_one()
        assert stored.requester_id == ANA

    async def test_unlinked_identity_is_linked_by_verified_email(self, client: AsyncClient, db_session: AsyncSession):
        new_alias = "windowslive|ana"
        headers = {"X-User-Id": new_alias, "X-User-Email": "ana@discordia.lol", "X-User-Email-Verified": "true"}

        assert (await client.get(FRIENDS, headers=headers)).status_code == 200
        assert await UserRepository().resolve_canonical_user(db_session, new_alias) is not None

    async def test_unverified_email_does_not_link(self, client: AsyncClient):
        headers = {"X-User-Id": "windowslive|x", "X-User-Email": "ana@discordia.lol"}
        assert (await client.get(FRIENDS, headers=headers)).status_code == 404

    async def test_suspended_caller_is_403(self, client: AsyncClient):
        res = await client.get(FRIENDS, headers=as_user(SUSPENDED))

        assert res.status_code == 403
        assert res.json()["type"].endswith("/account-suspended")


class TestSendFriendRequest:
    @pytest.mark.parametrize("target", ["beto", "@beto"])
    async def test_by_username(self, client: AsyncClient, target: str):
        res = await send(client, ANA, target=target, message="  hola, te vi en el TP  ")

        assert res.status_code == 201
        data = res.json()
        assert data["message"] == "hola, te vi en el TP"
        assert data["user"]["user_id"] == BETO
        assert data["user"]["relationship"] == "request_sent"
        assert data["user"]["friend_request_id"] == data["id"]
        assert "email" not in data["user"]

    @pytest.mark.parametrize("target", ["BETO", "Beto", "@bEtO"])
    async def test_username_ignores_case(self, client: AsyncClient, target: str):
        res = await send(client, ANA, target=target)

        assert res.status_code == 201
        assert res.json()["user"]["user_id"] == BETO

    async def test_exact_username_wins_over_another_case(self, client: AsyncClient, db_session: AsyncSession):
        twin = "auth0|beto-mayuscula"
        db_session.add(User(id=twin, email="twin@discordia.lol", is_active=True, is_suspended=False))
        db_session.add(UserProfile(user_id=twin, username="BETO"))
        await db_session.commit()

        assert (await send(client, ANA, target="BETO")).json()["user"]["user_id"] == twin
        assert (await send(client, ANA, target="beto")).json()["user"]["user_id"] == BETO
        assert (await send(client, CAMI, target="Beto")).status_code == 201

    async def test_by_user_id(self, client: AsyncClient):
        assert (await send(client, ANA, user_id=BETO)).status_code == 201

    async def test_by_alias_of_the_target_stores_the_canonical_id(self, client: AsyncClient, db_session: AsyncSession):
        assert (await send(client, BETO, user_id=ANA_ALIAS)).status_code == 201
        assert (await db_session.execute(select(FriendRequest))).scalar_one().addressee_id == ANA

    async def test_by_email_is_202_and_creates_the_request(self, client: AsyncClient, db_session: AsyncSession):
        res = await send(client, ANA, target="BETO@discordia.lol")

        assert res.status_code == 202
        assert res.json() == {"status": "sent"}
        assert await count(db_session, FriendRequest) == 1

    async def test_unknown_email_is_the_same_202(self, client: AsyncClient, db_session: AsyncSession):
        res = await send(client, ANA, target="nadie@discordia.lol")

        assert res.status_code == 202
        assert res.json() == {"status": "sent"}
        assert await count(db_session, FriendRequest) == 0

    async def test_email_of_a_suspended_account_is_the_same_202(self, client: AsyncClient, db_session: AsyncSession):
        assert (await send(client, ANA, target="sus@discordia.lol")).status_code == 202
        assert await count(db_session, FriendRequest) == 0

    async def test_email_never_tells_a_friend_or_a_pending_request_apart(self, client: AsyncClient):
        await send(client, ANA, target="beto")
        assert (await send(client, ANA, target="beto@discordia.lol")).status_code == 202

        await befriend(client, ANA, CAMI)
        assert (await send(client, ANA, target="cami@discordia.lol")).status_code == 202

    @pytest.mark.parametrize("payload", [{"target": "nadie"}, {"user_id": "auth0|nadie"}, {"target": "suspendido"}])
    async def test_unknown_username_or_id_is_404(self, client: AsyncClient, payload: dict):
        assert (await send(client, ANA, **payload)).status_code == 404

    async def test_already_friends_is_409(self, client: AsyncClient):
        await befriend(client, ANA, BETO)
        assert (await send(client, ANA, target="beto")).status_code == 409

    async def test_duplicate_pending_is_409_and_keeps_one_row(self, client: AsyncClient, db_session: AsyncSession):
        await send(client, ANA, target="beto")

        assert (await send(client, ANA, target="beto")).status_code == 409
        assert await count(db_session, FriendRequest) == 1

    @pytest.mark.parametrize(
        "payload", [{"target": "ana"}, {"target": "ana@discordia.lol"}, {"user_id": ANA}, {"user_id": ANA_ALIAS}]
    )
    async def test_to_yourself_is_422(self, client: AsyncClient, payload: dict):
        assert (await send(client, ANA, **payload)).status_code == 422

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"message": "sin destino"},
            {"target": "beto", "user_id": BETO},
            {"target": ""},
            {"target": "beto", "message": "x" * 191},
        ],
    )
    async def test_invalid_payload_is_422(self, client: AsyncClient, payload: dict):
        res = await client.post(REQUESTS, json=payload, headers=as_user(ANA))
        assert res.status_code == 422

    async def test_message_of_190_is_allowed(self, client: AsyncClient):
        assert (await send(client, ANA, target="beto", message="x" * 190)).status_code == 201

    async def test_null_byte_is_400(self, client: AsyncClient):
        assert (await send(client, ANA, target="beto", message="a\x00b")).status_code == 400

    async def test_blank_message_is_stored_as_none(self, client: AsyncClient):
        assert (await send(client, ANA, target="beto", message="   ")).json()["message"] is None

    async def test_unauthenticated_is_401(self, client: AsyncClient):
        assert (await client.post(REQUESTS, json={"target": "beto"})).status_code == 401

    async def test_new_request_after_a_decline_is_allowed(self, client: AsyncClient):
        first = (await send(client, ANA, target="beto")).json()
        await client.post(f"{REQUESTS}/{first['id']}/decline", headers=as_user(BETO))

        assert (await send(client, ANA, target="beto")).status_code == 201


class TestCrossedRequests:
    async def test_inverse_pending_accepts_both(self, client: AsyncClient, db_session: AsyncSession):
        await send(client, ANA, target="beto")

        res = await send(client, BETO, target="ana")

        assert res.status_code == 201
        assert res.json()["user"]["relationship"] == "friend"
        assert res.json()["user"]["friend_request_id"] is None
        assert await count(db_session, Friendship) == 1
        statuses = (await db_session.execute(select(FriendRequest.status))).scalars().all()
        assert sorted(statuses) == ["accepted", "accepted"]
        listed = (await client.get(REQUESTS, headers=as_user(ANA))).json()
        assert listed == {"incoming": [], "outgoing": []}

    async def test_inverse_pending_by_email_is_still_202(self, client: AsyncClient, db_session: AsyncSession):
        await send(client, ANA, target="beto")

        assert (await send(client, BETO, target="ana@discordia.lol")).status_code == 202
        assert await count(db_session, Friendship) == 1


class TestRespondToFriendRequest:
    async def test_accept_returns_the_friend(self, client: AsyncClient):
        created = (await send(client, ANA, target="beto")).json()

        res = await client.post(f"{REQUESTS}/{created['id']}/accept", headers=as_user(BETO))

        assert res.status_code == 200
        assert res.json()["friend"]["user_id"] == ANA
        assert res.json()["friend"]["relationship"] == "friend"
        names = [f["username"] for f in (await client.get(FRIENDS, headers=as_user(ANA))).json()]
        assert names == ["beto"]

    async def test_double_accept_is_idempotent(self, client: AsyncClient, db_session: AsyncSession):
        created = (await send(client, ANA, target="beto")).json()
        url = f"{REQUESTS}/{created['id']}/accept"

        first = await client.post(url, headers=as_user(BETO))
        second = await client.post(url, headers=as_user(BETO))

        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()
        assert await count(db_session, Friendship) == 1

    async def test_accept_after_unfriending_is_404(self, client: AsyncClient):
        created = (await send(client, ANA, target="beto")).json()
        url = f"{REQUESTS}/{created['id']}/accept"
        await client.post(url, headers=as_user(BETO))
        await client.delete(friend_url(ANA), headers=as_user(BETO))

        assert (await client.post(url, headers=as_user(BETO))).status_code == 404

    @pytest.mark.parametrize("action", ["accept", "decline"])
    async def test_only_the_addressee_can_respond(self, client: AsyncClient, action: str):
        created = (await send(client, ANA, target="beto")).json()
        url = f"{REQUESTS}/{created['id']}/{action}"

        assert (await client.post(url, headers=as_user(ANA))).status_code == 404
        assert (await client.post(url, headers=as_user(CAMI))).status_code == 404

    async def test_unknown_id_is_404(self, client: AsyncClient):
        assert (await client.post(f"{REQUESTS}/no-existe/accept", headers=as_user(ANA))).status_code == 404

    async def test_decline_leaves_it_out_of_both_lists(self, client: AsyncClient):
        created = (await send(client, ANA, target="beto")).json()

        res = await client.post(f"{REQUESTS}/{created['id']}/decline", headers=as_user(BETO))

        assert res.status_code == 204
        assert (await client.get(REQUESTS, headers=as_user(BETO))).json()["incoming"] == []
        assert (await client.get(REQUESTS, headers=as_user(ANA))).json()["outgoing"] == []

    async def test_declined_cannot_be_accepted(self, client: AsyncClient):
        created = (await send(client, ANA, target="beto")).json()
        await client.post(f"{REQUESTS}/{created['id']}/decline", headers=as_user(BETO))

        res = await client.post(f"{REQUESTS}/{created['id']}/accept", headers=as_user(BETO))
        assert res.status_code == 404

    async def test_decline_twice_is_404(self, client: AsyncClient):
        created = (await send(client, ANA, target="beto")).json()
        url = f"{REQUESTS}/{created['id']}/decline"
        await client.post(url, headers=as_user(BETO))

        assert (await client.post(url, headers=as_user(BETO))).status_code == 404

    async def test_requester_cancels_their_own(self, client: AsyncClient):
        created = (await send(client, ANA, target="beto")).json()

        res = await client.delete(f"{REQUESTS}/{created['id']}", headers=as_user(ANA))

        assert res.status_code == 204
        assert (await client.get(REQUESTS, headers=as_user(BETO))).json()["incoming"] == []

    async def test_only_the_requester_can_cancel(self, client: AsyncClient):
        created = (await send(client, ANA, target="beto")).json()

        assert (await client.delete(f"{REQUESTS}/{created['id']}", headers=as_user(BETO))).status_code == 404

    async def test_accept_from_a_suspended_requester_is_404(self, client: AsyncClient, db_session: AsyncSession):
        created = (await send(client, ANA, target="beto")).json()
        (await db_session.get(User, ANA)).is_suspended = True
        await db_session.commit()

        res = await client.post(f"{REQUESTS}/{created['id']}/accept", headers=as_user(BETO))
        assert res.status_code == 404


class TestListFriendRequests:
    async def test_lists_incoming_and_outgoing_with_the_other_user(self, client: AsyncClient):
        await send(client, ANA, target="beto", message="dale")
        await send(client, CAMI, target="ana")

        data = (await client.get(REQUESTS, headers=as_user(ANA))).json()

        assert [r["user"]["username"] for r in data["outgoing"]] == ["beto"]
        assert data["outgoing"][0]["message"] == "dale"
        assert [r["user"]["username"] for r in data["incoming"]] == ["cami"]
        assert data["incoming"][0]["user"]["relationship"] == "request_received"

    async def test_hides_requests_from_a_suspended_account(self, client: AsyncClient, db_session: AsyncSession):
        await send(client, ANA, target="beto")
        (await db_session.get(User, ANA)).is_suspended = True
        await db_session.commit()

        assert (await client.get(REQUESTS, headers=as_user(BETO))).json()["incoming"] == []


class TestFriends:
    async def test_list_is_sorted_and_public_only(self, client: AsyncClient):
        await befriend(client, ANA, CAMI)
        await befriend(client, BETO, ANA)

        res = await client.get(FRIENDS, headers=as_user(ANA))

        assert [f["username"] for f in res.json()] == ["beto", "cami"]
        assert all(f["relationship"] == "friend" for f in res.json())
        assert "email" not in res.text

    async def test_friendship_is_stored_ordered(self, client: AsyncClient, db_session: AsyncSession):
        await befriend(client, BETO, ANA)

        row = (await db_session.execute(select(Friendship))).scalar_one()
        assert (row.user_low_id, row.user_high_id) == ordered_pair(ANA, BETO)

    async def test_remove_is_204_for_both_sides(self, client: AsyncClient):
        await befriend(client, ANA, BETO)

        res = await client.delete(friend_url(ANA), headers=as_user(BETO))

        assert res.status_code == 204
        assert (await client.get(FRIENDS, headers=as_user(ANA))).json() == []

    async def test_remove_is_idempotent(self, client: AsyncClient):
        assert (await client.delete(friend_url(BETO), headers=as_user(ANA))).status_code == 204
        assert (await client.delete(friend_url("auth0|nadie"), headers=as_user(ANA))).status_code == 204

    async def test_suspended_friend_keeps_only_the_name(self, client: AsyncClient, db_session: AsyncSession):
        await befriend(client, ANA, BETO)
        (await db_session.get(User, BETO)).is_suspended = True
        await db_session.commit()

        friend = (await client.get(FRIENDS, headers=as_user(ANA))).json()[0]

        assert friend["username"] == "beto"
        assert friend["avatar_url"] is None
        assert friend["bio"] is None
        assert friend["custom_status"] is None


class TestBlocks:
    async def test_block_is_204_and_listed(self, client: AsyncClient):
        res = await client.put(block_url(BETO), headers=as_user(ANA))

        assert res.status_code == 204
        blocked = (await client.get(BLOCKS, headers=as_user(ANA))).json()
        assert [b["username"] for b in blocked] == ["beto"]
        assert blocked[0]["relationship"] == "blocked"
        assert "email" not in blocked[0]

    async def test_block_is_idempotent(self, client: AsyncClient, db_session: AsyncSession):
        assert (await client.put(block_url(BETO), headers=as_user(ANA))).status_code == 204
        assert (await client.put(block_url(BETO), headers=as_user(ANA))).status_code == 204
        assert await count(db_session, UserBlock) == 1

    async def test_block_removes_friendship(self, client: AsyncClient):
        await befriend(client, ANA, BETO)

        await client.put(block_url(BETO), headers=as_user(ANA))

        assert (await client.get(FRIENDS, headers=as_user(ANA))).json() == []
        assert (await client.get(FRIENDS, headers=as_user(BETO))).json() == []

    @pytest.mark.parametrize("requester, addressee", [(ANA, BETO), (BETO, ANA)])
    async def test_block_cancels_pending_in_both_directions(
        self, client: AsyncClient, db_session: AsyncSession, requester: str, addressee: str
    ):
        await send(client, requester, user_id=addressee)

        await client.put(block_url(BETO), headers=as_user(ANA))

        status = (await db_session.execute(select(FriendRequest.status))).scalar_one()
        assert status == "canceled"
        for user in (ANA, BETO):
            assert (await client.get(REQUESTS, headers=as_user(user))).json() == {"incoming": [], "outgoing": []}

    async def test_block_is_atomic(self, client: AsyncClient, db_session: AsyncSession, monkeypatch):
        await befriend(client, ANA, BETO)

        async def boom(*_args, **_kwargs):
            raise RuntimeError("falla en mitad de la transacción")

        monkeypatch.setattr(SocialRepository, "resolve_pending_between", boom)

        with pytest.raises(RuntimeError):
            await client.put(block_url(BETO), headers=as_user(ANA))

        assert await count(db_session, UserBlock) == 0
        assert await count(db_session, Friendship) == 1

    async def test_blocked_user_request_looks_sent_and_creates_nothing(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        await client.put(block_url(ANA), headers=as_user(BETO))

        res = await send(client, ANA, target="beto")

        assert res.status_code == 202
        assert res.json() == {"status": "sent"}
        assert "block" not in res.text.lower()
        assert await count(db_session, FriendRequest) == 0

    async def test_blocker_request_is_202_and_creates_nothing(self, client: AsyncClient, db_session: AsyncSession):
        await client.put(block_url(BETO), headers=as_user(ANA))

        assert (await send(client, ANA, user_id=BETO)).status_code == 202
        assert await count(db_session, FriendRequest) == 0

    async def test_unblock_frees_the_relation_and_is_idempotent(self, client: AsyncClient):
        await client.put(block_url(BETO), headers=as_user(ANA))

        assert (await client.delete(block_url(BETO), headers=as_user(ANA))).status_code == 204
        assert (await client.delete(block_url(BETO), headers=as_user(ANA))).status_code == 204
        assert (await client.delete(block_url("auth0|nadie"), headers=as_user(ANA))).status_code == 204

        assert (await send(client, ANA, target="beto")).status_code == 201

    async def test_unblock_only_undoes_your_own_block(self, client: AsyncClient):
        await client.put(block_url(BETO), headers=as_user(ANA))

        await client.delete(block_url(ANA), headers=as_user(BETO))

        assert await relationship_of(client, ANA, BETO) == "blocked"

    async def test_block_by_alias_stores_canonical_ids(self, client: AsyncClient, db_session: AsyncSession):
        await client.put(block_url(ANA_ALIAS), headers=as_user(BETO))

        row = (await db_session.execute(select(UserBlock))).scalar_one()
        assert (row.blocker_id, row.blocked_id) == (BETO, ANA)

    async def test_block_unknown_is_404(self, client: AsyncClient):
        assert (await client.put(block_url("auth0|nadie"), headers=as_user(ANA))).status_code == 404

    @pytest.mark.parametrize("target", [ANA, ANA_ALIAS])
    async def test_block_yourself_is_422(self, client: AsyncClient, target: str):
        assert (await client.put(block_url(target), headers=as_user(ANA))).status_code == 422

    async def test_suspended_can_be_blocked_and_listed_by_name(self, client: AsyncClient):
        assert (await client.put(block_url(SUSPENDED), headers=as_user(ANA))).status_code == 204

        blocked = (await client.get(BLOCKS, headers=as_user(ANA))).json()[0]
        assert blocked["username"] == "suspendido"
        assert blocked["bio"] is None


class TestRaceBackstops:
    """Con Postgres, `lock_pair` serializa estos casos. Acá se comprueba la última barrera."""

    async def test_unique_index_rejects_a_second_pending(self, db_session: AsyncSession):
        db_session.add(FriendRequest(requester_id=ANA, addressee_id=BETO))
        await db_session.commit()
        db_session.add(FriendRequest(requester_id=ANA, addressee_id=BETO))

        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()

    async def test_unique_index_allows_a_resolved_duplicate(self, db_session: AsyncSession):
        db_session.add(FriendRequest(requester_id=ANA, addressee_id=BETO, status="declined"))
        db_session.add(FriendRequest(requester_id=ANA, addressee_id=BETO))
        await db_session.commit()

    @pytest.mark.parametrize("target, expected", [("beto", "conflict"), ("beto@discordia.lol", "sent")])
    async def test_lost_race_is_not_a_500(self, db_session: AsyncSession, monkeypatch, target: str, expected: str):
        """Ambos pedidos pasaron el chequeo a la vez: el segundo choca contra el índice."""
        ana = await db_session.get(User, ANA)
        db_session.add(FriendRequest(requester_id=ANA, addressee_id=BETO))
        await db_session.commit()

        async def nothing_pending(*_args):
            return None

        monkeypatch.setattr(SocialRepository, "get_pending_request", nothing_pending)
        service = SocialService(db_session)
        payload = FriendRequestCreate(target=target)

        if expected == "conflict":
            with pytest.raises(FriendRequestAlreadyPendingError):
                await service.send_friend_request(ana, payload)
        else:
            assert await service.send_friend_request(ana, payload) is None


class TestInternal:
    async def test_canonical_of_a_canonical_id(self, client: AsyncClient):
        res = await client.get(f"/internal/users/{quote(ANA, safe='')}/canonical")

        assert res.status_code == 200
        assert res.json() == {"user_id": ANA, "suspended": False}

    async def test_canonical_resolves_an_alias(self, client: AsyncClient):
        res = await client.get(f"/internal/users/{quote(ANA_ALIAS, safe='')}/canonical")

        assert res.json() == {"user_id": ANA, "suspended": False}

    async def test_canonical_reports_suspension(self, client: AsyncClient):
        res = await client.get(f"/internal/users/{quote(SUSPENDED, safe='')}/canonical")

        assert res.json() == {"user_id": SUSPENDED, "suspended": True}

    async def test_canonical_unknown_is_404(self, client: AsyncClient):
        assert (await client.get("/internal/users/nadie/canonical")).status_code == 404

    async def relations(self, client: AsyncClient, actor: str, other: str) -> dict:
        res = await client.get("/internal/relations", params={"actor": actor, "other": other})
        assert res.status_code == 200
        return res.json()

    async def test_relations_of_strangers(self, client: AsyncClient):
        assert await self.relations(client, ANA, BETO) == {
            "exists": True,
            "suspended": False,
            "friends": False,
            "blocked_by_actor": False,
            "blocked_by_other": False,
        }

    async def test_relations_of_friends_through_an_alias(self, client: AsyncClient):
        await befriend(client, ANA, BETO)

        assert (await self.relations(client, ANA_ALIAS, BETO))["friends"] is True
        assert (await self.relations(client, BETO, ANA_ALIAS))["friends"] is True

    async def test_relations_tell_who_blocked(self, client: AsyncClient):
        await client.put(block_url(BETO), headers=as_user(ANA))

        from_actor = await self.relations(client, ANA, BETO)
        from_other = await self.relations(client, BETO, ANA)

        assert (from_actor["blocked_by_actor"], from_actor["blocked_by_other"]) == (True, False)
        assert (from_other["blocked_by_actor"], from_other["blocked_by_other"]) == (False, True)

    async def test_relations_with_a_suspended_user(self, client: AsyncClient):
        assert (await self.relations(client, ANA, SUSPENDED))["suspended"] is True

    @pytest.mark.parametrize("actor, other", [(ANA, "nadie"), ("nadie", ANA)])
    async def test_relations_unknown_user(self, client: AsyncClient, actor: str, other: str):
        assert (await self.relations(client, actor, other))["exists"] is False

    async def test_relations_need_both_params(self, client: AsyncClient):
        assert (await client.get("/internal/relations", params={"actor": ANA})).status_code == 422

    async def test_internal_routes_are_not_under_the_public_prefix(self, client: AsyncClient):
        assert (await client.get("/api/v1/internal/relations", params={"actor": ANA, "other": BETO})).status_code == 404
