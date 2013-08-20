#!/usr/bin/env python
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4
# Author: "Chris Ward <cward@redhat.com>

import logging
import base64
logger = logging.getLogger(__name__)

from functools import wraps
import simplejson as json
import tornado
import traceback

from metrique.server.defaults import VALID_PERMISSIONS
from metrique.server import query_api, etl_api, users_api

from metrique.tools import hash_password


# FIXME: create jobsave meta data here! rather rapping handler gets
def async(f):
    '''
    Decorator for enabling async Tornado.Handlers
    If not metrique.config.async: disable async

    Requires: futures

    Uses: async.threading
    '''
    @tornado.web.asynchronous
    @wraps(f)
    def wrapper(self, *args, **kwargs):
        if self.proxy.metrique_config.async:
            def future_end(future):
                try:
                    _result = future.result()
                    logger.debug('JSON dump: START... ')
                    result = json.dumps(_result, ensure_ascii=False)
                    logger.debug('JSON dump: DONE')
                except Exception:
                    result = traceback.format_exc()
                    logger.error(result)
                    raise tornado.web.HTTPError(500, result)
                finally:
                    self.write(result)
                self.finish()

            future = self.proxy.executor.submit(f, self, *args, **kwargs)
            tornado.ioloop.IOLoop.instance().add_future(future, future_end)
        else:
            _result = f(self, *args, **kwargs)
            logger.debug('JSON dump: START... ')
            result = json.dumps(_result, ensure_ascii=False)
            logger.debug('JSON dump: DONE... ')
            self.write(result)
            self.finish()
    return wrapper


def request_authentication(handler):
    ''' Helper-Function for settig 401 - Request for authentication '''
    handler.set_status(401)
    handler.set_header('WWW-Authenticate', 'Basic realm="Metrique"')


# user is not admin... lookup username in auth_keys
def cube_check(handler, cube, lookup):
    spec = {'_id': cube,
            lookup: {'$exists': True}}
    logger.debug("Cube Check: spec (%s)" % spec)
    return handler.proxy.mongodb_config.c_auth_keys.find_one(spec)


def authenticate(handler, username, password, permissions):
    ''' Helper-Function for determining whether a given
        user:password:permissions combination provides
        client with enough privleges to execute
        the requested command against the given cube '''
    # if auth isn't on, let anyone do anything!
    if not handler.proxy.metrique_config.auth:
        return True

    # GLOBAL DEFAULT
    cube = handler.get_argument('cube')
    if username == handler.proxy.metrique_config.admin_user:
        admin_password = handler.proxy.metrique_config.admin_password
        if password == admin_password:
            # admin pass is stored in plain text
            # we're admin user and so we get 'rw' to all cubes
            return True

    udoc = cube_check(handler, cube, username)
    audoc = cube_check(handler, '__all__', username)
    adoc = cube_check(handler, '__all__', '__all__')

    if udoc:
        user = udoc[username]
    if audoc:
        user = audoc[username]
    elif adoc:
        user = adoc['__all__']
    else:
        return False

    # permissions is a single string
    assert isinstance(permissions, basestring)
    VP = VALID_PERMISSIONS
    has_perms = VP.index(user['permissions']) >= VP.index(permissions)

    if not user['password'] and has_perms:
        return True

    _, p_hash = hash_password(password, user['salt'])
    p_match = user['password'] == p_hash
    if p_match and has_perms:
        # password is defined, make sure user's pass matches it
        # and that the user has the right permissions defined
        return True
    return False


def auth(permissions='r'):
    ''' Decorator for auth dependent Tornado.Handlers '''
    def decorator(f):
        @wraps(f)
        def wrapper(handler, *args, **kwargs):
            auth_header = handler.request.headers.get('Authorization')
            if auth_header is None or not auth_header.startswith('Basic '):
                #No HTTP Basic Authentication header
                return request_authentication(handler)

            auth = base64.decodestring(auth_header[6:])
            username, password = auth.split(':', 2)
            privleged = authenticate(handler, username, password, permissions)
            logger.debug("User (%s): Privleged (%s)" % (username, privleged))
            if privleged:
                return f(handler, *args, **kwargs)
            else:
                return request_authentication(handler)
        return wrapper
    return decorator


class MetriqueInitialized(tornado.web.RequestHandler):
    '''
        Template RequestHandler that accepts init parameters
        and unifies json get_argument handling
    '''

    def initialize(self, proxy):
        '''
        Paremeters
        ----------
        proxy : HTTPServer (MetriqueServer) Obj
            A pointer to the running metrique server namespace
        '''
        self.proxy = proxy

    def get_argument(self, key, default=None):
        '''
            Assume incoming arguments are json encoded,
            get_arguments should always deserialize
            on the way in
        '''
        # arguments are expected to be json encoded!
        _arg = super(MetriqueInitialized, self).get_argument(key, default)

        if _arg is None:
            return _arg

        try:
            arg = json.loads(_arg)
        except Exception as e:
            raise ValueError("Invalid JSON content (%s): %s" % (type(_arg), e))
        return arg


