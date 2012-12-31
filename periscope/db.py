#!/usr/bin/env python
"""
Databases related classes
"""
import abc
import asyncmongo
import functools
import json
import time
from bson.objectid import ObjectId
from bson.json_util import dumps
from netlogger import nllog

# Motor is optional
MOTORINSTALLED = True
try:
    import motor
except ImportError:
    MOTORINSTALLED = False


DUMPS_MONGO = dumps
OBJECTID = ObjectId


class MongoEncoder(json.JSONEncoder):
    """Special JSON encoder that converts Mongo ObjectIDs to string"""
    def _iterencode(self, obj, markers=None):
        if isinstance(obj, ObjectId):
            return """ObjectId("%s")""" % str(obj)
        else:
            return json.JSONEncoder._iterencode(self, obj, markers)


class AbstractDBCursor(object):
    __metaclass__ = abc.ABCMeta

    @abc.abstractproperty
    def fetch_next(self):
        pass

    @abc.abstractmethod
    def next_object(self):
        pass

    @abc.abstractmethod
    def each(self, callback):
        pass

    @abc.abstractmethod
    def to_list(self, length=None, callback=None):
        pass

    @abc.abstractmethod
    def tail(self, callback):
        pass


class AsyncmongoDBCursor(AbstractDBCursor):
    def __init__(self, asyncmongo_cursor):
        self.__cursor = asyncmongo_cursor

    @abc.abstractproperty
    def fetch_next(self):
        pass

    @abc.abstractmethod
    def next_object(self):
        pass

    @abc.abstractmethod
    def each(self, callback):
        pass

    @abc.abstractmethod
    def to_list(self, length=None, callback=None):
        pass

    @abc.abstractmethod
    def tail(self, callback):
        pass


class AbstractDBLayer(object, nllog.DoesLogging):
    """Thin layer asynchronous model to handle network objects.

    Right now this layer doesn't do much, but provides away to intercept
    the database calls for any future improvements or updates.

    Unfortuantly uncapped collections in Mongo must have a uniqe '_id'
    field, so this layer will generate one for each insert based on the
    network resource id and the revision number.
    """
    __metaclass__ = abc.ABCMeta

    def __init__(self, client, collection_name, capped=False, id_field="id",
                 timestamp_field="ts"):
        """Intializes with a reference to the mongodb collection."""
        nllog.DoesLogging.__init__(self)
        self.id_field = id_field
        self.timestamp_field = timestamp_field
        self.capped = capped
        self._collection_name = collection_name
        self._client = client

    @property
    def collection(self):
        """Returns a reference to the default mongodb collection."""
        return self._client[self._collection_name]

    @abc.abstractmethod
    def find(self, query, callback=None, **kwargs):
        """Find one or more documents in the collection."""
        pass

    @abc.abstractmethod
    def insert(self, data, callback=None, **kwargs):
        """Inserts data to the collection."""
        pass

    @abc.abstractmethod
    def update(self, query, data, callback=None, **kwargs):
        """Updates data found by query in the collection."""
        pass

    @abc.abstractmethod
    def remove(self, query, callback=None, **kwargs):
        """Remove objects from the database that matches a query."""
        pass


class IncompleteMongoDBLayer(AbstractDBLayer):
    """
    Incomplete implementation that is shared between asyncmongo and motor.
    """

    def _insert_id(self, data):
        """
        Utility to make sure that each resource has a proper ID and timestamp.

        returns an '_id' for each object
        """
        # First make sure that there is a timestamp
        timestamp = data.get(self.timestamp_field, None)
        if timestamp is None:
            timestamp = int(time.time() * 1000000)
            data[self.timestamp_field] = timestamp
        if '_id' not in data:
            data['_id'] = ObjectId()
        if self.id_field not in data:
            data[self.id_field] = str(data['_id'])
        return data['_id']

    def _insert_callback(self, result, error, object_ids, is_list, callback):
        """
        Utility method to make sure that the ObjectIDs are returend to the user.
        """
        self.log.debug("_insert_callback.start")
        if error is not None:
            callback(None, error=error)
        if not is_list:
            object_ids = object_ids[0]
        self.log.debug("_insert_callback.end")
        self.log.info("insert.end")
        callback(object_ids, error=error)

    def insert(self, data, callback=None, **kwargs):
        """Inserts data to the collection.

        Asyncmongo driver doesn't return the ObjectIDs of the inserted object.
        This class caches the inserted IDs in advance and issue a find to
        reterive them.
        """
        self.log.info("insert.start")
        is_list = isinstance(data, list)
        # It's easier to treat the data as a list
        if is_list:
            ldata = data
        else:
            ldata = [data]

        obj_ids = [self._insert_id(obj) for obj in ldata]
        icallback = functools.partial(self._insert_callback,
                                      object_ids=obj_ids, is_list=is_list,
                                      callback=callback)
        return self.collection.insert(data, callback=icallback, **kwargs)


