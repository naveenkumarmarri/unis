import os
from subprocess import call

measurement = '{ "id": "2", "configuration": { "default_collection_size": 10000 }, "eventTypes": ["test1", "test2"] }'

node = '{ "id": "3" }'

service = '{ "id": "4", "serviceType": "Test Service" }'


print "\033[34mPublishing id \033[36m2\033[34m to measurements\033[0m"
call(["curl", "-H", "Content-Type: application/perfsonar+json", "--data", measurement, "http://localhost:8888/measurements"])

print "\033[31mPublishing \033[36m3\033[31m to nodes\033[0m"
call(["curl", "-H", "Content-Type: application/perfsonar+json", "--data", node, "http://localhost:8888/nodes"])

print "\033[35mPublishing id \033[36m4\033[35m to services\033[0m"
call(["curl", "-H", "Content-Type: application/perfsonar+json", "--data", service, "http://localhost:8888/services"])
