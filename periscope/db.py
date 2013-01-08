#!/usr/bin/env python
"""
Databases related classes.

See the following example:

.. code-block:: python

    import motor
    from tornado import gen
    from tornado.ioloop import IOLoop
    from periscope.db import DBLayerFactory


    # Example inserting one document at a time
    @gen.engine
    def insert_one():
        db = motor.MotorClient().open_sync().test
        dblayer = DBLayerFactory.new_dblayer(db, 'test')
        ret = yield gen.Task(dblayer.insert, {'name': 'a'})
        error = ret.kwargs.get('error')
        if error is not None:
            print "Error", error
        else:
            obj_id = ret.args[0]
            print "Inserted", obj_id


    # Example to iterate all docs in a collection
    @gen.engine
    def print_all():
        db = motor.MotorClient().open_sync().test
        dblayer = DBLayerFactory.new_dblayer(db, 'test')
        cursor = dblayer.find({})  #Get all
        while (yield cursor.fetch_next):
            doc = cursor.next_object()
            print "Found", doc

    insert_one()
    print_all()
    IOLoop.instance().start()
"""

__author__ = 'Ahmed El-Hassany <a.hassany@gmail.com>'
__license__ = 'http://www.apache.org/licenses/LICENSE-2.0'

import abc
import functools
import time
import pymongo
from bson.objectid import ObjectId as MongoObjectId
from bson.json_util import dumps
from collections import deque
from netlogger import nllog
from tornado import gen
from tornado import ioloop
from periscope.utils import class_fullname

# Motor is optional
MOTOR_INSTALLED = True
try:
    import motor
except ImportError:
    MOTOR_INSTALLED = False

# Asyncmongo is optional
ASYNCMONGO_INSTALLED = True
try:
    import asyncmongo
except ImportError:
    ASYNCMONGO_INSTALLED = False


def dumps_mongo(obj, **kwargs):
    """Generate a mongodb document for an object."""
    return dumps(obj, **kwargs)


def object_id():
    """Generates a unique Object ID."""
    return MongoObjectId()


class AbstractDBCursor(object):
    """Used with the the find database operations.

    This class wraps around the native cursor to unify the operations across
    different drivers.
    """
    __metaclass__ = abc.ABCMeta

    def __init__(self, native_cursor):
        """
        Initialize with the native cursor to wrap around.
        """
        self.native_cursor = native_cursor

    @abc.abstractproperty
    def fetch_next(self):
        """Asynchronously retrieve the next document in the result set from the
        database.

        See :attr:`next_object`.
        """
        pass

    @abc.abstractmethod
    def next_object(self):
        """Get a document from the most recently fetched batch, or ``None``.

        See :attr:`fetch_next`.
        """
        pass

    @abc.abstractmethod
    def each(self, callback):
        """Iterates over all the documents for this cursor.

        If `callback` returns None the the each function will stop.

        :Parameters:
         - `callback`: function taking (documents, error)
        """
        pass

    @abc.abstractmethod
    def to_list(self, length=None, callback=None):
        """Get a list of documents.

        :Parameters:
          - `length`: optional, maximum number of documents to return for this
            call
          - `callback`: function taking (documents, error)
        """
        pass

    @abc.abstractmethod
    def tail(self, callback):
        """Invokes the callback once new document is inserted to the database.

        If `callback` returns None the the each function will stop.

        :Parameters:
          - `callback`: function taking (documents, error)
        """
        pass


class _AsyncmongoFetchNext(gen.YieldPoint):
    """Utility class to be used with AsyncmongoDBCursor fetch_next."""
    def __init__(self, cursor):
        self.cursor = cursor
        self.error = None
        self.ready = False
        self.runner = None

    def start(self, runner):
        # If cursor's current batch is empty, start fetching next batch...
        cursor = self.cursor
        if cursor._has_results is False:
            self.ready = False
            self.runner = runner
            cursor._invoke_find(callback=self.set_result)
        elif not cursor.buffer_size and cursor.native_cursor.alive:
            self.ready = False
            self.runner = runner
            cursor._get_more(self.set_result)
        else:
            self.ready = True

    def set_result(self, result=None, error=None):
        # 'result' is _get_more's return value, the number of docs fetched
        self.error = error
        self.ready = True
        runner, self.runner = self.runner, None  # Break cycle
        runner.run()

    def is_ready(self):
        # True unless we're in the midst of a fetch
        return self.ready

    def get_result(self):
        if self.error is not None:
            raise self.error
        return bool(self.cursor.buffer_size)


