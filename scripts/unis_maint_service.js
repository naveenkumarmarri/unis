// =============================================================================
//  periscope-ps (unis)
//
//  Copyright (c) 2012-2016, Trustees of Indiana University,
//  All rights reserved.
//
//  This software may be modified and distributed under the terms of the BSD
//  license.  See the COPYING file for details.
//
//  This software was created at the Indiana University Center for Research in
//  Extreme Scale Technologies (CREST).
// =============================================================================
// remove any service entries that have expired
// i.e.: timestamp + time-to-live is less than now
function removeExpired(entry) {
    if ((entry.ts + entry.ttl*1e6) < now) {
	//printjson(entry)
	db.services.remove(entry)
    }
}

conn = new Mongo()
db = conn.getDB("unis_db")
now = new Date().getTime()*1000

// get all services
cur = db.services.find()
cur.forEach(removeExpired)
