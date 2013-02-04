#!/usr/bin/env python
"""
A generic abstract class that used to implement the NetworkResource HTTP methods.
"""

__author__ = 'Ahmed El-Hassany <a.hassany@gmail.com>'
__license__ = 'http://www.apache.org/licenses/LICENSE-2.0'


import abc


class GenericHandlerImpl(object):

    __mataclass__ = abc.ABCMeta

    @classmethod
    @abc.abstractmethod
    def get(cls, handler, res_id, query, is_list, fields, limit):
        pass

    @classmethod
    @abc.abstractmethod
    def post(cls, handler):
        pass

    @classmethod
    @abc.abstractmethod
    def put(cls, handler, res_id):
        pass

    @classmethod
    @abc.abstractmethod
    def delete(cls, handler, res_id):
        pass

    @classmethod
    @abc.abstractmethod
    def publish(cls, handler, resource, callback, res_type=None):
        pass

    @classmethod
    @abc.abstractmethod
    def subscribe(cls, handler, query, callback):
        pass

