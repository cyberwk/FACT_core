# pylint: disable=no-self-use
import gc
from typing import List

import pytest

from storage.db_interface_admin import AdminDbInterface
from storage.db_interface_backend import BackendDbInterface
from storage.db_interface_common import DbInterfaceCommon
from storage.db_interface_comparison import ComparisonDbInterface
from storage.db_interface_frontend import FrontEndDbInterface
from storage.db_interface_frontend_editing import FrontendEditingDbInterface
from storage.db_setup import DbSetup
from test.common_helper import CommonDatabaseMock, CommonIntercomMock
from web_interface.frontend_main import WebFrontEnd
from web_interface.security.authentication import add_flask_security_to_app



from multiprocessing import Queue


from scheduler.analysis import AnalysisScheduler
from storage.unpacking_locks import UnpackingLockManager


class FrontendDatabaseMock:
    def __init__(self, db_mock: CommonDatabaseMock):
        self.frontend = db_mock
        self.editing = db_mock
        self.admin = db_mock
        self.comparison = db_mock
        self.template = db_mock
        self.stats_viewer = db_mock
        self.stats_updater = db_mock


class UserDbMock:
    class session:  # pylint: disable=invalid-name
        @staticmethod
        def commit():
            pass

        @staticmethod
        def rollback():
            pass


@pytest.fixture
def web_frontend(request, monkeypatch, cfg_tuple) -> WebFrontEnd:
    """Yields an intance to WebFrontEnd.
    Respects the `use_database` and `mock_database` fixtures.
    TODO
    """
    _, configparser_cfg = cfg_tuple
    # TODO document marker
    database_mock_class_marker = request.node.get_closest_marker('DatabaseMockClass')
    intercom_mock_class_marker = request.node.get_closest_marker('IntercomMockClass')

    if 'mock_database' in request.fixturenames:
        # TODO dont use lambda
        DatabaseMockClass = database_mock_class_marker.args[0]() if database_mock_class_marker else CommonDatabaseMock
        db_mock_instance = DatabaseMockClass()

        # TODO dont use lambda
        IntercomMockClass = intercom_mock_class_marker.args[0]() if intercom_mock_class_marker else CommonIntercomMock

        def add_security_get_mocked(app):
            add_flask_security_to_app(app)
            return UserDbMock(), db_mock_instance

        monkeypatch.setattr('web_interface.frontend_main.add_flask_security_to_app', add_security_get_mocked)

        frontend = WebFrontEnd(config=configparser_cfg, db=FrontendDatabaseMock(db_mock_instance), intercom=IntercomMockClass)
    elif "use_database" in request.fixturenames:
        assert database_mock_class_marker is None, "You can't mock the database if you use use_database"
        assert intercom_mock_class_marker is None, "You can't mock the database if you use use_database"

        frontend = WebFrontEnd(config=configparser_cfg)

    frontend.app.config['TESTING'] = True

    yield frontend

    if 'mock_database' in request.fixturenames:
        # TODO This should not have to be done here
        # State should not be stored in class variables.
        # Otherwise tests are not isolated.
        IntercomMockClass.tasks = []

    gc.collect()


@pytest.fixture
def test_client(web_frontend):
    yield web_frontend.app.test_client()


# TODO redis&posgres: It seems that only postgres is started
# TODO scope
@pytest.fixture
def use_database(request, cfg_tuple):
    """Creates test tables in the Postgres database.
    When the fixture goes out of scope the test tables are dropped.
    The database has to be initialized (See init_postgres.py) and running.
    """
    assert "mock_database" not in request.fixturenames, "You can't use the fixtures `use_database` and `mock_database` at the same time"

    # Keep function name in sync with web_frontend fixture
    _, configparser_cfg = cfg_tuple
    db_setup = DbSetup(configparser_cfg)
    db_setup.create_tables()
    db_setup.set_table_privileges()

    yield

    db_setup.base.metadata.drop_all(db_setup.engine)


# TODO redis&posgres
@pytest.fixture
def mock_database(request, monkeypatch):
    """Patches everthing in a way that the real database is not used.
    TODO
    """
    # This fixture intentionally does nothing.
    # Its presence shall be checked in fixtures that yield something database related (e.g. web_frontend).
    # A fixtures is used instead of a marker for symmetry with `use_database`.
    assert "use_database" not in request.fixturenames, "You can't use the fixtures `use_database` and `mock_database` at the same time"


class DB:
    def __init__(
        self, common: DbInterfaceCommon, backend: BackendDbInterface, frontend: FrontEndDbInterface,
        frontend_editing: FrontendEditingDbInterface, admin: AdminDbInterface
    ):
        self.common = common
        self.backend = backend
        self.frontend = frontend
        self.frontend_ed = frontend_editing
        self.admin = admin


# See test/integration/conftest.py
# TODO scope=function
# TODO scope=session
@pytest.fixture
def real_database(cfg_tuple, use_database) -> DB:
    """Returns handles to database interfaces as defined in `storage`.
    The database is not mocked, see `use_database`.
    """
    _, configparser_cfg = cfg_tuple
    admin = AdminDbInterface(configparser_cfg, intercom=MockIntercom())
    common = DbInterfaceCommon(configparser_cfg)
    backend = BackendDbInterface(configparser_cfg)
    frontend = FrontEndDbInterface(configparser_cfg)
    frontend_ed = FrontendEditingDbInterface(configparser_cfg)

    db_interface = DB(common, backend, frontend, frontend_ed, admin)

    try:
        yield db_interface
    finally:
        with db_interface.admin.get_read_write_session() as session:
            # clear rows from test db between tests
            for table in reversed(db_interface.admin.base.metadata.sorted_tables):
                session.execute(table.delete())
        # clean intercom mock
        if hasattr(db_interface.admin.intercom, 'deleted_files'):
            db_interface.admin.intercom.deleted_files.clear()


@pytest.fixture
def comp_db(cfg_tuple):
    _, configparser_cfg = cfg_tuple
    yield ComparisonDbInterface(configparser_cfg)


class MockIntercom:
    def __init__(self):
        self.deleted_files = []

    def delete_file(self, uid_list: List[str]):
        self.deleted_files.extend(uid_list)





class ViewUpdaterMock:
    def update_view(self, *_):
        pass


class BackendDbInterface:
    def get_analysis(self, *_):
        pass


# TODO rename to clarify that this is not something you should put into
@pytest.fixture
def analysis_queue():
    """TODO
    A queue where all analysed FileObjects are put.
    The entrys are dicts.
    """
    queue = Queue()

    yield queue

    queue.close()
    gc.collect()


@pytest.fixture
def unpacking_lock_manager():
    yield UnpackingLockManager()


@pytest.fixture
def analysis_scheduler(monkeypatch, analysis_queue, unpacking_lock_manager, cfg_tuple) -> AnalysisScheduler:
    monkeypatch.setattr('plugins.base.ViewUpdater', lambda *_: ViewUpdaterMock())

    _, configparser_cfg = cfg_tuple

    mocked_interface = BackendDbInterface()

    def post_analysis_cb(uid, plugin, analysis_result):
        analysis_queue.put({
            'uid': uid,
            'plugin': plugin,
            'result': analysis_result,
            }
        )

    sched = AnalysisScheduler(
        config=configparser_cfg,
        pre_analysis=lambda *_: None,
        post_analysis=post_analysis_cb,
        db_interface=mocked_interface,
        unpacking_locks=unpacking_lock_manager,
    )

    yield sched

    sched.shutdown()
