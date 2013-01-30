"""
Basic classes for unit testing.
"""

import pymongo
import random
import tornado.web
import unittest2
from copy import copy
from tornado.testing import AsyncTestCase
from tornado.testing import AsyncHTTPTestCase
from periscope.test import settings
from periscope.db import DBLayerFactory
from tornado.ioloop import IOLoop
from tornado import gen

# Motor is optional
MOTOR_INSTALLED = True
try:
    import motor
except ImportError:
    MOTOR_INSTALLED = False
    motor = None

# Asyncmongo is optional
ASYNCMONGO_INSTALLED = True
try:
    import asyncmongo
except ImportError:
    ASYNCMONGO_INSTALLED = False
    asyncmongo = None


class TestApp(tornado.web.Application):
    """Simple App to be used with testing."""
    @property
    def asyncmogno_db(self):
        """Returns a reference to asyncmongo DB connection."""
        if not getattr(self, '_async_db', None):
            if hasattr(self, 'io_loop'):
                # Unit testint is going to create different IOLoop instances
                # for each test case, thus we need to make sure that different
                # connection pools is used
                settings.ASYNC_DB['io_loop'] = self.io_loop
                settings.ASYNC_DB['pool_id'] = "pool_%d" \
                                               % int(random.random() * 100000)
            self._async_db = asyncmongo.Client(**settings.ASYNC_DB)
        return self._async_db

    def register_urn(self, resource, callback):
        callback(None, None)

    def creat_pubsub(self):
        if 'pubsub' not in self.sync_db.collection_names():
            self.sync_db.create_collection('pubsub',
                capped=True, size=10000)
        self._pubsub = DBLayerFactory.new_dblayer(self.async_db, 'pubsub', capped=True)

    def publish(self, resource, callback, res_type=None):
        if not hasattr(self, '_pubsub'):
            self.creat_pubsub()
        tmp ={}
        tmp['id'] = resource['id']
        tmp['id'] = resource['id']
        res_type2 = resource['$schema'].rstrip('#').split('/')[-1]
        tmp['type'] = res_type or res_type2
        tmp['resource'] = dict(resource.to_mongoiter())
        print "Publishing", tmp
        self._pubsub.insert(tmp, callback)
        print "END Publishing"

    def subscribe(self, query, callback):
        if not hasattr(self, '_pubsub'):
            self.creat_pubsub()
        cursor = self._pubsub.find(query, tailable=True, await_data=True)
        cursor.each(callback=callback)

    @property
    def motor_db(self):
        """Returns a reference to motor DB connection."""
        conn = motor.MotorClient(**settings.MOTOR_DB).open_sync()
        return conn[settings.DB_NAME]

    @property
    def sync_db(self):
        """Returns a reference to pymongo DB connection."""
        conn = pymongo.Connection(**settings.SYNC_DB)
        return conn[settings.DB_NAME]

    @property
    def async_db(self):
        if MOTOR_INSTALLED:
            return self.motor_db
        elif ASYNCMONGO_INSTALLED:
            return self.asyncmogno_db
        else:
            raise Exception("Neither motor or asyncmongo are installed")

    def get_db_layer(self, collection_name, id_field_name,
                     timestamp_field_name, is_capped_collection,
                     capped_collection_size):
        # Initialize the capped collection, if necessary!
        if is_capped_collection and \
                collection_name not in self.sync_db.collection_names():
            self.sync_db.create_collection(collection_name, capped=True,
                                           size=capped_collection_size)
        # Make indexes
        index = [(id_field_name, 1), (timestamp_field_name, -1)]
        self.sync_db[collection_name].ensure_index(index, unique=True)

        # Prepare the DBLayer
        db_layer = DBLayerFactory.new_dblayer(self.async_db,
                                              collection_name,
                                              is_capped_collection,
                                              id_field_name,
                                              timestamp_field_name)
        return db_layer


class PeriscopeTestCase(AsyncTestCase, unittest2.TestCase):
    """Base for Periscope's unit testing test cases.

    This base class sets up two database connections (sync, and async).
    """
    def __init__(self, *args, **kwargs):
        """Initializes internal variables."""
        super(PeriscopeTestCase, self).__init__(*args, **kwargs)
        self._async_db = None
        self._sync_db = None

    def get_new_ioloop(self):
        return IOLoop()

    @property
    def asyncmogno_db(self):
        """Returns a reference to asyncmongo DB connection."""
        db_settings = copy(settings.ASYNC_DB)
        db_settings['io_loop'] = self.io_loop
        db_settings['pool_id'] = "pool_%d" \
                                 % int(random.random() * 100000)
        return asyncmongo.Client(**db_settings)

    @property
    def async_db(self):
        if MOTOR_INSTALLED:
            return self.motor_db
        elif ASYNCMONGO_INSTALLED:
            return self.asyncmogno_db
        else:
            raise Exception("Neither motor or asyncmongo are installed")

    @property
    def motor_db(self):
        """Returns a reference to motor DB connection."""
        db_settings = copy(settings.MOTOR_DB)
        db_settings['io_loop'] = self.io_loop
        conn = motor.MotorClient(**db_settings).open_sync()
        return conn[settings.DB_NAME]

    @property
    def sync_db(self):
        """Returns a reference to pymongo DB connection."""
        conn = pymongo.Connection(**settings.SYNC_DB)
        return conn[settings.DB_NAME]


class PeriscopeHTTPTestCase(PeriscopeTestCase, AsyncHTTPTestCase):
    """Base for Periscope's HTTP based unit testing test cases.

    This base class defines tornado.web.Application and sets up
    two database connections (sync, and async).
    """
    def get_app(self):
        class DummyHandler(tornado.web.RequestHandler):
            def get(self):
                self.write("Dummy Handler")
        return TestApp([('/', DummyHandler)])

    def __init__(self, *args, **kwargs):
        """Initializes internal variables."""
        super(PeriscopeHTTPTestCase, self).__init__(*args, **kwargs)
