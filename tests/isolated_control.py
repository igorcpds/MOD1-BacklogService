"""Controlled seams for isolated legacy HTTP/signature tests."""

from uuid import uuid4


class IsolatedWriteControl:
    def acquire(self, project_id):
        return uuid4()

    def release(self, project_id, lease_id):
        pass

    def eligible(self, project_id, user_id):
        return True

    def availability(self, project_id, user_id):
        return True