class AsyncmongoDBCursor(AbstractDBCursor):
    # TODO (AH): Fix tailable cursors
    # TODO (AH): fix each
    """Abstract DBCursor implementation that works with AsyncmongoDBLayer.

    :Parameters:
      - `native_cursor`: See :class:`periscope.db.AbstractDBCursor`.
      - `find_call`: a partial function that calls find.

    See :class:`periscope.db.AbstractDBCursor`.
    """
    def __init__(self, native_cursor, find_call):
        super(AsyncmongoDBCursor, self).__init__(native_cursor)
        self._data = None
        self._error = None
        self._has_results = False
        self._find_call = find_call

    @property
    def buffer_size(self):
        """Returns the size of the data buffered in this cursor."""
        return len(self._data) if self._data is not None else 0

    def _find_callback(self, result, error, callback):
        """Thee callback when asyncmongo collection find is called."""
        if error is not None:
            self._data = None
            self._error = error
        else:
            if result is None:
                result = []
            if not isinstance(result, list):
                result = [result]
            self._data = deque(result)
            self._error = error
        self._has_results = True
        callback()

    def _get_more_callback(self, result, error, callback):
        """A wrapper callback for _get_more to store the result in self._data.
        """
        if self._data is None:
            self._data = deque([])
        if result is None:
            result = []
        if not isinstance(result, list):
            result = [result]
        self._data.extend(result)
        self._error = error
        self._has_results = True
        callback()

    def _get_more(self, callback):
        """Fetch more data from the database."""
        if not self.native_cursor.alive:
            raise pymongo.errors.InvalidOperation(
                "Can't call get_more() on a Cursor that has been"
                " exhausted or killed."
            )
        more_callback = functools.partial(self._get_more_callback,
                                          callback=callback)
        self.native_cursor.get_more(more_callback)

    def _invoke_find(self, callback):
        """Actuall invokes the collection.find operation"""
        find_callback = functools.partial(self._find_callback,
                                          callback=callback)
        cursor = self._find_call(callback=find_callback)
        self.native_cursor = cursor

    @property
    def fetch_next(self):
        """See :attr:`periscope.db.AbstractDBCursor.fetch_next`"""
        return _AsyncmongoFetchNext(self)

    def next_object(self):
        """See :meth:`periscope.db.AbstractDBCursor.next_object`"""
        if self.buffer_size == 0:
            raise StopIteration
        return self._data.popleft()

    def each(self, callback):
        """See :meth:`periscope.db.AbstractDBCursor.each`"""
        each_callback = functools.partial(self.each, callback=callback)
        if self._has_results is False:
            self._find_call.keywords['await_data'] = True
            self._invoke_find(each_callback)
            return

        data = self._data or deque([])
        for datum in data:
            if callback(datum, self._error) is None:
                return
        if len(data) == 0 and self.native_cursor.alive is True:
            self._get_more(callback=each_callback)
        else:
            callback(None, None)

    def to_list(self, length=None, callback=None):
        """See :meth:`periscope.db.AbstractDBCursor.to_list`"""
        tolist_callback = functools.partial(self.to_list, length=length,
                                            callback=callback)
        if self._has_results is False:
            self._invoke_find(tolist_callback)
            return

        data = self._data or deque([])
        the_list = []
        # If no length specifed return every thing
        if length is None:
            length = len(data)
        # if the data is not enought fetch more
        if len(data) < length \
                and self.native_cursor is not None \
                and self.native_cursor.alive is True:
            self._get_more(callback=tolist_callback)
        else:
            while len(data) > 0 and length != 0:
                length -= 1
                the_list.append(data.popleft())
            callback(the_list, self._error)

    def tail(self, callback):
        """See :meth:`periscope.db.AbstractDBCursor.tail`"""
        find_call = self._find_call
        find_call.keywords['tailable'] = True
        find_call.keywords['await_data'] = True
        self._find_call = find_call
        cursor = self
        each_callback = functools.partial(cursor._tail_got_more,
                                          cursor, callback)
        cursor.each(each_callback)

    def _tail_got_more(self, cursor, callback, result, error):
        """Called when the collection that tailed has new data."""
        if error is not None:
            cursor.native_cursor.kill()
            callback(None, error)
        elif result is not None:
            if callback(result, None) is None:
                cursor.native_cursor.kill()
                return False

        if not cursor.native_cursor.alive:
            loop = ioloop.IOLoop.instance()
            loop.add_timeout(time.time() + 0.5,
                             functools.partial(cursor.tail, callback))


