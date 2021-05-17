from flask import request
from flask_restx import Resource, Namespace, fields

from helperFunctions.database import ConnectTo
from helperFunctions.yara_binary_search import is_valid_yara_rule_file
from intercom.front_end_binding import InterComFrontEndBinding
from storage.db_interface_frontend import FrontEndDbInterface
from web_interface.rest.helper import convert_rest_request, error_message, success_message
from web_interface.security.decorator import roles_accepted
from web_interface.security.privileges import PRIVILEGES


class RestBinarySearchException(Exception):
    def get_message(self):
        return ", ".join(self.args)


api = Namespace('rest/binary_search', description='Initiate a binary search on the binary database and fetch the results')


binary_search_model = api.model('Binary Search', {
    'rule_file': fields.String(description='YARA rules', required=True),
    'uid': fields.String(description='Firmware UID')
}, description='Expected value')


class RestBinarySearchBase(Resource):
    URL = '/rest/binary_search'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = kwargs.get('config', None)


@api.route('', doc={'description': 'Binary search on the binary database (or a single firmware)'})
class RestBinarySearchPost(RestBinarySearchBase):
    @roles_accepted(*PRIVILEGES['pattern_search'])
    @api.expect(binary_search_model, validate=True)
    def post(self):
        '''
        Conduct a binary search
        The uid parameter is optional and can be specified if the user want's to search in the files of a single firmware
        rule_file can be something like "rule rule_name {strings: $a = \"foobar\" condition: $a}"
        '''
        try:
            data = convert_rest_request(request.data)
            yara_rules = self._get_yara_rules(data)
            uid = self._get_firmware_uid(data)
        except TypeError as type_error:
            return error_message(str(type_error), self.URL, request_data=request.data)
        except RestBinarySearchException as exception:
            return error_message(exception.get_message(), self.URL, request_data=request.data)

        with ConnectTo(InterComFrontEndBinding, self.config) as intercom:
            search_id = intercom.add_binary_search_request(yara_rules, uid)

        return success_message(
            {'message': 'Started binary search. Please use GET and the search_id to get the results'},
            self.URL,
            request_data={'search_id': search_id}
        )

    @staticmethod
    def _get_yara_rules(request_data):
        if 'rule_file' not in request_data:
            raise RestBinarySearchException('rule_file could not be found in the request data')
        yara_rules = request_data['rule_file']

        if isinstance(yara_rules, str):
            yara_rules = yara_rules.encode()

        if not is_valid_yara_rule_file(yara_rules):
            raise RestBinarySearchException('Error in YARA rule file')

        return yara_rules

    def _get_firmware_uid(self, request_data):
        if 'uid' not in request_data:
            return None

        with ConnectTo(FrontEndDbInterface, self.config) as db_interface:
            if not db_interface.is_firmware(request_data['uid']):
                raise RestBinarySearchException(
                    'Firmware with UID {uid} not found in database'.format(uid=request_data['uid']))

        return request_data['uid']


@api.route('/<string:search_id>',
           doc={'description': 'Get the results of a previously initiated binary search',
                'params': {'search_id': 'Search ID'}
                }
           )
class RestBinarySearchGet(RestBinarySearchBase):

    @roles_accepted(*PRIVILEGES['pattern_search'])
    @api.doc(responses={200: 'Success', 400: 'Unknown search ID'})
    def get(self, search_id=None):
        '''
        Get the results of a previously initiated binary search
        The search_id is needed to fetch the corresponding search result
        The result of the search request can only be fetched once
        After this the search needs to be started again.
        '''

        if search_id is None:
            return error_message('The request is missing a search_id (.../binary_search/<search_id>).', self.URL)

        with ConnectTo(InterComFrontEndBinding, self.config) as intercom:
            result, _ = intercom.get_binary_search_result(search_id)

        if result is None:
            return error_message('The result is not ready yet or it has already been fetched', self.URL)

        return success_message({'binary_search_results': result}, self.URL)
