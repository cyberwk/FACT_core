import shutil
import tempfile
from configparser import ConfigParser
from pathlib import Path
from typing import Dict, Tuple

import pytest

import config
from analysis.PluginBase import AnalysisBasePlugin
from config import Config, _replace_hyphens_with_underscores
from test.common_helper import CommonDatabaseMock, create_docker_mount_base_dir


def _get_test_config_tuple(defaults: Dict = None) -> Tuple[Config, ConfigParser]:
    """Returns a tuple containing a `config.Config` instance and a `ConfigParser` instance.
    Both instances are equivalent and the latter is legacy only.
    The "docker-mount-base-dir" and "firmware-file-storage-directory" in the section "data-storage"
    are created and must be cleaned up manually.

    :arg defaults: Sections to overwrite
    """
    config.load_config()

    docker_mount_base_dir = create_docker_mount_base_dir()
    firmware_file_storage_directory = Path(tempfile.mkdtemp())

    sections = {
        'data-storage': {
            'postgres-server': 'localhost',
            'postgres-port': '5432',
            'postgres-database': 'fact_test',
            'postgres-test-database': 'fact_test',

            'postgres-ro-user': config.cfg.data_storage.postgres_ro_user,
            'postgres-ro-pw': config.cfg.data_storage.postgres_ro_pw,
            'postgres-rw-user': config.cfg.data_storage.postgres_rw_user,
            'postgres-rw-pw': config.cfg.data_storage.postgres_rw_pw,
            'postgres-del-user': config.cfg.data_storage.postgres_del_user,
            'postgres-del-pw': config.cfg.data_storage.postgres_del_pw,
            'postgres-admin-user': config.cfg.data_storage.postgres_del_user,
            'postgres-admin-pw': config.cfg.data_storage.postgres_del_pw,

            'redis-fact-db': config.cfg.data_storage.redis_test_db,  # Note: This is unused in testing
            'redis-test-db': config.cfg.data_storage.redis_test_db,  # Note: This is unused in production
            'redis-host': config.cfg.data_storage.redis_host,
            'redis-port': config.cfg.data_storage.redis_port,

            'firmware-file-storage-directory': str(firmware_file_storage_directory),

            'user-database': 'sqlite:////media/data/fact_auth_data/fact_users.db',
            'password-salt': '1234',

            'structural-threshold': '40',  # TODO
            'temp-dir-path': '/tmp',
            'docker-mount-base-dir': str(docker_mount_base_dir),
            'variety-path': 'bin/variety.js',
         },
        'database': {
            'ajax-stats-reload-time': '10000',  # TODO
            'number-of-latest-firmwares-to-display': '10',
            'results-per-page': '10'
        },
        'default-plugins': {
            'default': '',
            'minimal': '',
        },
        'expert-settings': {
            'authentication': 'false',
            'block-delay': '0.1',
            'communication-timeout': '60',
            'intercom-poll-delay': '0.5',
            'nginx': 'false',
            'radare2-host': 'localhost',
            'ssdeep-ignore': '1',
            'throw-exceptions': 'false',
            'unpack-threshold': '0.8',
            'unpack_throttle_limit': '50'
        },
        'logging': {
            'logfile': '/tmp/fact_main.log',
            'loglevel': 'WARNING',
        },
        'unpack': {
            'max-depth': '10',
            'memory-limit': '2048',
            'threads': '4',
            'whitelist': [
                ''
            ]
        },
        'statistics': {
            'max_elements_per_chart': '10'
        },
    }
    # Update recursively
    for section_name in defaults if defaults else {}:
        sections.setdefault(section_name, {}).update(defaults[section_name])

    configparser_cfg = ConfigParser()
    configparser_cfg.read_dict(sections)

    _replace_hyphens_with_underscores(sections)
    cfg = Config(**sections)

    return cfg, configparser_cfg


