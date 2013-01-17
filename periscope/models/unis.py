#!/usr/bin/env python
"""
UNIS specific model classes.
"""

__author__ = 'Ahmed El-Hassany <a.hassany@gmail.com>'
__license__ = 'http://www.apache.org/licenses/LICENSE-2.0'

import time
from periscope.db import object_id
from periscope.models import JSONSchemaModel
from periscope.models import SCHEMA_LOADER
from periscope.models import schema_meta_factory
from periscope.settings import SCHEMAS

import json
from tornado import gen
from periscope.db import dumps_mongo
from periscope.db import DBOp
from periscope.models import ObjectDict


NETWORK_RESOURCE_SCHEMA = SCHEMA_LOADER.get(SCHEMAS["networkresource"])
NETWORK_RESOURCE_META = schema_meta_factory("NetworkResourceMeta",
                                            schema=NETWORK_RESOURCE_SCHEMA)


class NotValidSchema(Exception):
    """Raised If data is set to a $schema other than the schema for
    the model class"""
    pass


class NetworkResource(JSONSchemaModel):
    """Netowrk resource is the base of all objects in UNIS.

    :Parameters:

      - `data`: the initial data dict to load the `NetworkResource`
      - `set_defaults`: If true use the default values from the UNIS schema
        to set the values of the properties that were not definied in `data`.
      - `schema_loads`: the object used to load schema of the inner objects.
      - `auto_id`: If true, `id` will be generated if not provided in `data`.
      - `auto_ts`: If true, `ts` the current time will be used
        if not provided in `data`.

    """

    __metaclass__ = NETWORK_RESOURCE_META

    def __init__(self, data=None, set_defaults=True, schemas_loader=None,
                 auto_id=True, auto_ts=True):
        JSONSchemaModel.__init__(self, data=data, set_defaults=set_defaults,
                                 schemas_loader=schemas_loader)
        if auto_id is True:
            self.id = self.id or str(object_id())
        if auto_ts is True:
            self.ts = self.ts or int(time.time() * 1000000)

    @classmethod
    def create_resources(cls, data, base_url, set_defaults=True,
                         schemas_loader=None, auto_id=True, auto_ts=True):
        """
        Creates network resource(s) from the input json dict.

        :Parameters:
          - `data`: the input data dict or list of dicts.

        See :class:`periscope.models.unis.NetworkResource` for the rest
        of arguments.

        """
        # It's easier to deal with lists
        is_list = isinstance(data, list)
        if is_list is True:
            in_data = data
        else:
            in_data = [data]
        out_data = []
        schema = cls._schema_data['id']

        for item in in_data:
            item["$schema"] = item.get("$schema", schema)
            if item["$schema"] != schema:
                raise NotValidSchema("Found '%s' while expecting '%s'" %
                                     (item["$schema"], schema))
            obj = cls(item, set_defaults=set_defaults,
                      schemas_loader=schemas_loader, auto_id=auto_id,
                      auto_ts=auto_ts)
            obj['selfRef'] = '%s/%s' % (base_url.rstrip('/'), obj['id'])
            obj.validate()
            out_data.append(obj)
        if is_list:
            return out_data
        else:
            return out_data[0]

    @staticmethod
    def _rollback(dblayer, resources, callback):
        """
        Try to delete resources from the database.
        Expecting a list of ObjectIDs.
        """
        items_list = [
            {'id': item['id'], 'ts': item['ts']} for item in resources]
        remove_query = {'$or': items_list}
        dblayer.remove(remove_query, callback=callback)

    @classmethod
    @gen.engine
    def insert_resource(cls, dblayer, body, base_url, callback):
        """Inserts A network resource to the database.

        :Parameters:

          - `dblayer`: The database access layer,
            See :cls:`periscope.db.AbstractDBLayer`.
          - `base_url`: the base the path to access this resource, e.g., /nodes
          - `body`: The body of the user HTTP request (dict)
          - `callback`: Callback method with results and error

        """
        try:
            if isinstance(body, basestring):
                body = json.loads(body)
            if not isinstance(body, dict) and not isinstance(body, list):
                raise ValueError("Body is not a dictionary nor a list")
        except ValueError as exp:
            message = "malformatted json request '%s'." % exp
            callback(None,
                error=dict(status_code=400, code=400001, message=message))
            return

        try:
            resources = cls.create_resources(body, base_url)
            # Make sure it's a list
            if not isinstance(resources, list):
                resources = [resources]
        except NotValidSchema as exp:
            message = "Not valid '$schema' field: %s" % str(exp)
            callback(None,
                error=dict(status_code=400, code=400002, message=message))
            return
        except Exception as exp:
            message = "Clound't deserialize resources from the request: '%s'" \
                % str(exp)
            callback(None,
                error=dict(status_code=400, code=400003, message=message))
            return

        # Inserting resources to mongodb
        insert_result, insert_error = yield DBOp(
            dblayer.insert, [dict(item.to_mongoiter()) for item in resources])

        if insert_error is None:
            print "RETURN", insert_result
            callback(insert_result, error=None)
        else:
            # First try removing inserted items.
            _, remove_error = yield DBOp(NetworkResource._rollback,
                dblayer, resources)
            insert_error = str(insert_error)

            # Prepare the right error code
            if 'duplicate key' in insert_error:
                status_code = 409
                message = "Conflict: %s." % \
                    str(insert_error).replace("\"", "\\\"")
            else:
                status_code = 500
                message = "Could't process the POST request: %s." % \
                    str(insert_error).replace("\"", "\\\"")

            # Check if the inserted items where removed correctly
            if remove_error is None:
                if status_code == 409:
                    code = 409001
                else:
                    code = 500001
                message += " Transaction IS rolled back successfully."
            else:
                if status_code == 409:
                    code = 409002
                else:
                    code = 500002
                message += " Transaction couldn't be rolled back: %s" \
                    % str(remove_error)
            callback(None, error=dict(status_code=status_code,
                code=code, message=message))


