from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy.orm import Session
from story_context import context_for

from backlog_service.domain import Conflict, ItemChange, ItemDraft, ProjectContext, Reorder
from backlog_service.repository import StoryRepository
from backlog_service.service import StoriesService


def test_concurrent_expected_item_version_commits_only_once(engine, service, project_id):
    ctx = context_for(project_id)
    item = service.create_item(ctx, ItemDraft(title="Original"))
    barrier = Barrier(2)

    def change(title):
        with Session(engine, expire_on_commit=False) as session:
            worker = StoriesService(StoryRepository(session))
            barrier.wait()
            try:
                return worker.update_item(
                    ctx, item.id, ItemChange(title=title, expected_version=1)
                ).version
            except Conflict:
                return "conflict"

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(change, ["First", "Second"]))
    assert sorted(map(str, results)) == ["2", "conflict"]
    assert service.history(ctx, item.id)["total"] == 2


def test_concurrent_reorder_is_canonical_once(engine, service, project_id):
    old = context_for(project_id)
    ctx = ProjectContext(project_id, old.actor_id, old.permissions | {"backlog:reorder"})
    a, b = [service.create_item(ctx, ItemDraft(title=x)) for x in "AB"]
    version = service.board(ctx)["version"]
    service.repository.rollback()
    barrier = Barrier(2)

    def change(ids):
        with Session(engine, expire_on_commit=False) as session:
            worker = StoriesService(StoryRepository(session))
            barrier.wait()
            try:
                return worker.reorder(ctx, Reorder(item_ids=ids, expected_version=version))[
                    "version"
                ]
            except Conflict:
                return "conflict"

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(change, [[b.id, a.id], [a.id, b.id]]))
    assert sorted(map(str, results)) == [str(version + 1), "conflict"]


def test_board_detects_interleaving_mutation_before_exposing_version(
    engine, service, project_id, monkeypatch
):
    ctx = context_for(project_id)
    item = service.create_item(ctx, ItemDraft(title="Consistent snapshot"))
    original = service.repository.all_items

    def interleaved(project):
        snapshot = original(project)
        with Session(engine, expire_on_commit=False) as session:
            worker = StoriesService(StoryRepository(session))
            worker.update_item(ctx, item.id, ItemChange(status="done", expected_version=1))
        return snapshot

    monkeypatch.setattr(service.repository, "all_items", interleaved)
    with pytest.raises(Conflict):
        service.board(ctx)
