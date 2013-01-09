#!/usr/bin/env python
"""
Models to abstract dealing with JSON Schemas.

There is two ways to use :class:`periscope.models.JSONSchemaModel`.
The first and the simpliest way is through Schemas Loader. The second and
more powerful method is using metaclasses.

.. code-block:: python

    # Loading schema using schemas loader
    SchemaClass = SCHEMA_LOADER.get_class('http://example.com/schema#',
                                         "SchemaClass")

    # Loading a schema through metaclasses
    # 1- load the scheme from the url
    schema_dict = SCHEMA_LOADER.get('http://example.com/schema#')
    # 2- Define the metaclass for the schema
    meta = schema_meta_factory("SchemaMeta", schema=schema)
    # 3- Define the schema model
    class NetworkResource(JSONSchemaModel):
        # Must inherit directly on indirectly JSONSchemaModel
        __metaclass__ = meta

        def __init__(self, data=None, set_defaults=True, schemas_loader=None)
            # Need to initialize the model
            JSONSchemaModel.__init__(self, data=data,
                                     set_defaults=set_defaults,
                                     schemas_loader=schemas_loader)
            # Then we can do whatever to customize the model

"""

__author__ = 'Ahmed El-Hassany <a.hassany@gmail.com>'
__license__ = 'http://www.apache.org/licenses/LICENSE-2.0'

import json
import re
import validictory
import functools
import httplib2
from periscope.utils import json_schema_merge_extends
from periscope.settings import JSON_SCHEMAS
from periscope.settings import JSON_SCHEMAS_ROOT


SCHEMA = '$schema'
HREF = 'href'


class ObjectDict(dict):
    """Extends the dict object to make it's keys accessible via obj.key.

    :Parameters:

      - `data`: initial data in the dict.
      - `_set_attributes`: True
      - `schemas_loader`: The schema loader class to load the inner data.

    See :class:`periscope.models.SchemasLoader`.
    """

    __special_properties_names__ = [
        "_schema_data",
        "_set_defaults",
        "validate",
        "_value_converter",
        "__doc__",
    ]

    def __init__(self, data=None, _set_attributes=True, schemas_loader=None):
        """
        Initialize new ObjectDict object."""
        assert isinstance(schemas_loader, (SchemasLoader, type(None))), \
            "schemas_loader is not of type Schemas or None."
        setattr(self, "_$schemas_loader", schemas_loader)
        data = data or {}
        super(ObjectDict, self).__init__(data)
        if _set_attributes is True:
            for key, value in data.iteritems():
                if not hasattr(self, key):
                    self._add_property(key)
                self._set_property(key, value)

    def _add_property(self, name, doc=None):
        """Add a property to the class definition.

        :Parameters:

          - `name`: the name of property.
          - `doc`: documenation of the property to be read
          from obj.name.__doc__.
        """
        fget = lambda self: self._get_property(name)
        fset = lambda self, v: self._set_property(name, v)
        fdel = lambda self: self._del_property(name)
        setattr(self.__class__, name, property(fget, fset, fdel, doc=doc))

    def _get_property(self, name):
        """Returns the value of a property."""
        return self.get(name, None)

    def _set_property(self, name, value):
        """Set the value of a property."""
        value = self._value_converter(value, name)
        super(ObjectDict, self).__setitem__(name, value)

    def _del_property(self, name):
        """Delete a propety."""
        if name in self:
            super(ObjectDict, self).__delitem__(name)
        delattr(self.__class__, name)

    def __setattr__(self, name, value):
        special_props = self.__class__.__special_properties_names__
        if name not in special_props and not name.startswith("_$"):
            if not hasattr(self, name):
                self._add_property(name)
            value = self._value_converter(value, name)
        super(ObjectDict, self).__setattr__(name, value)

    def __setitem__(self, name, value):
        self.__setattr__(name, value)

    def __delitem__(self, name):
        self._del_property(name)

    def __iter__(self):
        for key in self.iterkeys():
            yield key

    def iteritems(self):
        for key in self.iterkeys():
            yield key, self[key]

    def itervalues(self):
        for key in self.iterkeys():
            yield self[key]

    def to_mongoiter(self):
        """Escapes mongo's special characters in the keys."""
        for key, value in self.iteritems():
            if isinstance(key, (str, unicode)):
                key = key.replace(".", "$DOT$")
                if key.startswith("$"):
                    key = "\\" + key
            if hasattr(value, "to_mongoiter"):
                value = dict(value.to_mongoiter())
            if isinstance(value, list):
                for index in range(len(value)):
                    if hasattr(value[index], "to_mongoiter"):
                        value[index] = dict(value[index].to_mongoiter())
            yield key, value

    @classmethod
    def from_mongo(cls, data, schemas_loader=None):
        """Loads the object from Mongo doc."""
        assert isinstance(data, dict)
        tmp = {}
        for key, value in data.iteritems():
            if isinstance(key, (str, unicode)):
                key = key.replace("$DOT$", ".")
                if key.startswith("\\$"):
                    key = key.lstrip("\\")
            if hasattr(value, "from_mongo"):
                value = value.from_mongo(schemas_loader=schemas_loader)
            elif isinstance(value, dict):
                if SCHEMA in value and schemas_loader:
                    obj_cls = schemas_loader.get_class(value[SCHEMA])
                else:
                    obj_cls = ObjectDict
                value = obj_cls.from_mongo(value, schemas_loader=None)
            elif isinstance(value, list):
                for index in range(len(value)):
                    if isinstance(value[index], dict):
                        value[index] = cls.from_mongo(value[index])
            tmp[key] = value
        return cls(tmp)

    def _value_converter(self, value, name=None):
        """Make sure thay properties that have dict values are also returend
        as ObjectDict instance."""
        original_type = type(value)
        if type(value) is list:
            for index in range(len(value)):
                if hasattr(value, "_value_converter"):
                    continue
                original_type = type(value[index])
                new_value = self._value_converter(value[index], None)
                if original_type != type(new_value):
                    value[index] = new_value
        elif type(value) is dict and not hasattr(value, "_value_converter"):
            cls = ObjectDict
            loader = getattr(self, "_$schemas_loader", None)
            if not loader:
                cls = ObjectDict
            elif SCHEMA in value:
                cls = loader.get_class(value[SCHEMA])
            elif HREF in value:
                cls = loader.get_class(JSON_SCHEMAS['links'])

            if issubclass(cls, JSONSchemaModel):
                value = cls(value,
                            set_defaults=getattr(self, "_set_defaults", True),
                            schemas_loader=getattr(self, "_$schemas_loader"))
            elif issubclass(cls, ObjectDict):
                value = cls(value,
                            schemas_loader=getattr(self, "_$schemas_loader"))
            else:
                value = cls(value)
            if name and original_type != type(value):
                self._set_property(name, value)
        return value


