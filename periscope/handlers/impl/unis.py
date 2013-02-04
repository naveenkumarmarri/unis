#!/usr/bin/env python
"""
UNIS specific handlers
"""

__author__ = 'Ahmed El-Hassany <a.hassany@gmail.com>'
__license__ = 'http://www.apache.org/licenses/LICENSE-2.0'


import copy
import re
import time
import tornado.gen as gen
from periscope.db import DBOp
from periscope.models.unis import write_psjson
from periscope.handlers.impl.handlerimpl import GenericHandlerImpl


class UNISHandlerImpl(GenericHandlerImpl):
    @classmethod
    def _validate_psjson_profile(cls, handler):
        """
        Validates if the profile provided with the content-type is valid.
        """
        regex = re.compile(".*(?P<p>profile\=(?P<profile>[^\;\ ]*))")
        content_type = handler.request.headers.get("Content-Type", "")
        # use the default schema
        if "profile" not in content_type:
            content_type += ";profile=" + \
                handler.schemas_single[handler.accept_content_type]
        match = re.match(regex, content_type)
        if not match:
            handler.send_error(400, message="Bad Content Type '%s'" % content_type)
            return None
        profile = match.groupdict().get("profile", None)
        if not profile:
            handler.send_error(400, message="Bad Content Type '%s'" % content_type)
            return None
        if profile != handler.schemas_single[handler.accept_content_type]:
            handler.send_error(400, message="Bad schema '%s'" % profile)
            return None
        return profile
    
    @classmethod
    @gen.engine
    def get(cls, handler, res_id, query, is_list=False, fields=None, limit=None):
        keep_alive = handler.supports_streaming or handler.supports_sse()
        if res_id is not None:
            query[handler.Id] = res_id
        options = dict(query=query)#, await_data=True)
        # Makes it a tailable cursor
        if keep_alive and handler._tailable:
            options.update(dict(tailable=True, timeout=False))
        if fields:
            options["fields"] = fields
        if limit:
            options["limit"] = limit
        if "sort" not in options:
            options["sort"] = []
        options["sort"].append(("ts", -1))
        
        include_deleted = False
        only_most_recent = True
        
        aggregate_query = [{'$match': query}]
        
        if only_most_recent is True:
            aggregate_ts = {
                '$group': {
                    '_id': {'_id': '$%s' % handler.Id, 'handlerRef': '$handlerRef'},
                    handler.timestamp: {'$max': '$%s' % handler.timestamp}}}
            project_id_set = {'$project': {
                handler.Id: '$_id.%s' % handler.Id,
                handler.timestamp: '$%s' % handler.timestamp}}
            aggregate_query.append(aggregate_ts)
        else:
            project_id_set = {'$project':
                    {
                        handler.Id: '$%s' % handler.Id,
                        handler.timestamp: '$%s' % handler.timestamp}}

        aggregate_id_set = {
            '$group': {
                '_id': None,
                "set": {
                    '$addToSet': {
                        handler.Id: '$%s' % handler.Id, 
                        handler.timestamp: '$%s' % handler.timestamp}}}}

        aggregate_query.append(project_id_set)
        aggregate_query.append(aggregate_id_set)
        results, error = yield DBOp(handler.dblayer.aggregate, aggregate_query)
        if error is not None:
            handler.send_error(500, code=404001, message="error: %s" % str(error))
            return

        results = results.pop("result", [])
        if len(results) == 0:
            results.append(dict(set=[]))
        if results[0]['set'] == [{}]:
            results[0]['set'] = []
        if len(results[0]['set']) == 0 and is_list is False:
            handler.set_status(404)
            handler.finish()
            return

        yield gen.Task(write_psjson, handler, {'$or': results[0]['set']},
                success_status=200, is_list=is_list, show_location=False)
        handler.finish()

    @classmethod
    @gen.engine
    def post(cls, handler):
        """
        Handles HTTP POST request with Content Type of PSJSON.
        """
        profile = cls._validate_psjson_profile(handler)

        if not profile:
            return

        # Create objects from the body
        base_url = handler.request.full_url()
        model_class = handler._model_class
    
        result, error = yield DBOp(model_class.insert_resource,
            handler.dblayer, handler.request.body, base_url,
            register_urn_call=handler.application.register_urn,
            publish_call=handler.application.publish)
        
        if error is None:
            yield gen.Task(write_psjson, handler, {'_id': {'$in': result}},
                success_status=201, is_list=False, show_location=True)
            handler.finish()
        else:
            handler.send_error(**error)

    @classmethod
    @gen.engine
    def put(cls, handler, res_id):
        """
        Validates and inserts HTTP PUT request with Content-Type of psjon.
        """
        # Create objects from the body
        base_url = "/".join(handler.request.full_url().split("/")[:-1])
        model_class = handler._model_class

        # TODO (AH): validate the ID and the selfref inside the resource 400008
        result, error = yield DBOp(model_class.insert_resource,
            handler.dblayer, handler.request.body, base_url,
            handler.application.register_urn, handler.application.publish)
        if error is None:
            yield gen.Task(write_psjson, handler, {'_id': {'$in': result}},
                success_status=201, is_list=False, show_location=True)
            handler.finish()
        else:
            handler.send_error(**error)

    @classmethod
    @gen.engine
    def delete(cls, handler, res_id):
        # Frist to try to fecth the resource to deleted
        res_id = unicode(res_id)
        query = {handler.Id: res_id}
        cursor = handler.dblayer.find(query)

        # TODO (AH): use aggregation to fetch the latest element
        response, error = yield DBOp(cursor.to_list)
        if error is not None:
            message = "Couldn't load the resource from the database: '%s'." % \
                str(error)
            handler.send_error(500, code=500005, message=message)
            return
        if len(response) == 0:
            message = "Couldn't find resource with %s='%s'" % (handler.Id, res_id)
            handler.send_error(404, code=404002, message=message)
            return

        deleted = copy.copy(response[0])
        # Check that the resource wasn't already deleted
        if deleted.get("status", None) == "DELETED":
            message = "Resource already has been deleted at timestamp='%s'." % \
                str(deleted[handler.timestamp])
            handler.send_error(410, code=410001, message=message)
            return

        deleted["status"] = "DELETED"
        deleted[handler.timestamp] = int(time.time() * 1000000) 
        response, error = yield DBOp(handler.dblayer.insert, deleted)
        if error is not None:
            message = "Couldn't delete resource: '%s'." % str(error)
            handler.send_error(500, code=500006, message=message)
            return
        handler.finish()

    @classmethod
    def publish(cls, handler, resource, callback, res_type=None):
        return handler.application.publish(resource, callback, res_type)

    @classmethod
    def subscribe(cls, handler, query, callback):
        return handler.application.subscribe(query, callback)
