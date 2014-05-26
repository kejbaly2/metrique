#!/usr/bin/env python
# -*- coding: utf-8 -*-
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4
# Author: "Chris Ward" <cward@redhat.com>

from __future__ import unicode_literals

import os

from .utils import set_env
from metrique.utils import remove_file

env = set_env()

testroot = os.path.dirname(os.path.abspath(__file__))
cubes = os.path.join(testroot, 'cubes')
fixtures = os.path.join(testroot, 'fixtures')
etc = os.path.join(testroot, 'etc')
cache_dir = env['METRIQUE_CACHE']
log_dir = env['METRIQUE_LOGS']


def test_csvdata():
    '''

    '''
    from metrique import pyclient
    from metrique.utils import load_shelve
    name = 'us_idx_eod'
    db_file = os.path.join(cache_dir, '%s.sqlite' % name)
    remove_file(db_file)
    m = pyclient(cube='csvdata_rows', name=name)

    uri = os.path.join(fixtures, 'us-idx-eod.csv')
    m.get_objects(uri=uri)

    assert m.objects
    assert len(m.objects) == 14
    assert m.objects.fields == ['__v__', '_e', '_end', '_hash', '_id',
                                '_oid', '_start', '_v', 'close', 'date',
                                'open', 'symbol']

    _ids = m.objects._ids
    _hash = '5a6d18a9c654886926e5f769d4bf4808df6cba39'
    _filtered = m.objects.filter(where={'_hash': _hash})
    assert len(_filtered) == 1
    assert m.objects['11']['_hash'] == _hash  # check _hash is as expected
    assert m.objects['11']['symbol'] == '$AJT'
    assert m.objects.persist() == _ids
    # still there...
    assert m.objects['11']['symbol'] == '$AJT'

    remove_file(db_file)

    # persist and remove from container
    assert m.objects.flush() == _ids
    assert m.objects == {}

    cube = load_shelve(db_file, as_list=False)
    assert cube['11'] == _filtered[0]

    remove_file(db_file)


def test_load_json():
    '''

    '''
    from metrique import pyclient
    from metrique.utils import load

    name = 'meps'
    db_file = os.path.join(cache_dir, '%s.sqlite' % name)
    remove_file(db_file)

    def _oid_func(o):
        o['_oid'] = o['id']
        return o

    m = pyclient(name=name)
    path = os.path.join(fixtures, 'meps.json')
    objects = load(path, _oid=_oid_func, orient='index')

    assert len(objects) == 736

    m.objects.extend(objects)

    assert len(m.objects)

    _ids = m.objects.flush()

    assert sorted(_ids) == sorted(map(unicode, [o['_oid'] for o in objects]))
    assert m.objects == {}

    remove_file(db_file)