def schema_meta_factory(name, schema, extends=None):
    """Creates a metaclass to be used in creating new objects that extends
    class:`periscope.models.JSONSchemaModel`.

    :Parameters:
      - `name`: the name of the metaclass.
      - `schema`: a dict of the JSONSchema.
      - `extends (optional)`: a class to be extended
    """
    assert isinstance(schema, dict), "schema is not of type dict."
    parent = extends or type

    class SchemaMetaClass(parent):
        """Creates a metaclass to be used in creating new objects that extends
        `JSONSchemaModel`.
        """
        def __new__(cls, classname, bases, class_dict):
            def make_property(name, doc=None):
                """Make a property to handle attribute from json schema."""
                fget = lambda self: self._get_property(name)
                fset = lambda self, v: self._set_property(name, v)
                fdel = lambda self: self._del_property(name)
                return  property(fget, fset, fdel, doc=doc)

            newtype = super(SchemaMetaClass, cls).__new__(cls, classname,
                                                          bases, class_dict)
            if "description" in schema:
                doc = getattr(newtype, '__doc__', None)
                if doc is None:
                    doc = schema["description"]
                else:
                    doc = "%s\n\n%s\n" % (schema["description"], doc)
                setattr(newtype, '__doc__', doc)
            if 'properties' not in schema:
                schema['properties'] = {}
            if schema.get("type", "object") == "object":
                for prop, value in schema['properties'].items():
                    if prop not in class_dict:
                        doc = value.get("description", None)
                        setattr(newtype, prop, make_property(prop, doc))

            setattr(newtype, '_schema_data', schema)
            return newtype

    return SchemaMetaClass


