.. _error_codes:

Error Codes
============



HTTP Status Codes
------------------

HTTP 200
`````````````

HTTP 400: Bad Request
```````````````````````

POST
''''''''''''''

code=400004, message="NetworkResource ID should not be defined." The client sent POST to /res/id

POST PS_JSON
''''''''''''''

code=400001, message="malformatted json request '%s

code=400002, message="Not valid '$schema' field" % str(exp)

code=400003, message="Clound't deserialize resources from the request: '%s'" % str(exp)

PUT PS_JSON
''''''''''''''

code=400005, message="malformatted json request '%s

code=400006, message="Not valid '$schema' field" % str(exp)

code=400007, message="Clound't deserialize resource from the request: '%s'" % str(exp)

code=400008, message = "Different IDs in the URL '%s' and in the body '%s'" % (body[self.Id], res_id)


HTTP 404: Not Found
`````````````````````

DELETE

code=404002, message = "Couldn't find resource with %s='%s'" % (self.Id, res_id)


HTTP 405: Method Not allowed
```````````````````````````````

POST
''''''''''''''

code=405001, message = "Cannot POST to specific ID. Try posting without an ID at the end of the URL."

PUT
''''''''''''''

code=405002, message = "PUT is allowed only for specific resources. Try PUT to specific resource (with /id at the end of the URL)."

DELETE
''''''''''''''

code=405003, message="DELETE is allowed only for specific resources. Try DELETE to specific resource (with /id at the end of the URL)."


HTTP 409: Conflict
````````````````````````

POST PS_JSON
''''''''''''''

code=409001, message="Conflict: %s." % error + " Transaction IS rolled back successfully."

code=409002, message="Conflict: %s." % error + "  Transaction couldn't be rolled back: %s"


PUT_PSJSON
''''''''''''''

code=409003, message="Conflict: %s." % error + " Transaction IS rolled back successfully."

code=409004, message="Conflict: %s." % error + "  Transaction couldn't be rolled back: %s"



HTTP 406: Not Acceptable
``````````````````````````

The client asked the response to be in a format that UNIS doesn't understand.

POST
''''''''''''''

code=406001, message="Unsupported accept content type '%s'" % (accept_content_type)

PUT
''''''''''''''

code=406002, message="Unsupported accept content type '%s'" % (accept_content_type)

DELETE
''''''''''''''

code=406003, message="Unsupported accept content type '%s'" % (accept_content_type)


HTTP 410: Gone

````````````````````````

DELETE
''''''''''''''

code=410001, message="Resource already has been deleted at timestamp='%s'." % str(deleted[self.timestamp])



HTTP 415: Unsupported Media Type
```````````````````````````````````

This will be a resulted if Content-Type of the body is not understood by UNIS.

POST
''''''''''''''

code=415001, message="No POST method is implemented fot content type '%s'" % \content_type

PUT
''''''''''''''

code=415001, message="No PUT method is implemented fot content type '%s'" % \content_type

# TODO (AH) check if this need to defined for DELETE


HTTP 500: Internal Server Error
``````````````````````````````````

POST PS_JSON
''''''''''''''

code=500001, message = "Could't process the POST request: %s." %  " Transaction IS rolled back successfully."

code=500002, message = "Could't process the POST request: %s." %  + "  Transaction couldn't be rolled back: %s"

PUT PS_JSON
''''''''''''''

code=500003, message = "Could't process the POST request: %s." %  " Transaction IS rolled back successfully."

code=500004, message = "Could't process the POST request: %s." %  + "  Transaction couldn't be rolled back: %s"

DELETE
''''''''''''''

code=500005, message = "Couldn't load the resource from the database: '%s'." % str(error)

code=500006, message = "Couldn't delete resource: '%s'." % str(error)

