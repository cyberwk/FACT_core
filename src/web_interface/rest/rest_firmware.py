import logging
from base64 import standard_b64decode

from flask import request
from flask_restx import Resource, Namespace, fields
from pymongo.errors import PyMongoError

from helperFunctions.database import ConnectTo
from helperFunctions.mongo_task_conversion import convert_analysis_task_to_fw_obj
from helperFunctions.object_conversion import create_meta_dict
from intercom.front_end_binding import InterComFrontEndBinding
from objects.firmware import Firmware
from storage.db_interface_frontend import FrontEndDbInterface
from web_interface.rest.helper import (
    convert_rest_request, error_message, get_boolean_from_request, get_paging, get_query, get_update, success_message
)
from web_interface.security.decorator import roles_accepted
from web_interface.security.privileges import PRIVILEGES


api = Namespace('rest/firmware', description='Query the firmware database or upload a firmware')


firmware_model = api.model('Upload Firmware', {
    'device_name': fields.String(description='Device Name', required=True),
    'device_part': fields.String(description='Device Part', required=True),
    'device_class': fields.String(description='Device Class', required=True),
    'file_name':  fields.String(description='File Name', required=True),
    'version':  fields.String(description='Version', required=True),
    'vendor':  fields.String(description='Vendor', required=True),
    'release_date':  fields.String(description='Release Date'),
    'tags':  fields.String(description='Tags'),
    'requested_analysis_systems': fields.List(description='Selected Analysis Systems', cls_or_instance=fields.String),
    'binary': fields.String(description='Base64 String Representing the Raw Binary', required=True)
})


class RestFirmwareBase(Resource):
    URL = '/rest/firmware'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.config = kwargs.get('config', None)


@api.route('', doc={'description': ''})
class RestFirmwareGetWithoutUid(RestFirmwareBase):
    @roles_accepted(*PRIVILEGES['view_analysis'])
    @api.doc(responses={200: 'Success', 400: 'Unknown file object'})
    def get(self):
        '''
        Browse the database
        List all available firmware in the database
        '''
        try:
            query, recursive, inverted, offset, limit = self._get_parameters_from_request(request.args)
        except ValueError as value_error:
            request_data = {k: request.args.get(k) for k in ['query', 'limit', 'offset', 'recursive', 'inverted']}
            return error_message(str(value_error), self.URL, request_data=request_data)

        parameters = dict(offset=offset, limit=limit, query=query, recursive=recursive, inverted=inverted)
        try:
            with ConnectTo(FrontEndDbInterface, self.config) as connection:
                uids = connection.rest_get_firmware_uids(**parameters)
            return success_message(dict(uids=uids), self.URL, parameters)
        except PyMongoError:
            return error_message('Unknown exception on request', self.URL, parameters)

    @staticmethod
    def _get_parameters_from_request(request_parameters):
        query = get_query(request_parameters)
        recursive = get_boolean_from_request(request_parameters, 'recursive')
        inverted = get_boolean_from_request(request_parameters, 'inverted')
        offset, limit = get_paging(request.args)
        if recursive and not query:
            raise ValueError('Recursive search is only permissible with non-empty query')
        if inverted and not recursive:
            raise ValueError('Inverted flag can only be used with recursive')
        return query, recursive, inverted, offset, limit

    @roles_accepted(*PRIVILEGES['submit_analysis'])
    @api.expect(firmware_model, validate=True)
    def put(self):
        '''
        Upload a firmware
        The HTTP body must contain a json document of the structure shown below
        Important: The binary has to be a base64 string representing the raw binary you want to submit
        '''
        try:
            data = convert_rest_request(request.data)
        except TypeError as type_error:
            return error_message(str(type_error), self.URL, request_data=request.data)

        result = self._process_data(data)
        if 'error_message' in result:
            logging.warning('Submission not according to API guidelines! (data could not be parsed)')
            return error_message(result['error_message'], self.URL, request_data=data)

        logging.debug('Upload Successful!')
        return success_message(result, self.URL, request_data=data)

    def _process_data(self, data):
        for field in ['device_name', 'device_class', 'device_part', 'file_name', 'version', 'vendor', 'release_date',
                      'requested_analysis_systems', 'binary']:
            if field not in data.keys():
                return dict(error_message='{} not found'.format(field))

        data['binary'] = standard_b64decode(data['binary'])
        firmware_object = convert_analysis_task_to_fw_obj(data)
        with ConnectTo(InterComFrontEndBinding, self.config) as intercom:
            intercom.add_analysis_task(firmware_object)
        data.pop('binary')

        return dict(uid=firmware_object.uid)


@api.route('/<string:uid>',
           doc={'description': '',
                'params': {'uid': 'Firmware UID'}
                }
           )
class RestFirmwareGetWithUid(RestFirmwareBase):
    @roles_accepted(*PRIVILEGES['view_analysis'])
    @api.doc(responses={200: 'Success', 400: 'Unknown UID'})
    def get(self, uid):
        '''
        Request a specific file
        Get a specific file by providing the uid of the corresponding firmware
        '''
        summary = get_boolean_from_request(request.args, 'summary')
        if summary:
            with ConnectTo(FrontEndDbInterface, self.config) as connection:
                firmware = connection.get_complete_object_including_all_summaries(uid)
        else:
            with ConnectTo(FrontEndDbInterface, self.config) as connection:
                firmware = connection.get_firmware(uid)
        if not firmware or not isinstance(firmware, Firmware):
            return error_message('No firmware with UID {} found'.format(uid), self.URL, dict(uid=uid))

        fitted_firmware = self._fit_firmware(firmware)
        return success_message(dict(firmware=fitted_firmware), self.URL, request_data=dict(uid=uid))

    @staticmethod
    def _fit_firmware(firmware):
        meta = create_meta_dict(firmware)
        analysis = firmware.processed_analysis
        return dict(meta_data=meta, analysis=analysis)

    @roles_accepted(*PRIVILEGES['submit_analysis'])
    @api.expect(firmware_model)
    def put(self, uid):
        '''
        Update existing firmware analysis
        You can use this endpoint to update a firmware analysis which is already existing
        '''
        try:
            update = get_update(request.args)
        except ValueError as value_error:
            return error_message(str(value_error), self.URL, request_data={'uid': uid})
        return self._update_analysis(uid, update)

    def _update_analysis(self, uid, update):
        with ConnectTo(FrontEndDbInterface, self.config) as connection:
            firmware = connection.get_firmware(uid)
        if not firmware:
            return error_message('No firmware with UID {} found'.format(uid), self.URL, dict(uid=uid))

        unpack = 'unpacker' in update
        while 'unpacker' in update:
            update.remove('unpacker')

        firmware.scheduled_analysis = update

        with ConnectTo(InterComFrontEndBinding, self.config) as intercom:
            supported_plugins = intercom.get_available_analysis_plugins().keys()
            for item in update:
                if item not in supported_plugins:
                    return error_message('Unknown analysis system \'{}\''.format(item), self.URL, dict(uid=uid, update=update))
            intercom.add_re_analyze_task(firmware, unpack)

        if unpack:
            update.append('unpacker')
        return success_message({}, self.URL, dict(uid=uid, update=update))