class JSONSchemaModel(ObjectDict):
    """Creates a class type based on JSON Schema.

    :Parameters:

      - `schema`: dict of the JSON schema to create the class based on.
      - `data`: initial data
      - `set_defaults (optional)`: if a property has default value on the
        schema then set the value of the attribute to it.

    """

    def __init__(self, data=None, set_defaults=True, schemas_loader=None):
        """Init"""
        assert isinstance(data, (dict, type(None))), \
            "data is not of type dict or None."
        assert isinstance(set_defaults, (bool, type(None))), \
            "set_defaults is not of type bool."
        assert isinstance(schemas_loader, (SchemasLoader, type(None))), \
            "schemas_loader is not of type Schemas or None."

        data = data or {}
        dict.__init__(self, data)
        self._set_defaults = set_defaults
        setattr(self, "_$schemas_loader", schemas_loader)

        for key, value in data.iteritems():
            if not hasattr(self, key):
                prop_type = self._get_property_type(key) or {}
                doc = prop_type.get("description", None)
                self._add_property(key, doc)
            self._set_property(key, value)

    def _set_property(self, name, value):
        """Set the value of a property."""
        value = self._value_converter(value, name)
        dict.__setitem__(self, name, value)

    def __setattr__(self, name, value):
        special_props = self.__class__.__special_properties_names__
        if name not in special_props and not name.startswith("_$"):
            if not hasattr(self, name):
                doc = None
                # Try to find if there is any doc in the pattern props
                for pattern, val in self._schema_data.get("patternProperties",
                                                          {}).items():
                    if re.match(pattern, name):
                        doc = val.get("description", None)
                self._add_property(name, doc)
            value = self._value_converter(value, name)
        super(JSONSchemaModel, self).__setattr__(name, value)

    def __setitem__(self, name, value):
        self.__setattr__(name, value)

    def _get_property_type(self, name):
        """Returns the type of the property as defined in the JSON Schema."""
        if name in self._schema_data["properties"]:
            return self._schema_data["properties"][name]
        for pattern, value in self._schema_data.get("patternProperties",
                                                    {}).items():
            if re.match(pattern, name):
                return value
        return None

    def _value_converter(self, value, prop_name=None):
        """Make sure thay properties that have dict values are also returend
        as ObjectDict instance."""
        original_type = type(value)
        if isinstance(value, list):
            for index in range(len(value)):
                original_type = type(value[index])
                new_value = self._value_converter(value[index], None)
                if original_type != type(new_value):
                    value[index] = new_value
        elif isinstance(value, dict) and not isinstance(value, ObjectDict):
            cls = ObjectDict
            loader = getattr(self, "_$schemas_loader", None)
            if not loader:
                cls = ObjectDict
            elif SCHEMA in value:
                cls = loader.get_class(value[SCHEMA])
            elif HREF in value:
                cls = loader.get_class(JSON_SCHEMAS['links'])
            elif prop_name:
                prop_type = (self._get_property_type(prop_name) or
                             {}).get("type", None)
                if isinstance(prop_type, list):
                    # TODO (AH): this is very bad to assume the first type
                    prop_type = prop_type[0]
                if type(prop_type) is dict:
                    prop_type = prop_type.get("$ref", None)
                else:
                    prop_type = None
                if prop_type:
                    cls = loader.get_class(prop_type)
            if issubclass(cls, JSONSchemaModel):
                value = cls(value,
                            set_defaults=self._set_defaults,
                            schemas_loader=getattr(self, "_$schemas_loader"))
            elif issubclass(cls, ObjectDict):
                value = cls(value,
                            chemas_loader=getattr(self, "_$schemas_loader"))
            else:
                value = cls(value)

            if prop_name and original_type != type(value):
                self._set_property(prop_name, value)
        return value

    def validate(self):
        """Validates the value of this instance to match the schema."""
        if self._schema_data.get('additionalProperties', None) is None:
            self._schema_data['additionalProperties'] = False
        validictory.validate(self, self._schema_data,
                             required_by_default=False)

    @staticmethod
    def json_model_factory(name, schema, extends=None):
        """Return a class type of JSONSchemaModel based on schema."""

        if isinstance(extends, (list, tuple)):
            raise ValueError("Support only single inheritance")

        parent = extends or JSONSchemaModel
        parent_meta = getattr(parent, '__metaclass__', None)
        meta = schema_meta_factory("%sMeta" % name, schema,
                                   extends=parent_meta)
        return meta(name, (parent, ), {'__metaclass__': meta})


