#!/usr/bin/env python
"""
Periscope HTTP(s) Handlers.
"""


MIME = {
    'HTML': 'text/html',
    'JSON': 'application/json',
    'PLAIN': 'text/plain',
    'SSE': 'text/event-stream',
    'PSJSON': 'application/perfsonar+json',
    'PSXML': 'application/perfsonar+xml',
}




# TODO (AH): cache common schemas locally
# TODO (AH): This is a very ugly way of handling cache!
CACHE = {
    "http://json-schema.org/draft-03/links#": {
        "additionalProperties": True,
        "type": "object"
    },
    "http://json-schema.org/draft-03/hyper-schema#": {
        "additionalProperties": True,
        "type": "object"
    },
}


import copy
import json
import functools
import time

import tornado.web
from tornado.httpclient import HTTPError
from tornado.httpclient import AsyncHTTPClient

from periscope.db import dumps_mongo
from periscope.models.unis import NetworkResource
from asyncmongo.errors import IntegrityError, TooManyConnections
from periscope.handlers.networkresource_handler import NetworkResourceHandler
from periscope.handlers.collection_handler import CollectionHandler



class MainHandler(tornado.web.RequestHandler):
    def initialize(self, base_url, resources):
        self._resources = resources
    
    def get(self):
        links = []
        for resource in self._resources:
            href = "%s://%s%s" % (self.request.protocol,
                self.request.host, self.reverse_url(resource))
            links.append({"href": href, "rel": "full"})
        self.set_header("Content-Type", MIME["JSON"])
        self.write(json.dumps(links, indent=4))

              
