#!/usr/bin/env python
"""
Measurement store specific model classes.
"""

__author__ = 'Omar Arap'
__license__ = 'http://www.apache.org/licenses/LICENSE-2.0'

import time
from periscope.db import object_id
from periscope.models import JSONSchemaModel
from periscope.models import schemaLoader
from periscope.models import schemaMetaFactory
from periscope.models import SCHEMAS


METADATA_SCHEMA = schemaLoader.get(SCHEMAS["metadata"])
METADATA_META = schemaMetaFactory("MetadataMeta",
                                  schema=METADATA_SCHEMA)

class Metadata(JSONSchemaModel):
    __metaclass__ = METADATA_META
    def __init__(self, data=None, set_defaults=True, schemas_loader=None,
                 auto_id=True, auto_ts=True):
        JSONSchemaModel.__init__(self, data=data, set_defaults=set_defaults,
                                 schemas_loader=schemas_loader)
        if auto_id is True:
            self.id = self.id or str(object_id())
        if auto_ts is True:
            self.ts = self.ts or int(time.time() * 1000000)
