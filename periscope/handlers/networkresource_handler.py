#!/usr/bin/env python
"""
Periscope HTTP(s) Handlers.
"""

__author__ = 'Ahmed El-Hassany <a.hassany@gmail.com>'
__license__ = 'http://www.apache.org/licenses/LICENSE-2.0'


import copy
import json
import re
import functools
from netlogger import nllog
import time
import traceback
from tornado.ioloop import IOLoop
import tornado.gen as gen
import tornado.web
from tornado.httpclient import HTTPError
from periscope.handlers.sse_handler import SSEHandler
from periscope.db import DBOp
from periscope.db import dumps_mongo, dump_mongo
from periscope.models import ObjectDict
from periscope.models.unis import NotValidSchema
from periscope.models.unis import write_psjson
from periscope.handlers import MIME


class NetworkResourceHandler(SSEHandler, nllog.DoesLogging):
    """Generic Network resources handler"""

    def initialize(self, dblayer, base_url,
            Id="id",
            timestamp="ts",
            schemas_single=None,
            schemas_list=None,
            allow_get=False,
            allow_post=True,
            allow_put=True,
            allow_delete=True,
            tailable=False,
            model_class=None,
            accepted_mime=[MIME['SSE'], MIME['PSJSON'], MIME['PSXML']],
            content_types_mime=[MIME['SSE'],
                        MIME['PSJSON'], MIME['PSXML'], MIME['HTML']]):
        """
        Initializes handler for certain type of network resources.

        :Parameters:

          - `collection_name`: name of the database collection name that
            stores information about the network resource.
          - `base_url`: the base the path to access this resource, e.g., /nodes
          - `schemas_single`: a dictionary that represents the network
            resources schema to be validated againest.
            The dictionary is indexed by content-type.
          - `schemas_list`: a dictionary that represents the listing of this
            resources schema to be validated againest.
          - `allow_get`: User client can issue HTTP GET requests to this resource
          - `allow_post`: User client can issue HTTP POST requests to this resource
          - `allow_put`: User client can issue HTTP PUT requests to this resource
          - `allow_delete`: User client can issue HTTP DELETE requests to this
            resource.
          - `tailable`: The underlying database collection is a capped collection.

        """
        # TODO (AH): Add ability to Enable/Disable different HTTP methods
        #if not isinstance(dblayer, DBLayer):
        #    raise TypeError("dblayer is not instance of DBLayer")
        self.Id = Id
        self.timestamp = timestamp
        self._dblayer = dblayer
        self._base_url = base_url
        self.schemas_single = schemas_single
        self.schemas_list = schemas_list
        self._allow_get = allow_get
        self._allow_post = allow_post
        self._allow_put = allow_put
        self._allow_delete = allow_delete
        self._accepted_mime = accepted_mime
        self._content_types_mime = content_types_mime
        self._tailable = tailable
        self._model_class = model_class
        if self.schemas_single is not None and \
            MIME["JSON"] not in self.schemas_single and \
            MIME["PSJSON"] in self.schemas_single:
                self.schemas_single[MIME["JSON"]] = self.schemas_single[MIME["PSJSON"]]
        if tailable and allow_delete:
            raise ValueError("Capped collections do not support" + \
                            "delete operation")

    @property
    def dblayer(self):
        """Returns a reference to the DB Layer."""
        if not getattr(self, "_dblayer", None):
            raise TypeError("No DB layer is defined for this handler.")
        return self._dblayer

    @property
    def accept_content_type(self):
        """
        HTTP has methods to allow the client and the server to negotiate
        the content type for their communication.

        Rigth now, this is simple implementation, but additional more complex
        methods can be added in the future.

        See:
            http://www.w3.org/Protocols/rfc2616/rfc2616-sec12.html
            
            http://www.ietf.org/rfc/rfc2295.txt
            
            http://httpd.apache.org/docs/2.2/content-negotiation.html
            
            http://www.w3.org/TR/webarch/#def-coneg
        """
        if not getattr(self, '_accept', None):
            self._accept = None
            raw = self.request.headers.get("Accept", MIME['PSJSON'])
            regex = re.findall(
                "(?P<type>(\w+|\*)\/(\w+|\*)(\+\w+)?)(;[^;,]*)?([ ]*,[ ]*)?",
                raw
            )
            accept = [k[0] for k in regex]
            for accepted_mime in self._accepted_mime:
                if accepted_mime in accept:
                    self._accept = accepted_mime
            if "*/*" in accept:
                self._accept = MIME['JSON']
            if not self._accept:
                self._accept = self.request.headers.get("Accept", None)
        return self._accept

    @property
    def content_type(self):
        """
        Returns the content type of the client's request

        See:
            
            http://www.w3.org/Protocols/rfc2616/rfc2616-sec12.html
            
            http://www.ietf.org/rfc/rfc2295.txt
            
            http://httpd.apache.org/docs/2.2/content-negotiation.html
            
            http://www.w3.org/TR/webarch/#def-coneg
        """
        if not getattr(self, '_content_type', None):
            raw = self.request.headers.get("Content-Type", MIME['PSJSON'])
            regex = re.findall(
                "(?P<type>\w+\/\w+(\+\w+)?)(;[^;,]*)?([ ]*,[ ]*)?",
                raw
            )
            content_type = [k[0] for k in regex]
            for accepted_mime in self._content_types_mime:
                if accepted_mime in content_type:
                    self._content_type = accepted_mime
                    return self._content_type
            self._content_type = raw
        return self._content_type

    @property
    def supports_streaming(self):
        """
        Returns true if the client asked for HTTP Streaming support.

        Any request that is of type text/event-stream or application/json
        with Connection = keep-alive is considered a streaming request
        and it's up to the client to close the HTTP connection.
        """
        if self.request.headers.get("Connection", "").lower() == "keep-alive":
            return self.request.headers.get("Accept", "").lower() in \
                    [MIME['PSJSON'], MIME['SSE']]
        else:
            return False

    def write_error(self, status_code, **kwargs):
        """
        Overrides Tornado error writter to produce different message
        format based on the HTTP Accept header from the client.
        """
        if self.settings.get("debug") and "exc_info" in kwargs:
            # in debug mode, try to send a traceback
            self.set_header('Content-Type', 'text/plain')
            for line in traceback.format_exception(*kwargs["exc_info"]):
                self.write(line)
            self.finish()
        else:
            content_type = self.accept_content_type or MIME['PSJSON']
            if content_type not in self.schemas_single:
                content_type = MIME['PSJSON']
            self.set_header("Content-Type", content_type)
            result = "{"
            for key in kwargs:
                result += '"%s": "%s",' % (key, kwargs[key])
            result = result.rstrip(",") + "}\n"
            self.write(result)
            self.finish()

    def set_default_headers(self):
        # Headers to allow cross domains requests to UNIS
        self.set_header('Access-Control-Allow-Origin', '*')
        self.set_header('Access-Control-Allow-Headers', 'x-requested-with')
    
    
    def _parse_get_arguments(self):
        """Parses the HTTP GET areguments given by the user."""
        def convert_value_type(key, value, val_type):
            if val_type == "integer":
                try:
                    return int(value)
                except:
                    raise HTTPError(400,
                        message="'%s' is not of type '%s'" % (key, val_type))
            if val_type == "number":
                try:
                    return float(value)
                except:
                    raise HTTPError(400,
                        message="'%s' is not of type '%s'" % (key, val_type))
            if val_type == "string":
                try:
                    return unicode(value)
                except:
                    raise HTTPError(400,
                        message="'%s' is not of type '%s'" % (key, val_type))
            if val_type == "boolean":
                try:
                    bools = {"true": True, "false": False, "1": True, "0": False}
                    return bools[value.lower()]
                except:
                    raise HTTPError(400,
                        message="'%s' is not of type '%s'" % (key, val_type))
            raise HTTPError(400,
                        message="Unkown value type '%s' for '%s'." % (val_type, key))
            
        def process_value(key, value):
            val = None
            in_split = value.split(",")
            if len(in_split) > 1:
                return process_in_query(key, in_split)[key]
            operators = ["lt", "lte", "gt", "gte"]
            for op in operators:
                if value.startswith(op + "="):
                    val = {"$"+ op: process_value(key, value.lstrip(op + "="))}
                    return val
            value_types = ["integer", "number", "string", "boolean"]
            for t in value_types:
                if value.startswith(t + ":"):
                    val = convert_value_type(key, value.split(t + ":")[1], t)
                    return val
            
            if key in ["ts", "ttl"]:
                val = convert_value_type(key, value, "number")
                return val
            return value
                
        def process_in_query(key, values):
            in_q = [process_value(key, val) for val in values]       
            return {key: {"$in": in_q}}
        
        def process_or_query(key, values):
            or_q = []
            if key:
                or_q.append({key: process_value(key, values[0])})
                values = values[1:]
            for val in values:
                keys_split = val.split("=", 1)
                if len(keys_split) != 2:
                    raise HTTPError(400, message="Not valid OR query.")
                k = keys_split[0]
                v = keys_split[1]
                or_q.append({k: process_value(k, v)})
            return {"$or": or_q}
            
        def process_and_query(key, values):
            and_q = []
            for val in values:
                split_or = val.split("|")
                if len(split_or) > 1:
                    and_q.append(process_or_query(key, split_or))
                    continue
                split = val.split(",")
                if len(split) == 1:
                    and_q.append({key: process_value(key, split[0])})
                else:
                    and_q.append(process_in_query(key, split))
            return {"$and": and_q}
        
        query = copy.copy(self.request.arguments)
        # First Reterive special parameters
        # fields
        fields = self.get_argument("fields", {})
        query.pop("fields", None)
        if fields:
            fields = dict([(name, 1) for name in fields.split(",")])
        # max results
        limit = self.get_argument("limit", default=None)
        query.pop("limit", None)
        if limit:
            limit = convert_value_type("limit", limit, "integer")
        
        query_ret = []
        for arg in query:
            if isinstance(query[arg], list) and len(query[arg]) > 1:
                and_q = process_and_query(arg, query[arg])
                query_ret.append(and_q)
                continue
            query[arg] = ",".join(query[arg])
            
            split_or = query[arg].split("|")
            if len(split_or) > 1:
                query_ret.append(process_or_query(arg, split_or))
                continue
            split = query[arg].split(",")
            if len(split) > 1:
                in_q = process_in_query(arg, split)
                query_ret.append(in_q)
            else:
                query_ret.append({arg: process_value(arg, split[0])})
        if query_ret:
            query_ret = {"$and": query_ret}
        else:
            query_ret = {}
        ret_val = {"fields": fields, "limit": limit, "query": query_ret}
        return ret_val

    def _get_cursor(self):
        """Returns reference to the database cursor."""
        return self._cursor

    @tornado.web.asynchronous
    @tornado.web.removeslash
    def get(self, res_id=None):
        """Handles HTTP GET"""
        accept = self.accept_content_type
        if res_id is not None:
            self._res_id = unicode(res_id)
        else:
            self._res_id = None
        # Parses the arguments in the URL
        parsed = self._parse_get_arguments()
        query = parsed["query"]
        fields = parsed["fields"]
        limit = parsed["limit"]
        is_list = not res_id
        if query:
            is_list = True
        if is_list:
            pass
            #query["status"] = {"$ne": "DELETED"}
        callback = functools.partial(self._get_on_response,
            new=True, is_list=is_list, query=query)
        #self._find(query, callback, fields=fields, limit=limit)
        self.get_psjson(self._res_id, query, is_list=is_list,
            fields=fields, limit=limit)
    
    @gen.engine
    def get_psjson(self, res_id, query, is_list=False, fields=None, limit=None):
        keep_alive = self.supports_streaming or self.supports_sse()
        if res_id is not None:
            query[self.Id] = res_id
        options = dict(query=query)#, await_data=True)
        # Makes it a tailable cursor
        if keep_alive and self._tailable:
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
                    '_id': {'_id': '$%s' % self.Id, 'selfRef': '$selfRef'},
                    self.timestamp: {'$max': '$%s' % self.timestamp}}}
            project_id_set = {'$project': {
                self.Id: '$_id.%s' % self.Id,
                self.timestamp: '$%s' % self.timestamp}}
            aggregate_query.append(aggregate_ts)
        else:
            project_id_set = {'$project':
                    {
                        self.Id: '$%s' % self.Id,
                        self.timestamp: '$%s' % self.timestamp}}

        aggregate_id_set = {
            '$group': {
                '_id': None,
                "set": {
                    '$addToSet': {
                        self.Id: '$%s' % self.Id, 
                        self.timestamp: '$%s' % self.timestamp}}}}

        aggregate_query.append(project_id_set)
        aggregate_query.append(aggregate_id_set)
        results, error = yield DBOp(self.dblayer.aggregate, aggregate_query)
        if error is not None:
            self.send_error(500, code=404001, message="error: %s" % str(error))
            return

        results = results.pop("result", [])
        if len(results) == 0:
            results.append(dict(set=[]))
        if results[0]['set'] == [{}]:
            results[0]['set'] = []
        if len(results[0]['set']) == 0 and is_list is False:
            self.set_status(404)
            self.finish()
            return

        yield gen.Task(write_psjson, self, {'$or': results[0]['set']},
                success_status=200, is_list=is_list, show_location=False)
        self.finish()

    def _find(self, query, callback, fields=None, limit=None):
        """Query the database.

        :Parameters:
          - `callback`: a function to be called back in case of new data.
            callback function should have `response`, `error`,
            and `new` fields. `new` is going to be True.

        """
        keep_alive = self.supports_streaming or self.supports_sse()
        if self._res_id:
            query[self.Id] = self._res_id
        options = dict(query=query)#, await_data=True)
        # Makes it a tailable cursor
        if keep_alive and self._tailable:
            options.update(dict(tailable=True, timeout=False))
        if fields:
            options["fields"] = fields
        if limit:
            options["limit"] = limit
        if "sort" not in options:
            options["sort"] = []
        options["sort"].append(("ts", -1))
        self._query = query
        self._cursor = self.dblayer.find(**options)
        self._cursor.to_list(callback=callback)

    def _get_more(self, cursor, callback):
        """Calls the given callback if there is data available on the cursor.

        :Parameters:
          - `cursor`: database cursor returned from a find operation.
          - `callback`: a function to be called back in case of new data.
            callback function should have `response`, `error`,
            and `new` fields. `new` is going to be False.

        """
        # If the client went away,
        # clean up the  cursor and close the connection
        if not self.request.connection.stream.socket:
            self._remove_cursor()
            self.finish()
            return
        # If the cursor is not alive, issue new find to the database
        if cursor and cursor.native_cursor.alive:
            cursor.get_more(callback)
        else:
            callback.keywords["response"] = []
            callback.keywords["error"] = None
            callback.keywords["last_batch"] = True
            callback()

    def _remove_cursor(self):
        """Clean up the opened database cursor."""
        if getattr(self, '_cursor', None):
            del self._cursor

    def _get_on_response(self, response, error, new=False,
                        is_list=False, query=None, last_batch=False):
        """callback for get request

        :Parameters:
          - `response`: the response body from the database
          - `error: any error messages from the database.
          - `new: True if this is the first time to call this method.
          - `is_list: If True listing is requered, for example /nodes,
            otherwise it's a single object like /nodes/node_id

        """
        if error:
            self.send_error(500, message=error)
            return
        keep_alive = self.supports_streaming
        if new and not response and not is_list:
            self.send_error(404)
            return
        if response and not is_list:
            response = response[0]
            if response.get("status", None) == "DELETED":
                self.set_status(410)
                self._remove_cursor()
                self.finish()
                return
        cursor = self._get_cursor()
        response_callback = functools.partial(self._get_on_response,
                                    new=False, is_list=is_list)
        get_more_callback = functools.partial(self._get_more,
                                    cursor, response_callback)

        # This will be called when self._get_more returns empty response
        if not new and not response and keep_alive and not last_batch:
            IOLoop.instance().add_callback(get_more_callback)
            return

        accept = self.accept_content_type
        self.set_header("Content-Type",
                    accept + "; profile=" + self.schemas_single[accept])
        from datetime import datetime
        self.set_header("Date",
                    datetime.utcnow())
        if accept == MIME['PSJSON'] or accept == MIME['JSON']:
            json_response = dumps_mongo(response,
                                indent=2).replace('\\\\$', '$').replace('$DOT$', '.')
            # Mongo sends each batch a separate list, this code fixes that
            # and makes all the batches as part of single list
            if is_list:
                if not new and response:
                    json_response = "," + json_response.lstrip("[")
                if not last_batch:
                    json_response = json_response.rstrip("]")
                if last_batch:
                    if not response:
                        json_response = "]"
                    else:
                        json_response += "]"
            else:
                if not response:
                    json_response = ""
            self.write(json_response)
        else:
            # TODO (AH): HANDLE HTML, SSE and other formats
            json_response = dumps_mongo(response,
                                indent=2).replace('\\\\$', '$')
            # Mongo sends each batch a separate list, this code fixes that
            # and makes all the batches as part of single list
            if is_list:
                if not new and response:
                    json_response = "," + json_response.lstrip("[")
                if not last_batch:
                    json_response = json_response.rstrip("]")
                if last_batch:
                    if not response:
                        json_response = "]"
                    else:
                        json_response += "]"
            else:
                if not response:
                    json_response = ""
            self.write(json_response)

        if keep_alive and not last_batch:
            self.flush()
            get_more_callback()            
        else:
            if last_batch:
                self._remove_cursor()
                self.finish()
            else:
                get_more_callback()

    def _validate_psjson_profile(self):
        """
        Validates if the profile provided with the content-type is valid.
        """
        regex = re.compile(".*(?P<p>profile\=(?P<profile>[^\;\ ]*))")
        content_type = self.request.headers.get("Content-Type", "")
        # use the default schema
        if "profile" not in content_type:
            content_type += ";profile=" + \
                self.schemas_single[self.accept_content_type]
        match = re.match(regex, content_type)
        if not match:
            self.send_error(400, message="Bad Content Type '%s'" % content_type)
            return None
        profile = match.groupdict().get("profile", None)
        if not profile:
            self.send_error(400, message="Bad Content Type '%s'" % content_type)
            return None
        if profile != self.schemas_single[self.accept_content_type]:
            self.send_error(400, message="Bad schema '%s'" % profile)
            return None
        return profile

    @tornado.web.asynchronous
    @tornado.web.removeslash
    def post(self, res_id=None):
        # Check if the schema for conetnt type is known to the server
        accept_content_type = self.accept_content_type
        if accept_content_type not in self.schemas_single:
            message = "Unsupported accept content type '%s'" % \
                (accept_content_type)
            self.send_error(406, code=406001, message=message)
            return
        # POST requests don't work on specific IDs
        if res_id is not None:
            message = "Cannot POST to specific ID." + \
                " Try posting without an ID at the end of the URL."
            self.send_error(405, code=405001, message=message)
            return

        # Load the appropriate content type specific POST handler
        content_type = self.content_type
        # TODO (AH): Implement auto dispatch
        if content_type == MIME['PSJSON']:
            self.post_psjson()
        else:
            message = "No POST method is implemented fot content type '%s'" % \
                content_type
            self.send_error(415, code=415001, message=message)
            return
        return

    def rollback(self, resources, callback):
        """
        Try to delete resources from the database.
        Expecting a list of ObjectIDs.
        """
        items_list = []
        for item in resources:
            items_list.append(
                {
                    self.Id: item[self.Id],
                    self.timestamp: item[self.timestamp]
                }
            )
        remove_query = {'$or': items_list}
        self.dblayer.remove(remove_query, callback=callback)

    def register_urn(self, urn, schema, url):
        print "regiserting", urn, schema, url
        
    @gen.engine
    def post_psjson(self):
        """
        Handles HTTP POST request with Content Type of PSJSON.
        """
        profile = self._validate_psjson_profile()
        
        if not profile:
            return

        # Create objects from the body
        base_url = self.request.full_url()
        model_class = self._model_class
        
        result, error = yield DBOp(model_class.insert_resource,
            self.dblayer, self.request.body, base_url)
        
        if error is None:
            yield gen.Task(write_psjson, self, {'_id': {'$in': result}},
                success_status=201, is_list=False, show_location=True)
            self.finish()
        else:
            self.send_error(**error)

    @tornado.web.asynchronous
    @tornado.web.removeslash
    def put(self, res_id=None):
        # Check if the schema for conetnt type is known to the server
        accept_content_type = self.accept_content_type
        if accept_content_type not in self.schemas_single:
            message = "Unsupported accept content type '%s'" % \
                (accept_content_type)
            self.send_error(406, code=406002, message=message)
            return
        
        # PUT requests only work on specific IDs
        if res_id is None:
            message = "PUT is allowed only for specific resources. Try PUT" + \
                " to specific resource (with /id at the end of the URL)."
            self.send_error(405, code=405002, message=message)
            return

        # Load the appropriate content type specific PUT handler
        # TODO (AH): Implement auto dispatch
        content_type = self.content_type
        if content_type == MIME['PSJSON']:
            self.put_psjson(unicode(res_id))
        else:
            message = "No PUT method is implemented fot content type '%s'" % \
                content_type
            self.send_error(415, code=415002, message=message)
            return

    @gen.engine
    def put_psjson(self, res_id):
        """
        Validates and inserts HTTP PUT request with Content-Type of psjon.
        """
        # Create objects from the body
        base_url = "/".join(self.request.full_url().split("/")[:-1])
        model_class = self._model_class
        
        # TODO (AH): validate the ID and the selfref inside the resource 400008
        result, error = yield DBOp(model_class.insert_resource,
            self.dblayer, self.request.body, base_url)

        if error is None:
            yield gen.Task(write_psjson, self, {'_id': {'$in': result}},
                success_status=201, is_list=False, show_location=True)
            self.finish()
        else:
            self.send_error(**error)

    def on_connection_close(self):
        self._remove_cursor()
    
    @tornado.web.asynchronous
    @tornado.web.removeslash
    @gen.engine
    def delete(self, res_id=None):
        # Check if the schema for conetnt type is known to the server
        accept_content_type = self.accept_content_type
        if accept_content_type not in self.schemas_single:
            message = "Unsupported accept content type '%s'" % \
                (accept_content_type)
            self.send_error(406, code=406003, message=message)
            return

        # DELETE requests only work on specific IDs
        if res_id is None:
            message = "DELETE is allowed only for specific resources." + \
                " Try DELETE to specific resource " + \
                "(with /id at the end of the URL)."
            self.send_error(405, code=405003, message=message)
            return

        # Frist to try to fecth the resource to deleted
        res_id = unicode(res_id)
        query = {self.Id: res_id}
        cursor = self.dblayer.find(query)

        # TODO (AH): use aggregation to fetch the latest element
        response, error = yield DBOp(cursor.to_list)
        if error is not None:
            message = "Couldn't load the resource from the database: '%s'." % \
                str(error)
            self.send_error(500, code=500005, message=message)
            return
        if len(response) == 0:
            message = "Couldn't find resource with %s='%s'" % (self.Id, res_id)
            self.send_error(404, code=404002, message=message)
            return

        deleted = copy.copy(response[0])
        # Check that the resource wasn't already deleted
        if deleted.get("status", None) == "DELETED":
            message = "Resource already has been deleted at timestamp='%s'." % \
                str(deleted[self.timestamp])
            self.send_error(410, code=410001, message=message)
            return

        deleted["status"] = "DELETED"
        deleted[self.timestamp] = int(time.time() * 1000000) 
        response, error = yield DBOp(self.dblayer.insert, deleted)
        if error is not None:
            message = "Couldn't delete resource: '%s'." % str(error)
            self.send_error(500, code=500006, message=message)
            return
        self.finish()
