# pylint: disable=no-self-use
import gc
from multiprocessing import Queue

import pytest

from objects.firmware import Firmware
from scheduler.analysis import AnalysisScheduler
from scheduler.unpacking_scheduler import UnpackingScheduler
from storage.unpacking_locks import UnpackingLockManager
from test.common_helper import get_test_data_dir
from test.integration.common import MockDbInterface, MockFSOrganizer, initialize_config


class TestFileAddition:
    def setup(self):
        self._config = initialize_config(None)
        self._tmp_queue = Queue()

        unpacking_lock_manager = UnpackingLockManager()
        self._analysis_scheduler = AnalysisScheduler(
            config=self._config, pre_analysis=lambda *_: None, post_analysis=self._dummy_callback,
            db_interface=MockDbInterface(None), unpacking_locks=unpacking_lock_manager
        )
        self._unpack_scheduler = UnpackingScheduler(
            config=self._config, post_unpack=self._analysis_scheduler.start_analysis_of_object,
            fs_organizer=MockFSOrganizer(), unpacking_locks=unpacking_lock_manager
        )

    def teardown(self):
        self._unpack_scheduler.shutdown()
        self._analysis_scheduler.shutdown()
        self._tmp_queue.close()
        gc.collect()

    @pytest.mark.usefixtures('test_real_database')
    def test_unpack_and_analyse(self):
        test_fw = Firmware(file_path='{}/container/test.zip'.format(get_test_data_dir()))

        self._unpack_scheduler.add_task(test_fw)

        processed_container = {}
        for _ in range(4 * 2):  # container with 3 included files times 2 mandatory plugins run
            uid, plugin, analysis_result = self._tmp_queue.get(timeout=10)
            processed_container.setdefault(uid, {}).setdefault(plugin, {})
            processed_container[uid][plugin] = analysis_result

        assert len(processed_container) == 4, '4 files should have been analyzed'
        assert all(
            sorted(processed_analysis) == ['file_hashes', 'file_type']
            for processed_analysis in processed_container.values()
        ), 'at least one analysis not done'

    def _dummy_callback(self, uid, plugin, analysis_result):
        self._tmp_queue.put((uid, plugin, analysis_result))
