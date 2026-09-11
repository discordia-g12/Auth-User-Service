import uuid

from app.db.session import AsyncSessionLocal
from app.models.user import User

# NOTE: UserProfile is intentionally not tested here — its table (user_profiles)
# doesn't exist yet in the current migration (23753b693bdd_initial.py), and
# `is_suspended` is missing from the `users` table too. Both are a pre-existing
# model/migration drift, out of scope for the CI/CD issue this test file was
# added for. Tracked separately; do not add coverage for them until the
# migration is fixed, or these tests will fail against a freshly-migrated DB.


async def test_user_default_values():
    async with AsyncSessionLocal() as session:
        user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="hashed")
        session.add(user)
        await session.flush()

        assert uuid.UUID(user.id)
        assert user.is_active is True

        await session.rollback()
