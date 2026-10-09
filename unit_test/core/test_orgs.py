"""Org store: default migration, membership, project mapping."""
from __future__ import annotations

import pytest

from app.core.trust.orgs import (
    DEFAULT_ORG_ID,
    OrgStoreError,
    ensure_tenancy_migrated,
    get_org_store,
    reset_org_store,
)
from app.core.trust.users import get_user_store, reset_user_store


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHYN_USERS_DB", str(tmp_path / "users.db"))
    monkeypatch.setenv("GRAPHYN_ENV", "development")
    reset_user_store()
    reset_org_store()
    users = get_user_store()
    orgs = get_org_store()
    yield users, orgs
    reset_user_store()
    reset_org_store()


def test_default_org_migration_and_membership(store):
    users, orgs = store
    admin = users.create_user("admin1", "correct-horse-1", roles=["admin"])
    bob = users.create_user("bob", "correct-horse-1", roles=["builder"])
    ensure_tenancy_migrated(orgs)
    default = orgs.get_org(DEFAULT_ORG_ID)
    assert default and default.slug == "default"
    assert orgs.membership_for(DEFAULT_ORG_ID, admin.id).role == "owner"
    assert orgs.membership_for(DEFAULT_ORG_ID, bob.id).role == "member"


def test_create_org_and_isolation_mapping(store):
    users, orgs = store
    alice = users.create_user("alice", "correct-horse-1", roles=["builder"])
    ensure_tenancy_migrated(orgs)
    other = orgs.create_org("acme", "Acme", owner_user_id=alice.id, created_by="alice")
    orgs.assign_project("alpha", DEFAULT_ORG_ID)
    orgs.assign_project("beta", other.id)
    assert orgs.project_org_id("alpha") == DEFAULT_ORG_ID
    assert orgs.project_org_id("beta") == other.id
    assert "beta" not in orgs.projects_in_org(DEFAULT_ORG_ID)
    assert "beta" in orgs.projects_in_org(other.id)


def test_last_owner_protected(store):
    users, orgs = store
    alice = users.create_user("alice", "correct-horse-1", roles=["admin"])
    ensure_tenancy_migrated(orgs)
    org = orgs.create_org("solo", "Solo", owner_user_id=alice.id)
    with pytest.raises(OrgStoreError) as exc:
        orgs.remove_membership(org.id, alice.id)
    assert exc.value.status_code == 409