@pytest.fixture
def cfg_tuple(request):
    """Returns a `config.Config` and a `configparser.ConfigParser` with testing defaults.
    Defaults can be overwritten with the `cfg_defaults` pytest mark.
    """
    # TODO Use iter_markers to be able to overwrite the config.
    # Make sure to iterate in order from closest to farthest.
    cfg_defaults_marker = request.node.get_closest_marker('cfg_defaults')
    cfg_defaults = cfg_defaults_marker.args[0] if cfg_defaults_marker else {}

    cfg, configparser_cfg = _get_test_config_tuple(cfg_defaults)
    yield cfg, configparser_cfg

    # Don't clean up directorys we didn't create ourselves
    if not cfg_defaults.get('data-storage', {}).get('docker-mount-base-dir', None):
        shutil.rmtree(cfg.data_storage.docker_mount_base_dir)
    if not cfg_defaults.get('data-storage', {}).get('firmware-file-storage-directory', None):
        shutil.rmtree(cfg.data_storage.firmware_file_storage_directory)


# We deliberatly don't want to autouse this fixture to explicitly mark when the config is used in testing
@pytest.fixture
def patch_cfg(cfg_tuple):
    """This fixture will replace `config.cfg` and `config.configparser_cfg` with the default test config.
    See `cfg_tuple` on how to change defaults.
    """
    cfg, configparser_cfg = cfg_tuple
    mpatch = pytest.MonkeyPatch()
    # We only patch the private parts of the module.
    # This ensures that even, when `config.cfg` is imported before this fixture is executed we get
    # the patched config.
    mpatch.setattr('config._cfg', cfg)
    mpatch.setattr('config._configparser_cfg', configparser_cfg)
    yield

    mpatch.undo()


class MockPluginAdministrator:
    def register_plugin(self, name, plugin_object):
        assert plugin_object.NAME == name, 'plugin object has wrong name'
        assert isinstance(plugin_object.DESCRIPTION, str)
        assert isinstance(plugin_object.VERSION, str)
        assert plugin_object.VERSION != 'not set' 'Plug-in version not set'


@pytest.fixture
def analysis_plugin(request, monkeypatch):
    """
    Returns an instance of an AnalysisPlugin.
    The following pytest markers affect this fixture:
        * AnalysisPluginClass: The plugin class type. Must be a class derived from `AnalysisBasePlugin`.
            E.g `AnalysisPlugin`
            The marker has to be set with `@pytest.mark.with_args` to work around pytest
            (wiredness)[https://docs.pytest.org/en/7.1.x/example/markers.html#passing-a-callable-to-custom-markers].
        * plugin_start_worker: If set the AnalysisPluginClass.start_worker method will NOT be overwritten.
            If not set the method is overwritten by a stub that does nothing.
        * plugin_init_kwargs: Additional keyword arguments that shall be passed to the `AnalysisPluginClass` constructor

    If this fixture does not fit your needs (which should not happen) you can define a fixture like this:
    ```@pytest.fixture
    def my_fancy_plugin(analysis_plugin)
        # Make sure the marker is defined as expected
        assert isinstance(analysis_plugin, MyFancyPlugin)
        # Patch custom things
        analysis_plugin.db_interface = CustomDbMock()
        # Return the plugin instance
        yield analysis_plugin
    ```
    """

    plugin_class_marker = request.node.get_closest_marker('AnalysisPluginClass')
    assert plugin_class_marker, '@pytest.mark.AnalysisPluginClass has to be defined'
    PluginClass = plugin_class_marker.args[0]
    assert issubclass(PluginClass, AnalysisBasePlugin), f'{PluginClass.__name__} is not a subclass of {AnalysisBasePlugin.__name__}'

    # We don't want to actually start workers when testing, except for some special cases
    plugin_start_worker_marker = request.node.get_closest_marker('plugin_start_worker')
    if not plugin_start_worker_marker:
        monkeypatch.setattr(PluginClass, 'start_worker', lambda _: None)

    plugin_init_kwargs_marker = request.node.get_closest_marker('plugin_init_kwargs')
    kwargs = plugin_init_kwargs_marker.kwargs if plugin_init_kwargs_marker else {}

    plugin_instance = PluginClass(
        MockPluginAdministrator(),
        view_updater=CommonDatabaseMock(),
        **kwargs,
    )
    yield plugin_instance

    plugin_instance.shutdown()
