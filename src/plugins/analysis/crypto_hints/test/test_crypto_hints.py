from pathlib import Path

import pytest

from objects.file import FileObject

from ..code.crypto_hints import AnalysisPlugin

TEST_DATA_DIR = Path(__file__).parent / 'data'


@pytest.mark.AnalysisPluginClass.with_args(AnalysisPlugin)
def test_basic_scan_feature(analysis_plugin):
    test_file = FileObject(file_path=str(TEST_DATA_DIR / 'CRC32_table'))
    processed_file = analysis_plugin.process_object(test_file)
    result = processed_file.processed_analysis[analysis_plugin.NAME]
    assert 'CRC32_table' in result
