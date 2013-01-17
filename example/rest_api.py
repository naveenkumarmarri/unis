#!/usr/bin/env python

"""
Small Examples about using the REST API
"""

import json
import time
import urllib
from httplib import HTTPConnection

HOST = "dev.incntre.iu.edu"
PORT =  80
URL = "http://%s:%s" % (HOST, PORT)

MIME = {
    'HTML': 'text/html',
    'JSON': 'application/json',
    'PLAIN': 'text/plain',
    'SSE': 'text/event-stream',
    'PSJSON': 'application/perfsonar+json',
    'PSXML': 'application/perfsonar+xml',
}

SCHEMAS = {
    'networkresource': 'http://unis.incntre.iu.edu/schema/20120709//networkresource#',
    'node': 'http://unis.incntre.iu.edu/schema/20120709/node#',
    'port': 'http://unis.incntre.iu.edu/schema/20120709/port#',
    'link': 'http://unis.incntre.iu.edu/schema/20120709/link#',
    'network': 'http://unis.incntre.iu.edu/schema/20120709/network#',
    'blipp': 'http://unis.incntre.iu.edu/schema/20120709/blipp#',
    'metadata': 'http://unis.incntre.iu.edu/schema/20120709/metadata#',
}


# Sample Node
node = {
    "$schema": SCHEMAS['node'],
    "id": "pc166",
    "name": "pc166.emulab.net",
    "ports": [
        {
            "href": URL + "/ports/pc166_iface0",
            "rel": "full"
        },
        {
            "href": URL + "/ports/pc166_10",
            "rel": "full"
        }
    ],
    "properties": {
        "pgeni": {
            "component_manager_urn": "urn:publicid:IDN+emulab.net+authority+cm",
            "component_manager_uuid": "28a10955-aa00-11dd-ad1f-001143e453fe",
            "component_urn": "urn:publicid:IDN+emulab.net+node+pc166",
            "component_uuid": "de99509e-773e-102b-8eb4-001143e453fe",
            "exclusive": True,
            "sliver_urn": "urn:publicid:IDN+emulab.net+sliver+72500",
            "sliver_uuid": "395c22c4-4d1a-11e1-a511-001143e453fe",
            "virtualization_subtype": "raw",
            "virtualization_type": "raw",
            "node_type": "pc",
            "disk_image": "urn:publicid:IDN+emulab.net+image+GeniSlices//UBUNTU91-LAMP"
        }
    }
}

# Sample Ethernet PORT
port = {
    "$schema": SCHEMAS['port'],
    "id": "pc166_iface0",
    "name": "eth27",
    "address": {
        "type": "mac",
        "address":"0002b365b8c9"
    },
    "properties": {
        "pgeni": {
            "component_id": "eth3",
            "component_urn": "urn:publicid:IDN+emulab.net+interface+pc166:eth3",
            "sliver_urn": "urn:publicid:IDN+emulab.net+sliver+72504",
            "sliver_uuid": "3c9b1bbb-4d1a-11e1-a511-001143e453fe"
        }
    }
}

# Sample IP PORT
port2 = {
    "$schema": SCHEMAS['port'],
    "id": "pc166_10",
    "name": "IP port",
    "address": {
        "type": "mac",
        "address":"10.10.10.10"
    },
    "relations": {
        "over": [
            {
                "href": URL + "/ports/pc166_iface0",
                "rel": "full"
            }
        ]
    }
}

meta1 = {
    "id": "meta1",
    "subject": {
        "href": URL + "/ports/pc166_iface0",
        "rel": "full"
    },
    "eventType": "ps.port.util"
}

meta2 = {
    "id": "meta1",
    "subject": {
        "href": URL + "/ports/pc166_iface0",
        "rel": "full"
    },
    "eventType": "ps.port.discard"
}

meta3 = {
    "id": "meta3",
    "subject": {
        "href": URL + "/ports/pc166_iface0",
        "rel": "full"
    },
    "eventType": "ps.port.error"
}

meta4 = {
    "id": "meta4",
    "subject": {
        "href": URL + "/ports/pc166_iface0",
        "rel": "full"
    },
    "eventType": "ps.port.util.avg"
}



# POST and let the server handle the IDs
# Note node has ID in the body, so Periscope is going to use it
# Howeever if there is no ID the server will generate one
print "POSTING new node to UNIS"
conn = HTTPConnection(HOST, PORT)
headers = {
        "Accept": MIME["PSJSON"],
        "Content-Type": MIME["PSJSON"] + "; profile="+ SCHEMAS["node"]
    }
conn.request("POST", "/nodes", json.dumps(node), headers)
res = conn.getresponse()
node_posted = json.loads(res.read())
# This should be 201
print "Node posted and returen status is (it should be 201): ", res.status


# Conflict
print "POSTING the node again, to make a conflict!"
conn = HTTPConnection(HOST, PORT)
headers = {
        "Accept": MIME["PSJSON"],
        "Content-Type": MIME["PSJSON"] + "; profile="+ SCHEMAS["node"]
    }

conn.request("POST", "/nodes", json.dumps(node_posted), headers)
res = conn.getresponse()
# This should be 409
print "Node posted and returen status is (it should be 409): ", res.status



# PUT
print "HTTP put for specific port"
conn = HTTPConnection(HOST, PORT)
headers = {
        "Accept": MIME["PSJSON"],
        "Content-Type": MIME["PSJSON"] + "; profile="+ SCHEMAS["port"]
    }
conn.request("PUT", "/ports/pc166_iface0" , json.dumps(port), headers)
res = conn.getresponse()
# This should be 201
print "PORT inserted and returen status is (it should be 201): ", res.status


# PUT
print "HTTP put for specific port (again for the IP Port)"
conn = HTTPConnection(HOST, PORT)
headers = {
        "Accept": MIME["PSJSON"],
        "Content-Type": MIME["PSJSON"] + "; profile="+ SCHEMAS["port"]
    }
conn.request("PUT", "/ports/pc166_iface0" , json.dumps(port), headers)
res = conn.getresponse()
# This should be 201
print "PORT inserted and returen status is (it should be 201): ", res.status


# POST Multiple Metadata at once
print "POST Multiple Metadata at once"
conn = HTTPConnection(HOST, PORT)
headers = {
        "Accept": MIME["PSJSON"],
        "Content-Type": MIME["PSJSON"] + "; profile="+ SCHEMAS["metadata"]
    }
conn.request("POST", "/metadata", json.dumps([meta1, meta2, meta3, meta4]), headers)
res = conn.getresponse()
# This should be 202
print "Metadata inserted and returen status is (it should be 201): ", res.status


# Sending Blipp
probs = []
for i in range(1000):
    ts = time.time() * 1000000
    probs.append({"mid": "meta1", "ts": ts, "v": ts * 5})
    probs.append({"mid": "meta2", "ts": ts, "v": ts * 5})
    probs.append({"mid": "meta3", "ts": ts, "v": ts * 5})
    probs.append({"mid": "meta4", "ts": ts, "v": ts * 5})

conn = HTTPConnection(HOST, PORT)
headers = {
        "Accept": MIME["PSJSON"],
        "Content-Type": MIME["PSJSON"]
    }
conn.request("POST", "/events", json.dumps(probs), headers)
res = conn.getresponse()
# This should be 202
print res.status, res.read()