class AsyncmongoDBLayer(IncompleteMongoDBLayer):
    """Thin layer asynchronous model to handle network objects.

    Right now this layer doesn't do much, but provides away to intercept
    the database calls for any future improvements or updates.

    Unfortuantly uncapped collections in Mongo must have a uniqe '_id'
    field, so this layer will generate one for each insert based on the
    network resource id and the revision number.
    """

    def find(self, query, callback=None, **kwargs):
        """Finds one or more elements in the collection."""
        self.log.info("find")
        fields = kwargs.pop("fields", {})
        fields["_id"] = 0
        cursor = self.collection.find(query, fields=fields,
                                      callback=callback, **kwargs)
        return cursor

    def _strip_list_callback(self, result, error, callback):
        """
        Asyncmongo returns result in list with one element.
        This utility method extract that element to make it easier for the
        client to deal with it.
        """
        self.log.debug("_strip_list_callback.start")
        if error is not None:
            callback(result, error)
        callback(result[0], error)
        self.log.debug("_strip_list_callback.end")

    def update(self, query, data, callback=None, **kwargs):
        """Updates data found by query in the collection."""
        self.log.info("update.start")
        ucallback = functools.partial(self._strip_list_callback,
                                      callback=callback)
        ret = self.collection.update(query, data, callback=ucallback, **kwargs)
        self.log.info("update.end")
        return ret

    def remove(self, query, callback=None, **kwargs):
        """Remove objects from the database that matches a query."""
        self.log.info("remove.start")
        rcallback = functools.partial(self._strip_list_callback,
                                      callback=callback)
        ret = self.collection.remove(query, callback=rcallback, **kwargs)
        self.log.info("remove.end")
        return ret


class MotorDBLayer(IncompleteMongoDBLayer):
    """Thin layer asynchronous model to handle network objects.

    Right now this layer doesn't do much, but provides away to intercept
    the database calls for any future improvements or updates.

    Unfortuantly uncapped collections in Mongo must have a uniqe '_id'
    field, so this layer will generate one for each insert based on the
    network resource id and the revision number.
    """

    def find(self, query, callback=None, **kwargs):
        """Finds one or more elements in the collection."""
        self.log.info("find")
        fields = kwargs.pop("fields", {})
        fields["_id"] = 0
        cursor = self.collection.find(query,
                                      fields=fields, **kwargs)
        if callback is None:
            return cursor
        else:
            return cursor.to_list(length=None, callback=callback)

    def update(self, query, data, callback=None, **kwargs):
        """Updates data found by query in the collection."""
        self.log.info("update")
        return self.collection.update(query, data, callback=callback, **kwargs)

    def remove(self, query, callback=None, **kwargs):
        """Remove objects from the database that matches a query."""
        self.log.info("remove")
        return self.collection.remove(query, callback=callback, **kwargs)


class DBLayerFactory(object):
    """Factory class to load the right DBLayer implementation."""

    @staticmethod
    def new_dblayer(client, *args, **kwargs):
        """
        Creates an instance of the right DBLayer implementatino for the client.
        """
        if isinstance(client, asyncmongo.client.Client):
            return AsyncmongoDBLayer(client, *args, **kwargs)
        else:
            return MotorDBLayer(client, *args, **kwargs)
