import time
import pytest
from app.db.sessions import SessionStore, SessionError


def test_persistence_owner_expiry_and_busy(tmp_path):
    path = tmp_path/'sessions.db'
    store = SessionStore(path)
    owner, cookie = store.browser(None, 60)
    assert store.browser(cookie, 60) == (owner, None)
    cid = store.create(owner)
    store.acquire(cid, owner, 'request-1', 60)
    with pytest.raises(SessionError, match='active request'):
        store.acquire(cid, owner, 'request-2', 60)
    with pytest.raises(SessionError):
        store.save(cid, 'other-owner', 'request-1', 'q', 'a', [])
    store.save(cid, owner, 'request-1', 'q', 'a [1]', [])
    restarted = SessionStore(path)
    assert restarted.history(cid, owner)[0]['answer'] == 'a [1]'
    with restarted.connect() as db:
        db.execute('UPDATE browsers SET expires=?', (time.time()-1,))
    new_owner, new_cookie = restarted.browser(cookie, 60)
    assert new_owner != owner and new_cookie != cookie
    with pytest.raises(SessionError):
        restarted.history(cid, new_owner)