class EventsHandler(NetworkResourceHandler):        
        
    @tornado.web.asynchronous
    @tornado.web.removeslash
    def post(self, res_id=None):
        # Check if the schema for conetnt type is known to the server
        if self.accept_content_type not in self.schemas_single:
            message = "Schema is not defiend fot content of type '%s'" % \
                        (self.accept_content_type)
            self.send_error(500, message=message)
            return
        # POST requests don't work on specific IDs
        if res_id:
            message = "NetworkResource ID should not be defined."
            self.send_error(400, message=message)
            return

        # Load the appropriate content type specific POST handler
        if self.content_type == MIME['PSJSON']:
            self.post_psjson()
        else:
            self.send_error(500,
                message="No POST method is implemented fot this content type")
            return
        return

    def on_post(self, request, error=None, res_refs=None, return_resources=True, last=True):
        """
        HTTP POST callback to send the results to the client.
        """
        
        if error:
            if isinstance(error, IntegrityError):
                self.send_error(409,
                    message="Could't process the POST request '%s'" % \
                        str(error).replace("\"", "\\\""))
            else:
                self.send_error(500,
                    message="Could't process the POST request '%s'" % \
                        str(error).replace("\"", "\\\""))
            return                
        self.set_status(201)
        #pool = self.application.async_db._pool
        #pool.close()
        self.finish()

    def verify_metadata(self,response, collection_size,post_body):
        if response.error:
            self.send_error(400, message="metadata is not found '%s'." % response.error)
        else:
            body=json.loads(response.body)
            if body["id"] not in self.application.sync_db.collection_names():
                self.application.get_db_layer(body["id"],"ts","ts",True,collection_size)
                self.set_header("Location",
                    "%s/data/%s" % (self.request.full_url(), body["id"]))
                callback = functools.partial(self.on_post,
                                             res_refs=None, return_resources=True)
                post_body["ts"] = int(time.time() * 1000000)
                post_body["id"] = body["id"]
                self.dblayer.insert(post_body, callback=callback)
            else:
                self.send_error(401, message="event collection exists already")  
            
    def post_psjson(self):
        """
        Handles HTTP POST request with Content Type of PSJSON.
        """
        profile = self._validate_psjson_profile()
        if not profile:
            return
        try:
            body = json.loads(self.request.body)
        except Exception as exp:
            self.send_error(400, message="malformatted json request '%s'." % exp)
            return
        

        callback = functools.partial(self.verify_metadata,
                                     collection_size=body["collection_size"], post_body=body)
        
        http_client = AsyncHTTPClient()
        http_client.fetch(body["metadata_URL"], callback)        

    def del_stat_fields(self,generic):
        generic.pop("ns",None)
        generic.pop("numExtents",None)
        generic.pop("nindexes",None)
        generic.pop("lastExtentSize",None)
        generic.pop("paddingFactor",None)
        generic.pop("flags",None)
        generic.pop("totalIndexSize",None)
        generic.pop("indexSizes",None)
        generic.pop("max",None)
        generic.pop("ok",None)
        if generic["capped"] == 1:
            generic["capped"]="Yes"
        else:
            generic["capped"]="No"

       
    def generate_response(self,query,mid,response,index):
        try:
            command={"collStats":mid,"scale":1}
            generic = self.application.sync_db.command(command)
        except Exception as exp:
            self.send_error(400, message="At least one of the metadata ID is invalid.")
            return
              
        self.del_stat_fields(generic)
        specific={}
        if 'ts' in self.request.arguments.keys():       
            criteria=self.request.arguments['ts'][0].split('=')
            
            if criteria[0]=='gte':
                specific["startTime"]=int(criteria[1])
            if criteria[0]=='lte':
                specific["endTime"]=int(criteria[1])
            
            if self.request.arguments['ts'].__len__() > 1 :            
                criteria=self.request.arguments['ts'][1].split('=')
                if criteria[0]=='gte':
                    specific["startTime"]=int(criteria[1])
                if criteria[0]=='lte':
                    specific["endTime"]=int(criteria[1])
            
            db_query=copy.deepcopy(query)
            del db_query["$and"][index]
            specific["numRecords"]=self.application.sync_db[mid].find(db_query).count()
            
        response.insert(0,{})
        response[0]["mid"]=mid
        response[0]["generic"]=generic
        response[0]["queried"]=specific

                                            
    @tornado.web.asynchronous
    @tornado.web.removeslash
    def get(self, res_id=None):
        """Handles HTTP GET"""
        accept = self.accept_content_type
        if res_id:
            self._res_id = unicode(res_id)
        else:
            self._res_id = None
            
        parsed = self._parse_get_arguments()
        query = parsed["query"]
        fields = parsed["fields"]
        limit = parsed["limit"]
        is_list = not res_id
        self.set_header("Content-Type", "application/json")
        if query.__len__() == 0:
            if self._res_id is None:
                q = {}
            else:
                q = {"id": self._res_id}
            cursor =  self.application.sync_db["events_cache"].find(q)
            index = -1
            response = []
            obj = next(cursor,None)
            while obj:
                index = index+1
                mid = obj["metadata_URL"].split('/')[obj["metadata_URL"].split('/').__len__() - 1]
                self.generate_response(query,mid,response,index)
                obj = next(cursor, None)
            try:
                json_response = dumps_mongo(response, indent=2)
                self.write(json_response)
                self.finish()
            except Exception as exp:
                self.send_error(400, message="1 At least one of the metadata ID is invalid.")
                return                
        else:
            index=-1
            response=[]
            for d in query["$and"]:
                index=index+1
                if 'mids' in d.keys():
                    if isinstance(d["mids"],dict):
                        for m in d['mids']['$in']:
                            self.generate_response(query,m,response,index)
                    else:
                        self.generate_response(query,d['mids'],response,index)
            try:
                json_response = dumps_mongo(response, indent=2)
                self.write(json_response)
                self.finish()
            except Exception as exp:
                self.send_error(400, message="1 At least one of the metadata ID is invalid.")
                return                
        
