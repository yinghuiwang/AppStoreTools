# tests/test_web_server.py
from __future__ import annotations
import pytest
from fastapi.testclient import TestClient
from asc.web.server import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def test_homepage_returns_200(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "AppStore Tools" in resp.text


def test_metadata_page_returns_200(client):
    resp = client.get("/metadata")
    assert resp.status_code == 200


def test_build_page_returns_200(client):
    resp = client.get("/build")
    assert resp.status_code == 200


def test_profiles_page_returns_200(client):
    resp = client.get("/profiles")
    assert resp.status_code == 200


def test_settings_page_returns_200(client):
    resp = client.get("/settings")
    assert resp.status_code == 200