class PingHandler(MetriqueInitialized):
    ''' RequestHandler for pings'''
    @async
    def get(self):
        return self.proxy.ping()


class QueryAggregateHandler(MetriqueInitialized):
    '''
        RequestHandler for running mongodb aggregation
        framwork pipeines against a given cube
    '''
    @auth('r')
    @async
    def get(self):
        cube = self.get_argument('cube')
        pipeline = self.get_argument('pipeline', '[]')
        return query_api.aggregate(cube, pipeline)


class QueryFetchHandler(MetriqueInitialized):
    ''' RequestHandler for fetching lumps of cube data '''
    @auth('r')
    @async
    def get(self):
        cube = self.get_argument('cube')
        fields = self.get_argument('fields')
        date = self.get_argument('date')
        sort = self.get_argument('sort', None)
        skip = self.get_argument('skip', 0)
        limit = self.get_argument('limit', 0)
        ids = self.get_argument('ids', [])
        return query_api.fetch(cube=cube, fields=fields, date=date,
                               sort=sort, skip=skip, limit=limit, ids=ids)


class QueryCountHandler(MetriqueInitialized):
    '''
        RequestHandler for returning back simple integer
        counts of objects matching the given query
    '''
    @auth('r')
    @async
    def get(self):
        cube = self.get_argument('cube')
        query = self.get_argument('query')
        return query_api.count(cube, query)


class QueryFindHandler(MetriqueInitialized):
    '''
        RequestHandler for returning back object
        matching the given query
    '''
    @auth('r')
    @async
    def get(self):
        cube = self.get_argument('cube')
        query = self.get_argument('query')
        fields = self.get_argument('fields', '')
        date = self.get_argument('date')
        sort = self.get_argument('sort', None)
        one = self.get_argument('one', False)
        return query_api.find(cube=cube,
                              query=query,
                              fields=fields,
                              date=date,
                              sort=sort,
                              one=one)


class QueryDistinctHandler(MetriqueInitialized):
    '''
        RequestHandler for fetching distinct token values for a
        given cube.field
    '''
    @auth('r')
    @async
    def get(self):
        cube = self.get_argument('cube')
        field = self.get_argument('field')
        return query_api.distinct(cube=cube, field=field)


class UsersAddHandler(MetriqueInitialized):
    '''
        RequestHandler for managing user access control
        lists for a given cube
    '''
    @auth('admin')
    @async
    def get(self):
        cube = self.get_argument('cube')
        user = self.get_argument('user')
        password = self.get_argument('password')
        permissions = self.get_argument('permissions', 'r')
        return users_api.add(cube, user,
                             password, permissions)


class ETLIndexHandler(MetriqueInitialized):
    '''
        RequestHandler for ensuring mongodb indexes
        in timeline collection for a given cube
    '''
    @auth('rw')
    @async
    def get(self):
        cube = self.get_argument('cube')
        ensure = self.get_argument('ensure')
        drop = self.get_argument('drop')
        return etl_api.index(cube=cube, ensure=ensure, drop=drop)


class ETLActivityImportHandler(MetriqueInitialized):
    '''
        RequestHandler for building pre-calculated
        object timelines given a 'activity history'
        data source that can be used to recreate
        objects in time
    '''
    @auth('rw')
    @async
    def get(self):
        cube = self.get_argument('cube')
        ids = self.get_argument('ids')
        return etl_api.activity_import(cube=cube, ids=ids)


class ETLSaveObjects(MetriqueInitialized):
    '''
        RequestHandler for saving a given
        object to a metrique server cube
    '''
    @auth('rw')
    @async
    def post(self):
        cube = self.get_argument('cube')
        objects = self.get_argument('objects')
        update = self.get_argument('update')
        mtime = self.get_argument('mtime')
        return etl_api.save_objects(cube=cube, objects=objects, update=update,
                                    mtime=mtime)


class ETLRemoveObjects(MetriqueInitialized):
    '''
        RequestHandler for saving a given
        object to a metrique server cube
    '''
    @auth('rw')
    @async
    def delete(self):
        cube = self.get_argument('cube')
        ids = self.get_argument('ids')
        backup = self.get_argument('backup')
        return etl_api.remove_objects(cube=cube, ids=ids,
                                      backup=backup)


class ETLCubeDrop(MetriqueInitialized):
    ''' RequestsHandler for droping given cube from timeline '''
    @auth('rw')
    @async
    def delete(self):
        cube = self.get_argument('cube')
        return etl_api.drop(cube=cube)


class CubeHandler(MetriqueInitialized):
    '''
        RequestHandler for querying about
        available cubes and cube.fields
    '''
    @auth('r')
    @async
    def get(self):
        cube = self.get_argument('cube')
        _mtime = self.get_argument('_mtime')
        exclude_fields = self.get_argument('exclude_fields')
        if cube is None:
            # return a list of cubes
            return self.proxy.list_cubes()
        else:
            # return a list of fields in a cube
            return self.proxy.list_cube_fields(cube,
                                               exclude_fields,
                                               _mtime)
