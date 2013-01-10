#!/usr/bin/env python
"""
Databases related tests
"""
import copy
import functools
from mock import Mock
from periscope.db import DBLayerFactory
from periscope.test.base import PeriscopeTestCase


class DBLayerIntegrationTest(PeriscopeTestCase):
    """This test suit test againest mongodb directly."""
    def __init__(self, *args, **kwargs):
        super(DBLayerIntegrationTest, self).__init__(*args, **kwargs)
        self.collection_name = "test_collection"

    def setUp(self):
        super(DBLayerIntegrationTest, self).setUp()
        # make sure we start by clean collection for each test case
        self.sync_db.drop_collection(self.collection_name)
        self.sync_db.create_collection(self.collection_name)

    def tearDown(self):
        super(DBLayerIntegrationTest, self).tearDown()
        # make sure we start by clean collection for each test case
        self.sync_db.drop_collection(self.collection_name)

    def test_insert(self):
        """
        Test inserting a document into the database.
        """
        # Arrange
        def handle_insert(response, error=None):
            """The callback function"""
            self.assertIsNone(error)
            self.assertEqual(response, '1')
            self.stop()

        model = DBLayerFactory().new_dblayer(self.async_db,
                                             self.collection_name)
        full_collection_name = model.collection.full_collection_name
        collection = self.async_db[self.collection_name].full_collection_name

        # Act
        model.insert({"_id": "1", "id": "1", "two": 2}, callback=handle_insert)

        # Assert
        self.assertEqual(full_collection_name, collection)
        self.wait()

    def test_find(self):
        """
        Test finding a document in the database
        """
        def handle_find(response, error=None, expected=None):
            """The callback function"""
            self.assertIsNone(error)
            self.assertEqual(response, expected)
            self.stop()

        # Arrange
        # Insert some test data directly to the collection
        self.sync_db[self.collection_name].insert({"_id": "1", "num": 1})
        self.sync_db[self.collection_name].insert({"_id": "2", "num": 2})
        self.sync_db[self.collection_name].insert({"_id": "3", "num": 3})
        expected = [{u"num": 2}, {u"num": 3}]
        model = DBLayerFactory().new_dblayer(self.async_db,
                                             self.collection_name)

        # Act
        cursor = model.find({"num": {"$gte": 2}}, batch_size=100)

        # Assert
        callback = functools.partial(handle_find, expected=expected)
        cursor.to_list(length=200, callback=callback)
        self.wait()

    def test_find_each(self):
        """
        Test finding a document in the database, using Cursor.each this time
        """
        expected = [{u"num": 3}, {u"num": 2}]

        def handle_each(response, error=None):
            """The callback function"""
            if response is None and error is None:
                self.stop()
                return
            self.assertIsNone(error)
            self.assertTrue(response in expected)
            expected.remove(response)
            return True

        # Arrange
        # Insert some test data directly to the collection
        self.sync_db[self.collection_name].insert({"_id": "1", "num": 1})
        self.sync_db[self.collection_name].insert({"_id": "2", "num": 2})
        self.sync_db[self.collection_name].insert({"_id": "3", "num": 3})
        model = DBLayerFactory().new_dblayer(self.async_db,
                                             self.collection_name)

        # Act
        cursor = model.find({"num": {"$gte": 2}}, batch_size=3)

        # Assert
        callback = functools.partial(handle_each)
        cursor.each(callback=callback)
        self.wait()
        self.assertEqual(len(expected), 0)

    def test_tail(self):
        """
        Test tailable cursors a document
        """
        # Buffer for the tail results
        results = []

        def each(response, error=None):
            """The callback function"""
            if response is None and error is None:
                self.stop()
                return
            results.append(response)
            if len(results) == 3:
                self.stop()
                return None

        def dummy_callback(response, error=None):
            pass

        # Arrange
        self.sync_db[self.collection_name].drop()
        self.sync_db.create_collection(self.collection_name,
                                       capped=True, size=1000)
        self.sync_db[self.collection_name].insert({"_id": "1", "num": 1})
        model = DBLayerFactory().new_dblayer(self.async_db,
                                             self.collection_name,
                                             io_loop=self.io_loop)
        expected = [{u'num': 2, u'id': u'2', u'ts': u'2'},
                    {u'num': 3, u'id': u'3', u'ts': u'3'},
                    {u'num': 4, u'id': u'4', u'ts': u'4'}]

        # Act
        cursor = model.find({"num": {"$gte": 2}})
        cursor.tail(each)
        # Insert some test data
        for i in range(1, 5):
            model.insert({'_id': str(i), 'id': str(i), 'ts': str(i), 'num': i},
                         callback=dummy_callback)

        # Assert
        self.wait()
        for i in range(len(results)):
            self.assertTrue(results[0] in expected)
            results.remove(results[0])
        self.assertEqual(results, [])

    def test_update(self):
        """
        Test updating existing field in the database.
        """
        def handle_update(response, error=None):
            """The callback function"""
            self.assertIsNone(error)
            self.assertEqual(response['ok'], 1.0)
            self.stop()

        self.sync_db[self.collection_name].insert({"num": 1})
        model = DBLayerFactory().new_dblayer(self.async_db,
                                             self.collection_name)
        model.update({"num": 1}, {"num": 2}, callback=handle_update)
        self.wait()

    def test_remove(self):
        """
        Test deleting a document from the database
        """
        def handle_remove(response, error=None):
            """The callback function"""
            self.assertIsNone(error)
            self.assertEqual(response['ok'], 1.0)
            self.stop()

        self.sync_db[self.collection_name].insert({"num": 1})
        model = DBLayerFactory().new_dblayer(self.async_db,
                                             self.collection_name)
        model.remove({"num": 1}, callback=handle_remove)
        self.wait()

    def test_aggregate(self):
        """
        Test aggrefate function
        """
        expected =  {u'ok': 1.0, u'result': [{u'count': 3, u'_id': None}]}

        def handle(response, error=None):
            """The callback function"""
            self.assertIsNone(error)
            self.assertEqual(response, expected)
            self.stop()

        # Arrange
        # Insert some test data directly to the collection
        self.sync_db[self.collection_name].insert({"_id": "1", "num": 1})
        self.sync_db[self.collection_name].insert({"_id": "2", "num": 2})
        self.sync_db[self.collection_name].insert({"_id": "3", "num": 3})
        model = DBLayerFactory().new_dblayer(self.async_db,
                                             self.collection_name)

        # Act
        result = model.aggregate([{'$group': { '_id': None,
                                   'count': { '$sum': 1 }}}], callback=handle)

        # Assert
        self.wait()


