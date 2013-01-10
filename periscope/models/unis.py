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


Node = SCHEMA_LOADER.get_class(SCHEMAS["node"], extends=NetworkResource)
Link = SCHEMA_LOADER.get_class(SCHEMAS["link"], extends=NetworkResource)
Port = SCHEMA_LOADER.get_class(SCHEMAS["port"], extends=NetworkResource)
Path = SCHEMA_LOADER.get_class(SCHEMAS["path"], extends=NetworkResource)
Service = SCHEMA_LOADER.get_class(SCHEMAS["service"], extends=NetworkResource)
Network = SCHEMA_LOADER.get_class(SCHEMAS["network"], extends=Node)
Domain = SCHEMA_LOADER.get_class(SCHEMAS["domain"], extends=NetworkResource)
Topology = SCHEMA_LOADER.get_class(SCHEMAS["topology"], extends=NetworkResource)