class SchemasLoader(object):
    """JSON Schema Loader"""
    __cache__ = {}
    __classes_cache__ = {}
    __locations__ = {}

    def __init__(self, locations=None, cache=None, class_cache=None):
        assert isinstance(locations, (dict, type(None))), \
            "locations is not of type dict or None."
        assert isinstance(cache, (dict, type(None))), \
            "cache is not of type dict or None."
        assert isinstance(class_cache, (dict, type(None))), \
            "class_cache is not of type dict or None."
        self.__locations__ = locations or {}
        self.__cache__ = cache or {}
        self.__classes_cache__ = class_cache or {}

    def get(self, uri):
        """Loads schema from `uri` and returns json dict of the schema."""
        if uri in self.__cache__:
            if self.__cache__[uri].get("extends", None) is None:
                return self.__cache__[uri]
        location = self.__locations__.get(uri, uri)
        return self._load_schema(location)

    def get_class(self, schema_uri, class_name=None, extends=None,
                  *args, **kwargs):
        """Return a class type of JSONSchemaModel based on schema."""
        if schema_uri in self.__classes_cache__:
            return self.__classes_cache__[schema_uri]
        schema = self.get(schema_uri)
        class_name = class_name or str(schema.get("name", None))
        if not class_name:
            raise AttributeError(
                "class_name is defined and the schema has not 'name'.")
        cls = JSONSchemaModel.json_model_factory(class_name, schema, extends,
                                                 *args, **kwargs)
        self.set_class(schema_uri, cls)
        return cls

    def set_class(self, schema_uri, cls):
        """Set a class type to returned by get_class."""
        self.__classes_cache__[schema_uri] = cls

    def _load_schema(self, name):
        """The actual load method to be implemented by the
        specific HTTP library."""
        raise NotImplementedError("Schemas._load_schema is not implemented")


class SchemasHTTPLib2(SchemasLoader):
    """Relies on HTTPLib2 HTTP client to load schemas"""
    def __init__(self, http, locations=None, cache=None, class_cache=None):
        super(SchemasHTTPLib2, self).__init__(locations, cache, class_cache)
        self._http = http

    def _load_schema(self, uri):
        resp, content = self._http.request(uri, "GET")
        self.__cache__[uri] = json.loads(content)
        # Work around that 'extends' is not supported in validictory
        json_schema_merge_extends(self.__cache__[uri], self.__cache__)
        return self.__cache__[uri]


class SchemasAsyncHTTP(SchemasLoader):
    """Relies on Tornado's AsyncHTTP client to load schemas"""
    def __init__(self, async_http, locations=None, cache=None,
                 class_cache=None):
        super(SchemasAsyncHTTP, self).__init__(locations, cache, class_cache)
        self._http = async_http

    def _save_schema(self, response, uri, callback):
        """Save the schema in `self.__cache__`."""
        self.__cache__[uri] = json.loads(response.body)
        # Work around that 'extends' is not supported in validictory
        json_schema_merge_extends(self.__cache__[uri], self.__cache__)
        callback(self.__cache__[uri])

    def get(self, uri, callback):
        if not callback:
            raise ValueError("callback is not defined.")
        if uri in self.__cache__:
            callback(self.__cache__[uri])
        else:
            location = self.__locations__.get(uri, uri)
            self._load_schema(location, callback)

    def _load_schema(self, uri, callback):
        load_cb = functools.partial(callback, uri=uri)
        self._http.fetch(uri, callback=load_cb)


# Define the default JSON Schemas that are defiend in the JSON schema RFC
JSON_SCHEMA = json.loads(open(JSON_SCHEMAS_ROOT + "/schema").read())
HYPER_SCHEMA = json.loads(open(JSON_SCHEMAS_ROOT + "/hyper-schema").read())
JSON_REF_SCHEMA = json.loads(open(JSON_SCHEMAS_ROOT + "/json-ref").read())
HYPER_LINKS_SCHEMA = json.loads(open(JSON_SCHEMAS_ROOT + "/links").read())

CACHE = {
    JSON_SCHEMAS['schema']: JSON_SCHEMA,
    JSON_SCHEMAS['hyper']: HYPER_SCHEMA,
    JSON_SCHEMAS['links']: HYPER_LINKS_SCHEMA,
    JSON_SCHEMAS['ref']: JSON_REF_SCHEMA,
}

HTTP_CLIENT = httplib2.Http(".cache")
SCHEMA_LOADER = SchemasHTTPLib2(HTTP_CLIENT, cache=CACHE)

JSONSchema = SCHEMA_LOADER.get_class(JSON_SCHEMAS['schema'], "JSONSchema")
HyperSchema = SCHEMA_LOADER.get_class(JSON_SCHEMAS['hyper'], "HyperSchema")
HyperLink = SCHEMA_LOADER.get_class(JSON_SCHEMAS['links'], "HyperLink")
JSONRef = SCHEMA_LOADER.get_class(JSON_SCHEMAS['ref'], "JSONRef")
