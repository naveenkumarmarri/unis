#!/usr/bin/env python
"""
UNIS specific model classes.
"""

__author__ = 'Ahmed El-Hassany <a.hassany@gmail.com>'
__license__ = 'http://www.apache.org/licenses/LICENSE-2.0'

import time
from periscope.db import object_id
from periscope.models import JSONSchemaModel
from periscope.models import schemaLoader
from periscope.models import schemaMetaFactory
from periscope.settings import SCHEMAS


NETWORK_RESOURCE_SCHEMA = schemaLoader.get(SCHEMAS["networkresource"])
NETWORK_RESOURCE_META = schemaMetaFactory("NetworkResourceMeta",
                                          schema=NETWORK_RESOURCE_SCHEMA)


class NetworkResource(JSONSchemaModel):

    __metaclass__ = NETWORK_RESOURCE_META

    def __init__(self, data=None, set_defaults=True, schemas_loader=None,
                 auto_id=True, auto_ts=True):
        JSONSchemaModel.__init__(self, data=data, set_defaults=set_defaults,
                                 schemas_loader=schemas_loader)
        if auto_id is True:
            self.id = self.id or str(object_id())
        if auto_ts is True:
            self.ts = self.ts or int(time.time() * 1000000)


Node = schemaLoader.get_class(SCHEMAS["node"], extends=NetworkResource)
Link = schemaLoader.get_class(SCHEMAS["link"], extends=NetworkResource)
Port = schemaLoader.get_class(SCHEMAS["port"], extends=NetworkResource)
Path = schemaLoader.get_class(SCHEMAS["path"], extends=NetworkResource)
Service = schemaLoader.get_class(SCHEMAS["service"], extends=NetworkResource)
Network = schemaLoader.get_class(SCHEMAS["network"], extends=Node)
Domain = schemaLoader.get_class(SCHEMAS["domain"], extends=NetworkResource)
Topology = schemaLoader.get_class(SCHEMAS["topology"], extends=NetworkResource)
Event = schemaLoader.get_class(SCHEMAS["datum"], extends=NetworkResource)
Data = schemaLoader.get_class(SCHEMAS["data"], extends=NetworkResource)
