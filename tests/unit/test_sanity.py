import pytest


def test_pytest_sanity(tmp_db, mock_settings):
    assert tmp_db.exists()
    assert mock_settings.db_path == tmp_db


@pytest.mark.asyncio
async def test_async_sanity(mock_httpx_client):
    mock_httpx_client.add_response(
        "GET",
        "https://example.test/health",
        status_code=200,
        json={"ok": True},
    )

    response = await mock_httpx_client.client.get("https://example.test/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