class DataHandler(NetworkResourceHandler):        
        
    @tornado.web.asynchronous
    @tornado.web.removeslash
    def post(self, res_id=None):
        # Check if the schema for conetnt type is known to the server
        if self.accept_content_type not in self.schemas_single:
            message = "Schema is not defiend fot content of type '%s'" % \
                        (self.accept_content_type)
            self.send_error(500, message=message)
            return
        # POST requests don't work on specific IDs
        #if res_id:
        #    message = "NetworkResource ID should not be defined."
        #    self.send_error(400, message=message)
        #    return
        self._res_id=res_id
        #Load the appropriate content type specific POST handler
        if self.content_type == MIME['PSJSON']:
            self.post_psjson()
        else:
            self.send_error(500,
                message="No POST method is implemented for this content type")
            return
        return
    
    def on_post(self, request, error=None, res_refs=None, return_resources=True, last=True):
        """
        HTTP POST callback to send the results to the client.
        """
        
        if error:
            if isinstance(error, IntegrityError):
                self.send_error(409,
                    message="Could't process the POST request '%s'" % \
                        str(error).replace("\"", "\\\""))
            else:
                self.send_error(500,
                    message="Could't process the POST request '%s'" % \
                        str(error).replace("\"", "\\\""))
            return
        
        if return_resources:
            query = {"$or": []}
            for res_ref in res_refs:
                query["$or"].append(res_ref)
            self.dblayer.find(query, self._return_resources)
        else:
            if last:
                accept = self.accept_content_type
                self.set_header("Content-Type", accept + \
                                " ;profile="+ self.schemas_single[accept])
                if len(res_refs) == 1:
                    self.set_header("Location",
                                    "%s/%s" % (self.request.full_url(), res_refs[0][self.Id]))
                
                self.set_status(201)
                #pool = self.application.async_db._pool
                #pool.close()
                self.finish()   
                     
    def post_psjson(self):
        """
        Handles HTTP POST request with Content Type of PSJSON.
        """                    
        profile = self._validate_psjson_profile()
        if not profile:
            return
        try:
            body = json.loads(self.request.body)
        except Exception as exp:
            self.send_error(400, message="malformatted json request '%s'." % exp)
            return
        if self._res_id:
            res_refs = []
            if self._res_id in self.application.sync_db.collection_names():
                callback = functools.partial(self.on_post,
                        res_refs=res_refs, return_resources=False,last=True)
                try:
                    self.application.async_db[self._res_id].insert(body["data"], callback=callback)
                except TooManyConnections:
                    self.send_error(503, message="Too many DB connections")
                    return
            else:
                self.send_error(400, message="The collection for metadata ID '%s' does not exist" % self._res_id)
                return
        else:
            col_names = self.application.sync_db.collection_names()
            data={}
            for i in range(0,body.__len__()):
                mid = body[i]['mid']
                dataraw = body[i]['data']
                if(mid in data.keys()):
                    data[mid].extend(dataraw)
                else :
                    data[mid]=dataraw
                   
            mids = data.keys()
            
            for i in range(0,mids.__len__()):    
                res_refs = []
                if mids[i] in col_names:
                    if i+1 == mids.__len__():
                        callback = functools.partial(self.on_post,
                                                     res_refs=res_refs, return_resources=False,last=True)
                    else:
                        callback = functools.partial(self.on_post,
                                                     res_refs=res_refs, return_resources=False,last=False)
                    try:
                        self.application.async_db[mids[i]].insert(data[mids[i]], callback=callback)
                    except TooManyConnections:
                        self.send_error(503, message="Too many DB connections")
                        return
                else:
                    self.send_error(400, message="The collection for metadata ID '%s' does not exist" % mids[i])
                    return

    @tornado.web.asynchronous
    @tornado.web.removeslash
    def get(self, res_id=None):
        """Handles HTTP GET"""
        accept = self.accept_content_type
        if res_id:
            self._res_id = unicode(res_id)
        else:
            self.send_error(500, message="You need to specify the metadata ID in the URL while querying the data")
            return
        
        parsed = self._parse_get_arguments()
        query = parsed["query"]
        fields = parsed["fields"]
        fields["_id"] = 0
        limit = parsed["limit"]
        if limit == None:
            limit = 1000000000

        is_list = True #, not res_id
        if query:
            is_list = True
        callback = functools.partial(self._get_on_response,
                            new=True, is_list=is_list, query=query)
        self._find(query, callback, fields=fields, limit=limit)

    def _find(self, query, callback, fields=None, limit=None):
        """Query the database.

        Parameters:

        callback: a function to be called back in case of new data.
                callback function should have `response`, `error`,
                and `new` fields. `new` is going to be True.
        """
        keep_alive = self.supports_streaming or self.supports_sse()
        if self._res_id:
            query[self.Id] = self._res_id
        options = dict(query=query, callback=callback)#, await_data=True)
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
        db_layer = self.application.get_db_layer(self._res_id, "ts", "ts",
                        True,  5000)
        query.pop("id", None)
        self._cursor = db_layer.find(**options)        