class MotorDBCursor(AbstractDBCursor):
    """Abstract DBCursor implementation that works with MotorDBLayer.

    See :class:`periscope.db.AbstractDBCursor`.
    """
    def __init__(self, native_cursor):
        super(MotorDBCursor, self).__init__(native_cursor)

    @property
    def fetch_next(self):
        """See :attr:`periscope.db.AbstractDBCursor.fetch_next`"""
        return self.native_cursor.fetch_next

    def next_object(self):
        """See :meth:`periscope.db.AbstractDBCursor.next_object`"""
        return self.native_cursor.next_object()

    def each(self, callback):
        """See :meth:`periscope.db.AbstractDBCursor.each`"""
        return self.native_cursor.each(callback)

    def to_list(self, length=None, callback=None):
        """See :meth:`periscope.db.AbstractDBCursor.to_list`"""
        return self.native_cursor.to_list(length, callback)

    def tail(self, callback):
        """See :meth:`periscope.db.AbstractDBCursor.tail`"""
        return self.native_cursor.tail(callback)


class AbstractDBLayer(object, nllog.DoesLogging):
    """This class provides a thin layer that wraps around the specific databate
    implementation.

    Right now this layer doesn't do much, but provides away to intercept
    the database calls for any future improvements or updates.

    :Parameters:
    - `client`: the database driver client or connection. The connection is
        assumed to be established.
    - `collection_name`: the name of the database collection that this layer
        will talk to.
    - `capped`: True if the collection is capped collection. See MongoDB capped
        collections.
    - `id_field`: The name of the identifier field
    - `timestamp_field`: The name of the timestamp field
    """
    __metaclass__ = abc.ABCMeta

    def __init__(self, client, collection_name, capped=False, id_field="id",
                 timestamp_field="ts"):
        """Creates DBLayer
        """
        nllog.DoesLogging.__init__(self)
        self.id_field = id_field
        self.timestamp_field = timestamp_field
        self.capped = capped
        self._collection_name = collection_name
        self._client = client

    @property
    def collection(self):
        """Returns a reference to the collection handled by this layer."""
        return self._client[self._collection_name]

    @abc.abstractmethod
    def find(self, query, **kwargs):
        """Find one or more documents in the collection.

        :Parameters:
        - `query`: the database query.
        - `kwargs`: see mongodb find query argumenets
        """
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

    @abc.abstractmethod
    def aggregate(self, query, callback=None, **kwargs):
        """Perform aggeragatation query"""
        pass


