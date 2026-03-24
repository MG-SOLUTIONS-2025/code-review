"""Tests for verify_gateway_token auth dependency."""

from unittest.mock import patch

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_no_token_set_skips_auth():
    """When GATEWAY_API_TOKEN is empty, auth check is skipped."""
    with patch("gateway.utils.auth.GATEWAY_API_TOKEN", ""):
        from gateway.utils.auth import verify_gateway_token
        # Should not raise
        result = await verify_gateway_token(authorization="")
        assert result is None


@pytest.mark.asyncio
async def test_valid_token():
    """When correct bearer token is provided, no exception is raised."""
    with patch("gateway.utils.auth.GATEWAY_API_TOKEN", "my-secret"):
        from gateway.utils.auth import verify_gateway_token
        result = await verify_gateway_token(authorization="Bearer my-secret")
        assert result is None


@pytest.mark.asyncio
async def test_invalid_token():
    """When wrong bearer token is provided, 403 is raised."""
    with patch("gateway.utils.auth.GATEWAY_API_TOKEN", "my-secret"):
        from gateway.utils.auth import verify_gateway_token
        with pytest.raises(HTTPException) as exc_info:
            await verify_gateway_token(authorization="Bearer wrong-token")
        assert exc_info.value.status_code == 403
        assert "Invalid gateway token" in exc_info.value.detail


@pytest.mark.asyncio
async def test_missing_bearer_prefix():
    """When Authorization header doesn't start with 'Bearer ', 401 is raised."""
    with patch("gateway.utils.auth.GATEWAY_API_TOKEN", "my-secret"):
        from gateway.utils.auth import verify_gateway_token
        with pytest.raises(HTTPException) as exc_info:
            await verify_gateway_token(authorization="Token my-secret")
        assert exc_info.value.status_code == 401
        assert "Missing bearer token" in exc_info.value.detail


@pytest.mark.asyncio
async def test_empty_authorization_header():
    """When Authorization header is empty and token is set, 401 is raised."""
    with patch("gateway.utils.auth.GATEWAY_API_TOKEN", "my-secret"):
        from gateway.utils.auth import verify_gateway_token
        with pytest.raises(HTTPException) as exc_info:
            await verify_gateway_token(authorization="")
        assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_bearer_with_extra_whitespace():
    """Token with leading/trailing whitespace should still match after strip."""
    with patch("gateway.utils.auth.GATEWAY_API_TOKEN", "my-secret"):
        from gateway.utils.auth import verify_gateway_token
        result = await verify_gateway_token(authorization="Bearer  my-secret ")
        assert result is None
