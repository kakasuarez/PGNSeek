"""
Minimal in-memory stand-in for the Motor database, covering what the review code uses:
equality and $in filters, inclusion or exclusion projections, find / find_one /
insert_many / delete_many. Documents are copied in and out, as with a real database.
"""

import copy
from collections import defaultdict
from typing import Any


def _matches(document: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, condition in query.items():
        value = document.get(key)
        if isinstance(condition, dict) and "$in" in condition:
            if value not in condition["$in"]:
                return False
        elif value != condition:
            return False
    return True


def _project(
    document: dict[str, Any], projection: dict[str, int] | None
) -> dict[str, Any]:
    document = copy.deepcopy(document)
    if not projection:
        return document
    if any(projection.values()):
        keep = {key for key, include in projection.items() if include} | {"_id"}
        keep -= {key for key, include in projection.items() if not include}
        return {key: value for key, value in document.items() if key in keep}
    return {key: value for key, value in document.items() if key not in projection}


class FakeCursor:
    def __init__(self, documents: list[dict[str, Any]]):
        self._documents = documents

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for document in self._documents:
            yield document


class FakeCollection:
    def __init__(self):
        self.documents: list[dict[str, Any]] = []

    async def insert_one(self, document: dict[str, Any]):
        self.documents.append(copy.deepcopy(document))

    async def insert_many(self, documents: list[dict[str, Any]], ordered: bool = True):
        self.documents.extend(copy.deepcopy(document) for document in documents)

    async def delete_many(self, query: dict[str, Any]):
        self.documents = [d for d in self.documents if not _matches(d, query)]

    def find(
        self, query: dict[str, Any], projection: dict[str, int] | None = None
    ) -> FakeCursor:
        return FakeCursor(
            [_project(d, projection) for d in self.documents if _matches(d, query)]
        )

    async def find_one(
        self, query: dict[str, Any], projection: dict[str, int] | None = None
    ):
        for document in self.documents:
            if _matches(document, query):
                return _project(document, projection)
        return None


class FakeDB:
    def __init__(self):
        self._collections: dict[str, FakeCollection] = defaultdict(FakeCollection)

    def __getitem__(self, name: str) -> FakeCollection:
        return self._collections[name]

    def __getattr__(self, name: str) -> FakeCollection:
        if name.startswith("_"):
            raise AttributeError(name)
        return self._collections[name]
