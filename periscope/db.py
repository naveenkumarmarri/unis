#!/usr/bin/env python
"""
Databases related classes
"""
import time
import functools
import settings
import auth
from json import JSONEncoder
from netlogger import nllog
from settings import DB_AUTH

AuthField = DB_AUTH['auth_field']
AuthDefault = DB_AUTH['auth_default']

class MongoEncoder(JSONEncoder):
    """Special JSON encoder that converts Mongo ObjectIDs to string"""
    def _iterencode(self, obj, markers=None):
        if isinstance(obj, ObjectId):
            return """ObjectId("%s")""" % str(obj)
        else:
            return JSONEncoder._iterencode(self, obj, markers)

import pymongo
if pymongo.version_tuple[1] > 1:
    from bson.objectid import ObjectId
    import bson.json_util
    dumps_mongo = bson.json_util.dumps
else:
    from pymongo.objectid import ObjectId
    import json
    dumps_mongo = functools.partial(json.dumps, cls=MongoEncoder)

class DBLayer(object, nllog.DoesLogging):
    """Thin layer asynchronous model to handle network objects.

    Right now this layer doesn't do much, but provides away to intercept
    the database calls for any future improvements or updates.

    Unfortuantly uncapped collections in Mongo must have a uniqe '_id'
    field, so this layer will generate one for each insert based on the
    network resource id and the revision number.
    """

    def __init__(self, client, collection_name, capped=False, Id="id", \
        timestamp="ts"):
        """Intializes with a reference to the mongodb collection."""
        nllog.DoesLogging.__init__(self)
        self.Id = Id
        self.timestamp = timestamp
        self.capped = capped
        self._collection_name = collection_name
        self._client = client

    @property
    def collection(self):
        """Returns a reference to the default mongodb collection."""
        return self._client[self._collection_name]

    def find(self, query, callback=None, ccallback = None,**kwargs):
        """Finds one or more elements in the collection."""                
        self.log.info("find for Collection: [" + self._collection_name + "]")
        fields = kwargs.pop("fields", {})
        fields["_id"] = 0
        self.log.info(str(query))
        findCursor = self.collection.find(query, callback=callback,
                                          fields=fields, **kwargs)
        if ccallback:
            self._client['$cmd'].find_one({'count' : self._collection_name , 'query' : query}, _is_command=True, callback=ccallback)

        return findCursor 

    def _insert_id(self, data):
        if "_id" not in data and not self.capped:
            res_id = data.get(self.Id, str(ObjectId()))
            timestamp = data.get(self.timestamp, int(time.time() * 1000000))
            data["_id"] = "%s:%s" % (res_id, timestamp)
            
    def insert(self, data,cert=None,callback=None, **kwargs):
        """Inserts data to the collection."""
        # TODO - Not sure how to deal with insert ,
        # is filtering the data out as per attributes an option ?, Large inserts might kill the server or be slow
        if cert == None:
            """Select a default filter token"""
            """ Should probably stop inserts and throw error """
        else:
            """ Get a list of attributes for this certificate """            
            attList = self._auth.getAllowedAttributes(cert)
            
        self.log.info("insert for Collection: [" + self._collection_name + "]")
        if isinstance(data, list) and not self.capped:
            for item in data:
                self._insert_id(item)
        elif not self.capped:
            self._insert_id(data)                    
        return self.collection.insert(data, callback=callback, **kwargs)

    def update(self, query, data,cert=None, callback=None, **kwargs):
        """Updates data found by query in the collection."""
        self.log.info("Update for Collection: [" + self._collection_name + "]")
        return self.collection.update(query, data, callback=callback, **kwargs)

    def remove(self, query, cert,callback=None, **kwargs):
        """Remove objects from the database that matches a query."""        
        self.log.info("Delete for Collection: [" + self._collection_name + "]")
        return self.collection.remove(query, callback=callback, **kwargs)
        

