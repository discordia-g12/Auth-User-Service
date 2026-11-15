from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import CurrentUser, DbSession
from app.schemas.problem import ProblemDetails
from app.schemas.social import (
    FriendAccepted,
    FriendRequestCreate,
    FriendRequestResponse,
    FriendRequestSent,
    FriendRequestsResponse,
    PublicProfile,
)
from app.services.social_service import SocialService

# Las rutas /me/... se declaran antes que /{user_id}/...: "me" no es un id
router = APIRouter(prefix="/users", tags=["Social"])

UNAUTHENTICATED = {status.HTTP_401_UNAUTHORIZED: {"model": ProblemDetails, "description": "Unauthenticated identity"}}
REQUEST_NOT_FOUND = {
    **UNAUTHENTICATED,
    status.HTTP_404_NOT_FOUND: {"model": ProblemDetails, "description": "No such pending request for this user"},
}


def get_social_service(db: DbSession) -> SocialService:
    return SocialService(db)


Service = Annotated[SocialService, Depends(get_social_service)]


@router.get(
    "/me/friends",
    response_model=list[PublicProfile],
    summary="List own friends",
    responses=UNAUTHENTICATED,
)
async def list_friends(actor: CurrentUser, service: Service) -> list[PublicProfile]:
    return await service.list_friends(actor)


@router.delete(
    "/me/friends/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a friend",
    responses=UNAUTHENTICATED,
)
async def remove_friend(user_id: str, actor: CurrentUser, service: Service) -> None:
    await service.remove_friend(actor, user_id)


@router.get(
    "/me/friend-requests",
    response_model=FriendRequestsResponse,
    summary="List pending friend requests, sent and received",
    responses=UNAUTHENTICATED,
)
async def list_friend_requests(actor: CurrentUser, service: Service) -> FriendRequestsResponse:
    return await service.list_friend_requests(actor)


@router.post(
    "/me/friend-requests",
    status_code=status.HTTP_201_CREATED,
    response_model=FriendRequestResponse | FriendRequestSent,
    summary="Send a friend request",
    description=(
        "By username, @username or email (`target`), or by `user_id` from a profile. If the other user already "
        "sent one, both are accepted and `user.relationship` comes back as `friend`. By email, or if there is a "
        "block, the answer is always 202 and confirms nothing about the other account."
    ),
    responses={
        **UNAUTHENTICATED,
        status.HTTP_202_ACCEPTED: {"model": FriendRequestSent, "description": "Answer that confirms nothing"},
        status.HTTP_404_NOT_FOUND: {"model": ProblemDetails, "description": "Unknown username or user_id"},
        status.HTTP_409_CONFLICT: {"model": ProblemDetails, "description": "Already friends or already pending"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ProblemDetails, "description": "Invalid payload or yourself"},
    },
)
async def send_friend_request(
    payload: FriendRequestCreate, actor: CurrentUser, service: Service, response: Response
) -> FriendRequestResponse | FriendRequestSent:
    created = await service.send_friend_request(actor, payload)
    if created is None:
        response.status_code = status.HTTP_202_ACCEPTED
        return FriendRequestSent()
    return created


@router.post(
    "/me/friend-requests/{request_id}/accept",
    response_model=FriendAccepted,
    summary="Accept a received friend request",
    responses=REQUEST_NOT_FOUND,
)
async def accept_friend_request(request_id: str, actor: CurrentUser, service: Service) -> FriendAccepted:
    return await service.accept_friend_request(actor, request_id)


@router.post(
    "/me/friend-requests/{request_id}/decline",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Decline a received friend request",
    responses=REQUEST_NOT_FOUND,
)
async def decline_friend_request(request_id: str, actor: CurrentUser, service: Service) -> None:
    await service.decline_friend_request(actor, request_id)


@router.delete(
    "/me/friend-requests/{request_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel a friend request you sent",
    responses=REQUEST_NOT_FOUND,
)
async def cancel_friend_request(request_id: str, actor: CurrentUser, service: Service) -> None:
    await service.cancel_friend_request(actor, request_id)


@router.get(
    "/me/blocks",
    response_model=list[PublicProfile],
    summary="List the users you blocked",
    responses=UNAUTHENTICATED,
)
async def list_blocks(actor: CurrentUser, service: Service) -> list[PublicProfile]:
    return await service.list_blocks(actor)


@router.put(
    "/me/blocks/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Block a user",
    description="Idempotent. Also removes the friendship and the pending friend requests between both users.",
    responses={
        **UNAUTHENTICATED,
        status.HTTP_404_NOT_FOUND: {"model": ProblemDetails, "description": "Unknown user"},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ProblemDetails, "description": "Tried to block yourself"},
    },
)
async def block_user(user_id: str, actor: CurrentUser, service: Service) -> None:
    await service.block(actor, user_id)


@router.delete(
    "/me/blocks/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unblock a user",
    description="Idempotent.",
    responses=UNAUTHENTICATED,
)
async def unblock_user(user_id: str, actor: CurrentUser, service: Service) -> None:
    await service.unblock(actor, user_id)


@router.get(
    "/{user_id}/profile",
    response_model=PublicProfile,
    summary="Get a user's public profile",
    description="Never includes the email or anything about direct messages. 404 if suspended or unknown.",
    responses={
        **UNAUTHENTICATED,
        status.HTTP_404_NOT_FOUND: {"model": ProblemDetails, "description": "Profile not available"},
    },
)
async def get_public_profile(user_id: str, actor: CurrentUser, service: Service) -> PublicProfile:
    return await service.get_profile(actor, user_id)