class DBLayerTest(PeriscopeTestCase):
    """This test suit mocks mongodb driver."""
    def test_insert(self):
        """
        Test inserting a document into the database.
        """
        # Arrange
        response = [{u'connectionId': 1, u'ok': 1.0, u'err': None, u'n': 0}]
        collection_name = "collection_insert"
        collection = Mock(name=collection_name)
        collection.insert.return_value = None
        call = lambda *args, **kwargs: kwargs['callback'](response, error=None)
        collection.insert.side_effect = call
        client = {collection_name: collection}
        callback = Mock(name="insert_callback")
        callback.side_effect = lambda response, error: self.stop()
        timestamp = 1330921125000000
        data = {"id": "1", "ts": timestamp, "two": 2}
        expected = copy.copy(data)

        # Act
        model = DBLayerFactory().new_dblayer(client, collection_name)
        model.insert(data, callback=callback)
        self.wait()

        # Assert
        self.assertEqual(collection.insert.call_count, 1)
        inserted = collection.insert.call_args[0][0]
        obj_id = inserted.pop('_id', None)
        self.assertIsNotNone(obj_id)
        self.assertEqual(inserted, expected)
        callback.assert_called_once_with(obj_id, error=None)

    def test_remove(self):
        """
        Test deleting a document from the database
        """
        response = [{u'connectionId': 1, u'ok': 1.0, u'err': None, u'n': 0}]
        query = {"id": "1", "two": 2}
        collection_name = "collection_remove"
        collection = Mock(name=collection_name)
        collection.remove.return_value = None
        call = lambda *args, **kwargs: kwargs['callback'](response, error=None)
        collection.remove.side_effect = call
        client = {collection_name: collection}
        callback = Mock(name="remove_callback")
        callback.side_effect = lambda response, error: self.stop()
        # Act
        model = DBLayerFactory().new_dblayer(client, collection_name)
        model.remove(query, callback=callback)
        self.wait()
        # Assert
        collection.remove.assert_called_once_with(query, callback=callback)
        callback.assert_called_once_with(response, error=None)

    def test_find(self):
        """
        Test finding a document in the database
        """
        # Arrange
        response = [{"_id": "2", "num": 2}, {"_id": "3", "num": 3}]
        expected = [{"_id": "2", "num": 2}, {"_id": "3", "num": 3}]
        query = {"num": {"$gte": 2}, }
        # This is mock for the mongodb driver
        collection_name = "collection_find"
        collection = Mock(name=collection_name)
        collection.find.return_value = "AA"
        client = Mock(name='async_dbmock', spec_set=self.async_db)
        #client.__getitem__.value = 'aa'
        #client
        # Mock for the callback by the driver
        callback = Mock(name="find_callback")
        callback.side_effect = lambda response, error: self.stop()

        # Act
        model = DBLayerFactory().new_dblayer(client, collection_name)
        cursor = model.find(query)

        # Assert
        self.assertEqual(collection.find.call_args[0], (query,))
        self.assertIsNotNone(cursor)

    def test_update(self):
        """
        Test updating existing field in the database.
        """
        # Arrange
        response = [
            {
                u'updatedExisting': True,
                u'connectionId': 1,
                u'ok': 1.0,
                u'err': None,
                u'n': 1
            }
        ]
        query = {"id": 1}
        data = {"num": 2}
        collection_name = "collection_update"
        # This is mock for the mongodb driver
        collection = Mock(name=collection_name)
        collection.update.return_value = None
        call = lambda *args, **kwargs: kwargs['callback'](response, error=None)
        collection.update.side_effect = call
        client = {collection_name: collection}
        # Mock for the callback by the driver
        callback = Mock(name="update_callback")
        callback.side_effect = lambda response, error: self.stop()

        # Act
        model = DBLayerFactory().new_dblayer(client, collection_name)
        model.update(query, data, callback=callback)
        self.wait()

        # Assert
        collection.update.assert_called_once_with({'id': 1}, data,
                                                  callback=callback)
        callback.assert_called_once_with(response, error=None)
