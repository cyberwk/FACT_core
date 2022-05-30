import json
import os

from common_helper_files import get_dir_of_file

from objects.file import FileObject
from plugins.analysis.known_vulnerabilities.code.known_vulnerabilities import AnalysisPlugin
from test.unit.analysis.analysis_plugin_test_class import AnalysisPluginTest  # pylint: disable=wrong-import-order

TEST_DATA_DIR = os.path.join(get_dir_of_file(__file__), 'data')


class TestAnalysisPluginsKnownVulnerabilities(AnalysisPluginTest):

    PLUGIN_NAME = 'known_vulnerabilities'
    PLUGIN_CLASS = AnalysisPlugin

    def setUp(self):
        super().setUp()
        with open(os.path.join(TEST_DATA_DIR, 'sc.json'), 'r') as json_file:
            self._software_components_result = json.load(json_file)

    def test_process_object_yara(self):
        test_file = FileObject(file_path=os.path.join(TEST_DATA_DIR, 'testfile'))
        test_file.processed_analysis['file_hashes'] = {'sha256': '1234'}
        test_file.processed_analysis['software_components'] = {}

        results = self.analysis_plugin.process_object(test_file).processed_analysis[self.PLUGIN_NAME]['result']

        self.assertEqual(len(results), 2, 'incorrect number of vulnerabilities found')
        self.assertTrue('DLink_Bug' in results, 'test match not found')
        self.assertEqual(results['DLink_Bug']['score'], 'high', 'incorrect or no score found in meta data')

        self.assertIn('DLink_Bug', test_file.processed_analysis[self.PLUGIN_NAME]['tags'])
        self.assertTrue(test_file.processed_analysis[self.PLUGIN_NAME]['tags']['DLink_Bug']['propagate'])

    def test_process_object_software(self):
        test_file = FileObject(file_path=os.path.join(TEST_DATA_DIR, 'empty'))
        test_file.processed_analysis['file_hashes'] = {'sha256': '1234'}
        test_file.processed_analysis['software_components'] = {'result':  self._software_components_result}

        results = self.analysis_plugin.process_object(test_file).processed_analysis[self.PLUGIN_NAME]['result']

        self.assertEqual(len(results), 1, 'incorrect number of vulnerabilities found')
        self.assertTrue('Heartbleed' in results, 'test match not found')
        self.assertEqual(results['Heartbleed']['score'], 'high', 'incorrect or no score found in meta data')

    def test_process_object_software_wrong_version(self):
        test_file = FileObject(file_path=os.path.join(TEST_DATA_DIR, 'empty'))
        test_file.processed_analysis['file_hashes'] = {'sha256': '1234'}
        self._software_components_result['OpenSSL']['meta']['version'] = ['0.9.8', '1.0.0', '']
        test_file.processed_analysis['software_components'] = self._software_components_result

        self.analysis_plugin.process_object(test_file)

        assert len(test_file.processed_analysis[self.PLUGIN_NAME]['result'].keys()) == 0, 'no match should be found'

    def test_process_object_hash(self):
        test_file = FileObject(file_path=os.path.join(TEST_DATA_DIR, 'empty'))
        test_file.processed_analysis['file_hashes'] = {'sha256': '7579d10e812905e134cf91ad8eef7b08f87f6f8c8e004ebefa441781fea0ec4a'}
        test_file.processed_analysis['software_components'] = {}

        results = self.analysis_plugin.process_object(test_file).processed_analysis[self.PLUGIN_NAME]['result']

        self.assertEqual(len(results), 1, 'incorrect number of vulnerabilities found')
        self.assertTrue('Netgear_CGI' in results, 'test match not found')
        self.assertEqual(results['Netgear_CGI']['score'], 'medium', 'incorrect or no score found in meta data')

        self.assertIn('Netgear_CGI', test_file.processed_analysis[self.PLUGIN_NAME]['tags'])
        self.assertFalse(test_file.processed_analysis[self.PLUGIN_NAME]['tags']['Netgear_CGI']['propagate'])
