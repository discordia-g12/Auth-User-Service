async def test_read_root(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Welcome to Auth User Service API"}


async def test_livez(client):
    response = await client.get("/livez")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


async def test_readyz_with_db_up(client):
    response = await client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