Node = SCHEMA_LOADER.get_class(SCHEMAS["node"], extends=NetworkResource)
Link = SCHEMA_LOADER.get_class(SCHEMAS["link"], extends=NetworkResource)
Port = SCHEMA_LOADER.get_class(SCHEMAS["port"], extends=NetworkResource)
Path = SCHEMA_LOADER.get_class(SCHEMAS["path"], extends=NetworkResource)
Service = SCHEMA_LOADER.get_class(SCHEMAS["service"], extends=NetworkResource)
Network = SCHEMA_LOADER.get_class(SCHEMAS["network"], extends=Node)
Domain = SCHEMA_LOADER.get_class(SCHEMAS["domain"], extends=NetworkResource)
Topology = SCHEMA_LOADER.get_class(
    SCHEMAS["topology"], extends=NetworkResource)


def register_urn(handler, urn, schema, url):
    print "XXX regiserting", urn, schema, url


@gen.engine
def write_psjson(handler, query, callback, success_status=200,
        is_list=True, full_representation=True,
        show_location=True, include_deleted=False):
    """
    Writes application/perfsonar+json response to the client.
    """
    def write_header(status=success_status):
        handler.set_status(status)
        accept = handler.accept_content_type
        handler.set_header("Content-Type", accept +
                           " ;profile=" + handler.schemas_single[accept])

    cursor = handler.dblayer.find(query)
    first_list = False
    if is_list is True:
        handler.write("[\n")
        first_list = True
    found_one = False
    while (yield cursor.fetch_next):
        found_one = True
        res = cursor.next_object()
        unescaped = ObjectDict.from_mongo(res)
        if unescaped.get('status', None) == 'DELETED' and not include_deleted:
            if is_list is True:
                continue
            else:
                write_header(410)
                break

        if is_list is False and show_location is True:
            location = unescaped.get('selfRef', None)
            write_header(success_status)
            if location is not None:
                handler.set_header("Location", location)

        if first_list is True:
            first_list = False
            write_header(success_status)
        elif is_list is True:
            handler.write(",\n")
        if full_representation is True:
            handler.write(dumps_mongo(unescaped, indent=2))
        else:
            handler.write({
                'href': unescaped['selfRef'],
                handler.timestamp: unescaped[handler.timestamp]})
        if is_list is False:
            break

    if found_one is False:
        if is_list is False:
            write_header(404)
        else:
            write_header(success_status)

    if is_list is True:
        handler.write("\n]\n")

    handler.write("\n")
    callback(None, error=None)
