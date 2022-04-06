# pylint: disable=redefined-outer-name,wrong-import-order
import logging

import pytest

from intercom.back_end_binding import InterComBackEndDeleteFile
from test.common_helper import CommonDatabaseMock
from test.integration.common import MockFSOrganizer


class UnpackingLockMock:
    @staticmethod
    def unpacking_lock_is_set(uid):
        if uid == 'locked':
            return True
        return False


@pytest.fixture(scope='function')
def mock_listener(cfg_tuple):
    _, configparser_cfg = cfg_tuple
    listener = InterComBackEndDeleteFile(configparser_cfg, unpacking_locks=UnpackingLockMock(), db_interface=CommonDatabaseMock())
    listener.fs_organizer = MockFSOrganizer(None)
    listener.config = configparser_cfg
    return listener


def test_delete_file_success(mock_listener, caplog):
    with caplog.at_level(logging.INFO):
        mock_listener.post_processing(['AnyID'], None)
        assert 'removing file: AnyID' in caplog.messages


def test_delete_file_entry_exists(mock_listener, monkeypatch, caplog):
    monkeypatch.setattr('test.common_helper.CommonDatabaseMock.exists', lambda self, uid: True)
    with caplog.at_level(logging.DEBUG):
        mock_listener.post_processing(['AnyID'], None)
        assert 'entry exists: AnyID' in caplog.messages[-1]


def test_delete_file_is_locked(mock_listener, caplog):
    with caplog.at_level(logging.DEBUG):
        mock_listener.post_processing(['locked'], None)
        assert 'processed by unpacker: locked' in caplog.messages[-1]
