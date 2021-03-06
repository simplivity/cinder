# Copyright (c) 2014, Oracle and/or its affiliates. All rights reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
"""
ZFS Storage Appliance Proxy
"""
import json

from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log
from cinder.volume.drivers.zfssa import restclient

LOG = log.getLogger(__name__)


class ZFSSAApi(object):
    """ZFSSA API proxy class"""

    def __init__(self):
        self.host = None
        self.url = None
        self.rclient = None

    def __del__(self):
        if self.rclient and self.rclient.islogin():
            self.rclient.logout()

    def _is_pool_owned(self, pdata):
        """returns True if the pool's owner is the
           same as the host.
        """
        svc = '/api/system/v1/version'
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            exception_msg = (_('Error getting version: '
                               'svc: %(svc)s.'
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'svc': svc,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

        vdata = json.loads(ret.data)
        return vdata['version']['asn'] == pdata['pool']['asn'] and \
            vdata['version']['nodename'] == pdata['pool']['owner']

    def set_host(self, host, timeout=None):
        self.host = host
        self.url = "https://" + self.host + ":215"
        self.rclient = restclient.RestClientURL(self.url, timeout=timeout)

    def login(self, auth_str):
        """Login to the appliance"""
        if self.rclient and not self.rclient.islogin():
            self.rclient.login(auth_str)

    def get_pool_stats(self, pool):
        """Get space available and total properties of a pool
           returns (avail, total).
        """
        svc = '/api/storage/v1/pools/' + pool
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            exception_msg = (_('Error Getting Pool Stats: '
                               'Pool: %(pool)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'pool': pool,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.InvalidVolume(reason=exception_msg)

        val = json.loads(ret.data)

        if not self._is_pool_owned(val):
            exception_msg = (_('Error Pool ownership: '
                               'Pool %(pool)s is not owned '
                               'by %(host)s.')
                             % {'pool': pool,
                                'host': self.host})
            LOG.error(exception_msg)
            raise exception.InvalidInput(reason=pool)

        avail = val['pool']['usage']['available']
        total = val['pool']['usage']['total']

        return avail, total

    def create_project(self, pool, project, compression=None, logbias=None):
        """Create a project on a pool
           Check first whether the pool exists.
        """
        self.verify_pool(pool)
        svc = '/api/storage/v1/pools/' + pool + '/projects/' + project
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            svc = '/api/storage/v1/pools/' + pool + '/projects'
            arg = {
                'name': project
            }
            if compression and compression != '':
                arg.update({'compression': compression})
            if logbias and logbias != '':
                arg.update({'logbias': logbias})

            ret = self.rclient.post(svc, arg)
            if ret.status != restclient.Status.CREATED:
                exception_msg = (_('Error Creating Project: '
                                   '%(project)s on '
                                   'Pool: %(pool)s '
                                   'Return code: %(ret.status)d '
                                   'Message: %(ret.data)s .')
                                 % {'project': project,
                                    'pool': pool,
                                    'ret.status': ret.status,
                                    'ret.data': ret.data})
                LOG.error(exception_msg)
                raise exception.VolumeBackendAPIException(data=exception_msg)

    def create_initiator(self, initiator, alias, chapuser=None,
                         chapsecret=None):
        """Create an iSCSI initiator."""

        svc = '/api/san/v1/iscsi/initiators/alias=' + alias
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            svc = '/api/san/v1/iscsi/initiators'
            arg = {
                'initiator': initiator,
                'alias': alias
            }
            if chapuser and chapuser != '' and chapsecret and chapsecret != '':
                arg.update({'chapuser': chapuser,
                            'chapsecret': chapsecret})

            ret = self.rclient.post(svc, arg)
            if ret.status != restclient.Status.CREATED:
                exception_msg = (_('Error Creating Initiator: '
                                   '%(initiator)s on '
                                   'Alias: %(alias)s '
                                   'Return code: %(ret.status)d '
                                   'Message: %(ret.data)s .')
                                 % {'initiator': initiator,
                                    'alias': alias,
                                    'ret.status': ret.status,
                                    'ret.data': ret.data})
                LOG.error(exception_msg)
                raise exception.VolumeBackendAPIException(data=exception_msg)

    def add_to_initiatorgroup(self, initiator, initiatorgroup):
        """Add an iSCSI initiator to initiatorgroup"""
        svc = '/api/san/v1/iscsi/initiator-groups/' + initiatorgroup
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            svc = '/api/san/v1/iscsi/initiator-groups'
            arg = {
                'name': initiatorgroup,
                'initiators': [initiator]
            }
            ret = self.rclient.post(svc, arg)
            if ret.status != restclient.Status.CREATED:
                exception_msg = (_('Error Adding Initiator: '
                                   '%(initiator)s on group'
                                   'InitiatorGroup: %(initiatorgroup)s '
                                   'Return code: %(ret.status)d '
                                   'Message: %(ret.data)s .')
                                 % {'initiator': initiator,
                                    'initiatorgroup': initiatorgroup,
                                    'ret.status': ret.status,
                                    'ret.data': ret.data})
                LOG.error(exception_msg)
                raise exception.VolumeBackendAPIException(data=exception_msg)
        else:
            val = json.loads(ret.data)
            inits = val['group']['initiators']
            if inits is None:
                exception_msg = (_('Error Getting Initiators: '
                                   'InitiatorGroup: %(initiatorgroup)s '
                                   'Return code: %(ret.status)d '
                                   'Message: %(ret.data)s .')
                                 % {'initiatorgroup': initiatorgroup,
                                    'ret.status': ret.status,
                                    'ret.data': ret.data})
                LOG.error(exception_msg)
                raise exception.VolumeBackendAPIException(data=exception_msg)

            if initiator in inits:
                return

            inits.append(initiator)
            svc = '/api/san/v1/iscsi/initiator-groups/' + initiatorgroup
            arg = {
                'initiators': inits
            }
            ret = self.rclient.put(svc, arg)
            if ret.status != restclient.Status.ACCEPTED:
                exception_msg = (_('Error Adding Initiator: '
                                   '%(initiator)s on group'
                                   'InitiatorGroup: %(initiatorgroup)s '
                                   'Return code: %(ret.status)d '
                                   'Message: %(ret.data)s .')
                                 % {'initiator': initiator,
                                    'initiatorgroup': initiatorgroup,
                                    'ret.status': ret.status,
                                    'ret.data': ret.data})
                LOG.error(exception_msg)
                raise exception.VolumeBackendAPIException(data=exception_msg)

    def create_target(self, alias, interfaces=None, tchapuser=None,
                      tchapsecret=None):
        """Create an iSCSI target.
           interfaces: an array with network interfaces
           tchapuser, tchapsecret: target's chapuser and chapsecret
           returns target iqn
        """
        svc = '/api/san/v1/iscsi/targets/alias=' + alias
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            svc = '/api/san/v1/iscsi/targets'
            arg = {
                'alias': alias
            }

            if tchapuser and tchapuser != '' and tchapsecret and \
               tchapsecret != '':
                arg.update({'targetchapuser': tchapuser,
                            'targetchapsecret': tchapsecret,
                            'auth': 'chap'})

            if interfaces is not None and len(interfaces) > 0:
                arg.update({'interfaces': interfaces})

            ret = self.rclient.post(svc, arg)
            if ret.status != restclient.Status.CREATED:
                exception_msg = (_('Error Creating Target: '
                                   '%(alias)s'
                                   'Return code: %(ret.status)d '
                                   'Message: %(ret.data)s .')
                                 % {'alias': alias,
                                    'ret.status': ret.status,
                                    'ret.data': ret.data})
                LOG.error(exception_msg)
                raise exception.VolumeBackendAPIException(data=exception_msg)

        val = json.loads(ret.data)
        return val['target']['iqn']

    def get_target(self, alias):
        """Get an iSCSI target iqn."""
        svc = '/api/san/v1/iscsi/targets/alias=' + alias
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            exception_msg = (_('Error Getting Target: '
                               '%(alias)s'
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s .')
                             % {'alias': alias,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

        val = json.loads(ret.data)
        return val['target']['iqn']

    def add_to_targetgroup(self, iqn, targetgroup):
        """Add an iSCSI target to targetgroup."""
        svc = '/api/san/v1/iscsi/target-groups/' + targetgroup
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            svccrt = '/api/san/v1/iscsi/target-groups'
            arg = {
                'name': targetgroup,
                'targets': [iqn]
            }

            ret = self.rclient.post(svccrt, arg)
            if ret.status != restclient.Status.CREATED:
                exception_msg = (_('Error Creating TargetGroup: '
                                   '%(targetgroup)s with'
                                   'IQN: %(iqn)s'
                                   'Return code: %(ret.status)d '
                                   'Message: %(ret.data)s .')
                                 % {'targetgroup': targetgroup,
                                    'iqn': iqn,
                                    'ret.status': ret.status,
                                    'ret.data': ret.data})
                LOG.error(exception_msg)
                raise exception.VolumeBackendAPIException(data=exception_msg)

            return

        arg = {
            'targets': [iqn]
        }

        ret = self.rclient.put(svc, arg)
        if ret.status != restclient.Status.ACCEPTED:
            exception_msg = (_('Error Adding to TargetGroup: '
                               '%(targetgroup)s with'
                               'IQN: %(iqn)s'
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'targetgroup': targetgroup,
                                'iqn': iqn,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def verify_pool(self, pool):
        """Checks whether pool exists."""
        svc = '/api/storage/v1/pools/' + pool
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            exception_msg = (_('Error Verifying Pool: '
                               '%(pool)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'pool': pool,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def verify_project(self, pool, project):
        """Checks whether project exists."""
        svc = '/api/storage/v1/pools/' + pool + '/projects/' + project
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            exception_msg = (_('Error Verifying '
                               'Project: %(project)s on '
                               'Pool: %(pool)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'project': project,
                                'pool': pool,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def verify_initiator(self, iqn):
        """Check whether initiator iqn exists."""
        svc = '/api/san/v1/iscsi/initiators/' + iqn
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            exception_msg = (_('Error Verifying '
                               'Initiator: %(iqn)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'initiator': iqn,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def verify_target(self, alias):
        """Check whether target alias exists."""
        svc = '/api/san/v1/iscsi/targets/alias=' + alias
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            exception_msg = (_('Error Verifying '
                               'Target: %(alias)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'alias': alias,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def create_lun(self, pool, project, lun, volsize, targetgroup,
                   volblocksize='8k', sparse=False, compression=None,
                   logbias=None):
        """Create a LUN.
           required - pool, project, lun, volsize, targetgroup.
           optional - volblocksize, sparse, compression, logbias
        """
        svc = '/api/storage/v1/pools/' + pool + '/projects/' + \
              project + '/luns'
        arg = {
            'name': lun,
            'volsize': volsize,
            'targetgroup': targetgroup,
            'initiatorgroup': 'com.sun.ms.vss.hg.maskAll',
            'volblocksize': volblocksize,
            'sparse': sparse
        }
        if compression and compression != '':
            arg.update({'compression': compression})
        if logbias and logbias != '':
            arg.update({'logbias': logbias})

        ret = self.rclient.post(svc, arg)
        if ret.status != restclient.Status.CREATED:
            exception_msg = (_('Error Creating '
                               'Volume: %(lun)s '
                               'Size: %(size)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'lun': lun,
                                'size': volsize,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def get_lun(self, pool, project, lun):
        """return iscsi lun properties."""
        svc = '/api/storage/v1/pools/' + pool + '/projects/' + \
            project + "/luns/" + lun
        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            exception_msg = (_('Error Getting '
                               'Volume: %(lun)s on '
                               'Pool: %(pool)s '
                               'Project: %(project)s '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'lun': lun,
                                'pool': pool,
                                'project': project,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

        val = json.loads(ret.data)
        ret = {
            'guid': val['lun']['lunguid'],
            'number': val['lun']['assignednumber'],
            'initiatorgroup': val['lun']['initiatorgroup'],
            'size': val['lun']['volsize'],
            'nodestroy': val['lun']['nodestroy']
        }
        if 'origin' in val['lun']:
            ret.update({'origin': val['lun']['origin']})
        if isinstance(ret['number'], list):
            ret['number'] = ret['number'][0]

        return ret

    def set_lun_initiatorgroup(self, pool, project, lun, initiatorgroup):
        """Set the initiatorgroup property of a LUN."""
        if initiatorgroup == '':
            initiatorgroup = 'com.sun.ms.vss.hg.maskAll'

        svc = '/api/storage/v1/pools/' + pool + '/projects/' + \
            project + '/luns/' + lun
        arg = {
            'initiatorgroup': initiatorgroup
        }

        ret = self.rclient.put(svc, arg)
        if ret.status != restclient.Status.ACCEPTED:
            exception_msg = (_('Error Setting '
                               'Volume: %(lun)s to '
                               'InitiatorGroup: %(initiatorgroup)s '
                               'Pool: %(pool)s '
                               'Project: %(project)s  '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'lun': lun,
                                'initiatorgroup': initiatorgroup,
                                'pool': pool,
                                'project': project,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)

    def delete_lun(self, pool, project, lun):
        """delete iscsi lun."""
        svc = '/api/storage/v1/pools/' + pool + '/projects/' + \
            project + '/luns/' + lun

        ret = self.rclient.delete(svc)
        if ret.status != restclient.Status.NO_CONTENT:
            exception_msg = (_('Error Deleting '
                               'Volume: %(lun)s to '
                               'Pool: %(pool)s '
                               'Project: %(project)s  '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'lun': lun,
                                'pool': pool,
                                'project': project,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)

    def create_snapshot(self, pool, project, lun, snapshot):
        """create snapshot."""
        svc = '/api/storage/v1/pools/' + pool + '/projects/' + \
            project + '/luns/' + lun + '/snapshots'
        arg = {
            'name': snapshot
        }

        ret = self.rclient.post(svc, arg)
        if ret.status != restclient.Status.CREATED:
            exception_msg = (_('Error Creating '
                               'Snapshot: %(snapshot)s on'
                               'Volume: %(lun)s to '
                               'Pool: %(pool)s '
                               'Project: %(project)s  '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'snapshot': snapshot,
                                'lun': lun,
                                'pool': pool,
                                'project': project,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def delete_snapshot(self, pool, project, lun, snapshot):
        """delete snapshot."""
        svc = '/api/storage/v1/pools/' + pool + '/projects/' + \
              project + '/luns/' + lun + '/snapshots/' + snapshot

        ret = self.rclient.delete(svc)
        if ret.status != restclient.Status.NO_CONTENT:
            exception_msg = (_('Error Deleting '
                               'Snapshot: %(snapshot)s on '
                               'Volume: %(lun)s to '
                               'Pool: %(pool)s '
                               'Project: %(project)s  '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'snapshot': snapshot,
                                'lun': lun,
                                'pool': pool,
                                'project': project,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def clone_snapshot(self, pool, project, lun, snapshot, clone):
        """clone snapshot."""
        svc = '/api/storage/v1/pools/' + pool + '/projects/' + \
            project + '/luns/' + lun + '/snapshots/' + snapshot + '/clone'
        arg = {
            'project': project,
            'share': clone,
            'nodestroy': True
        }

        ret = self.rclient.put(svc, arg)
        if ret.status != restclient.Status.CREATED:
            exception_msg = (_('Error Cloning '
                               'Snapshot: %(snapshot)s on '
                               'Volume: %(lun)s of '
                               'Pool: %(pool)s '
                               'Project: %(project)s  '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'snapshot': snapshot,
                                'lun': lun,
                                'pool': pool,
                                'project': project,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def set_lun_props(self, pool, project, lun, **kargs):
        """set lun properties."""
        svc = '/api/storage/v1/pools/' + pool + '/projects/' + \
            project + '/luns/' + lun
        if kargs is None:
            return

        ret = self.rclient.put(svc, kargs)
        if ret.status != restclient.Status.ACCEPTED:
            exception_msg = (_('Error Setting props '
                               'Props: %(props)s on '
                               'Volume: %(lun)s of '
                               'Pool: %(pool)s '
                               'Project: %(project)s  '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'props': kargs,
                                'lun': lun,
                                'pool': pool,
                                'project': project,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

    def has_clones(self, pool, project, lun, snapshot):
        """Checks whether snapshot has clones or not."""
        svc = '/api/storage/v1/pools/' + pool + '/projects/' + \
            project + '/luns/' + lun + '/snapshots/' + snapshot

        ret = self.rclient.get(svc)
        if ret.status != restclient.Status.OK:
            exception_msg = (_('Error Getting '
                               'Snapshot: %(snapshot)s on '
                               'Volume: %(lun)s to '
                               'Pool: %(pool)s '
                               'Project: %(project)s  '
                               'Return code: %(ret.status)d '
                               'Message: %(ret.data)s.')
                             % {'snapshot': snapshot,
                                'lun': lun,
                                'pool': pool,
                                'project': project,
                                'ret.status': ret.status,
                                'ret.data': ret.data})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

        val = json.loads(ret.data)
        return val['snapshot']['numclones'] != 0