class IncompleteMongoDBLayer(AbstractDBLayer):
    """
    Incomplete implementation that is shared between asyncmongo and motor.
    """

    def _insert_id(self, data):
        """
        Utility to make sure that each resource has a proper ID and timestamp.

        Returns:
            The id of the document
        """
        # First make sure that there is a timestamp
        timestamp = data.get(self.timestamp_field, None)
        if timestamp is None:
            timestamp = int(time.time() * 1000000)
            data[self.timestamp_field] = timestamp
        if '_id' not in data:
            data['_id'] = object_id()
        if self.id_field not in data:
            data[self.id_field] = str(data['_id'])
        return data['_id']

    def _insert_callback(self, result, error, object_ids, is_list, callback):
        """
        Utility method to make sure that the ObjectIDs are returend to the user
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
        ldata = data if is_list is True else [data]
        obj_ids = [self._insert_id(obj) for obj in ldata]
        icallback = functools.partial(self._insert_callback,
                                      object_ids=obj_ids, is_list=is_list,
                                      callback=callback)
        return self.collection.insert(data, callback=icallback, **kwargs)


class AsyncmongoDBLayer(IncompleteMongoDBLayer):
    """
    AbstractDBLayer implementation that works with asyncmongo driver.

    See :class:`periscope.db.AbstractDBLayer`.
    """
    def find(self, query, **kwargs):
        """See :meth:`periscope.db.AbstractDBLayer.find`."""
        self.log.info("find")
        fields = kwargs.pop("fields", {})
        # Hide the _id field by default, unless requested
        if '_id' not in fields:
            fields["_id"] = 0
        find_call = functools.partial(self.collection.find, query,
                                      fields=fields, **kwargs)
        return AsyncmongoDBCursor(None, find_call)

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
        """See :meth:`periscope.db.AbstractDBLayer.update`."""
        self.log.info("update.start")
        ucallback = functools.partial(self._strip_list_callback,
                                      callback=callback)
        ret = self.collection.update(query, data, callback=ucallback, **kwargs)
        self.log.info("update.end")
        return ret

    def remove(self, query, callback=None, **kwargs):
        """See :meth:`periscope.db.AbstractDBLayer.remove`."""
        self.log.info("remove.start")
        rcallback = functools.partial(self._strip_list_callback,
                                      callback=callback)
        ret = self.collection.remove(query, callback=rcallback, **kwargs)
        self.log.info("remove.end")
        return ret

    def aggregate(self, query, callback, **kwargs):
        # TODO (AH): Implement this to use aggregate from sync driver
        """See :meth:`periscope.db.AbstractDBLayer.aggregate`."""
        pass


class MotorDBLayer(IncompleteMongoDBLayer):
    """
    AbstractDBLayer implementation that works with motor driver.

    See :class:`periscope.db.AbstractDBLayer`.
    """
    def find(self, query, **kwargs):
        """See :meth:`periscope.db.AbstractDBLayer.find`."""
        self.log.info('find.start')
        fields = kwargs.pop("fields", {})
        fields["_id"] = 0
        cursor = self.collection.find(query,
                                      fields=fields, **kwargs)
        self.log.info('find.end')
        return MotorDBCursor(cursor)

    def update(self, query, data, callback=None, **kwargs):
        """See :meth:`periscope.db.AbstractDBLayer.update`."""
        self.log.info("update.start")
        ret = self.collection.update(query, data, callback=callback, **kwargs)
        self.log.info("update.end")
        return ret

    def remove(self, query, callback=None, **kwargs):
        """See :meth:`periscope.db.AbstractDBLayer.remove`."""
        self.log.info("remove.start")
        ret = self.collection.remove(query, callback=callback, **kwargs)
        self.log.info("remove.end")
        return ret

    def aggregate(self, query, callback, **kwargs):
        """See :meth:`periscope.db.AbstractDBLayer.aggregate`."""
        self.log.info("aggregate.start")
        ret = self.collection.aggregate(query, callback=callback, **kwargs)
        self.log.info("aggregate.end")
        return ret


class PyMongoDBLayer(AbstractDBLayer):
    """This simulates asynchronous operations on pymongo.
    This is NOT a non-blocking layer. DO NOT use this inside tornado IOLoop.
    """
    __metaclass__ = abc.ABCMeta

    def find(self, query, callback=None, **kwargs):
        results = self.collection.find(query, **kwargs)
        callback(results, error=None)

    def insert(self, data, callback=None, **kwargs):
        new_objs = self.collection.insert(data, **kwargs)
        callback(new_objs, error=None)

    def update(self, query, data, callback=None, **kwargs):
        result = self.collection.update(query, **kwargs)
        callback(result, error=None)

    def remove(self, query, callback=None, **kwargs):
        result = self.collection.remove(query, **kwargs)
        callback(result, error=None)


class DBLayerFactory(object):
    """Factory class to load the right DBLayer implementation."""

    @staticmethod
    def new_dblayer(client, *args, **kwargs):
        """
        Creates an instance of the right DBLayer implementation for the client.
        """
        return DBLayerFactory.dblayer_class(client)(client, *args, **kwargs)

    @staticmethod
    def dblayer_class(client=None):
        """
        Returns the DBLayer class for the client.
        """
        class_name = class_fullname(client)
        if client is None:
            if MOTOR_INSTALLED is True:
                return MotorDBLayer
            elif ASYNCMONGO_INSTALLED is True:
                return AsyncmongoDBLayer
            else:
                raise Exception("Neither Motor or Asyncmongo is installed.")

        if class_name == 'motor.MotorDatabase':
            return MotorDBLayer
        elif class_name == 'asyncmongo.client.Client':
            return AsyncmongoDBLayer
        else:
            raise Exception("No implementation for '%s'" % class_name)
