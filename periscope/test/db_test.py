#!/usr/bin/env python
"""
Databases related tests
"""
import functools
from periscope.db import DBLayerFactory
from periscope.test.base import PeriscopeTestCase
from mock import Mock
import copy


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
        def handle_insert(response, error=None):
            """The callback function"""
            self.assertIsNone(error)
            self.assertEqual(response, '1')
            self.stop()

        model = DBLayerFactory().new_dblayer(self.async_db,
                                             self.collection_name)
        full_collection_name = model.collection.full_collection_name
        collection = self.async_db[self.collection_name].full_collection_name
        self.assertEqual(full_collection_name, collection)
        model.insert({"_id": "1", "id": "1", "two": 2}, callback=handle_insert)
        self.wait()

    def test_find(self):
        """
        Test finding a document in the database
        """
        def handle_find(expected, response, error=None):
            """The callback function"""
            self.assertIsNone(error)
            self.assertEqual(response, expected)
            self.stop()

        # Insert some test data directly to the collection
        self.sync_db[self.collection_name].insert({"_id": "1", "num": 1})
        self.sync_db[self.collection_name].insert({"_id": "2", "num": 2})
        self.sync_db[self.collection_name].insert({"_id": "3", "num": 3})
        expected = [{u"num": 2}, {u"num": 3}]
        find_callback = functools.partial(handle_find, expected)

        model = DBLayerFactory().new_dblayer(self.async_db,
                                             self.collection_name)
        model.find({"num": {"$gte": 2}}, callback=find_callback)
        self.wait()

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
        cursor = Mock(name="cursor" + collection_name)
        collection = Mock(name=collection_name)
        collection.find.return_value = cursor
        call = lambda *args, **kwargs: kwargs['callback'](response, error=None)
        cursor.to_list.side_effect = call
        client = {collection_name: collection}
        # Mock for the callback by the driver
        callback = Mock(name="find_callback")
        callback.side_effect = lambda response, error: self.stop()

        # Act
        model = DBLayerFactory().new_dblayer(client, collection_name)
        model.find(query, callback=callback)
        self.wait()

        # Assert
        self.assertEqual(collection.find.call_args[0], (query,))
        callback.assert_called_once_with(expected, error=None)

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
