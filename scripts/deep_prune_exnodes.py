# =============================================================================
#  periscope-ps (unis)
#
#  Copyright (c) 2012-2016, Trustees of Indiana University,
#  All rights reserved.
#
#  This software may be modified and distributed under the terms of the BSD
#  license.  See the COPYING file for details.
#
#  This software was created at the Indiana University Center for Research in
#  Extreme Scale Technologies (CREST).
# =============================================================================
from pymongo import MongoClient
from protocol import factory
from protocol.exceptions import AllocationException
import datetime
import concurrent.futures



class Search(object):
    def __init__(self, exnodes, allocs):
        self._exnodes = exnodes
        self._allocs = allocs
    
    def remove_allocation(self, alloc):
        self._allocs.remove({ "id": alloc["id"] })
        print("removing: Allocation[{uid}]".format(uid = alloc["id"]))    


    def test_allocation(self, allocation):
        print("  Testing Allocation[{alloc}]".format(alloc = allocation["id"]))
        try:
            alloc = factory.buildAllocation(allocation)
            if alloc:
                print("Found live allocation: {alloc}".format(alloc = allocation["id"]))
                return allocation["id"]
            else:
                self.remove_allocation(allocation)
                return False
        except Exception as exp:
            print("Could not confirm allocation: {alloc} - {exp}".format(alloc = allocation["id"], exp = exp))
            self.remove_allocation(allocation)
            return False
                
    def clean_exnode(self, exnode):
        valid_allocations = []
        restart = True
        tmpSize = 0
        
        with concurrent.futures.ThreadPoolExecutor(max_workers = 15) as executor:
            for result in executor.map(self.test_allocation, exnode["extents"]):
                if result:
                    valid_allocations.append(result)

        
        while restart:
            restart = False
            for allocation in exnode["extents"]:
                if allocation["offset"] == tmpSize and allocation["id"] in valid_allocations:
                    tmpSize = tmpSize + allocation["size"]
                    restart = True
                    break

        for allocation in exnode["extents"]:
            if allocation["offset"] > tmpSize:
                print("--Incomplete Exnode: Deleting [{actual}/{expected}]".format(actual = tmpSize, expected = exnode["size"]))
                self.remove_allocation(allocation)
                return False
            
        return len(valid_allocations) > 0

    

    def prune_directories(self):
        root = self._exnodes.find({"parent": None})
        
        with concurrent.futures.ThreadPoolExecutor(max_workers = 15) as executor:
            for result in executor.map(self.search_children, root):
                pass


    def search_children(self, exnode):
        contains_data = False

        print("Checking Exnode[{exnode}]".format(exnode = exnode["id"]))
        if exnode["mode"] == "file":
            contains_data = self.clean_exnode(exnode)
            if not contains_data:
                print("removing: Exnode[{exnode}]".format(exnode = exnode["id"]))
                self._exnodes.remove({ "id": exnode["id"] })
                
            return contains_data

        children = self._exnodes.find({ "parent": exnode["id"] })
    
        with concurrent.futures.ThreadPoolExecutor(max_workers = 15) as executor:
            for result in executor.map(self.search_children, children):
                contains_data = contains_data | result

        if not contains_data:
            self._exnodes.remove({"id": exnode["id"]})
            print "Removing Directory: {0}".format(exnode["name"])
        
        return contains_data


def main():
    client = MongoClient()
    db = client["unis_db"]
    search = Search(db.exnodes, db.extents)

    print("Starting prune....")
    search.prune_directories()

    
if __name__ == "__main__":
    main()
