# Copyright 2015 SimpliVity Corp.
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

from oslo.config import cfg

from cinder.i18n import _LI, _LW
from cinder.openstack.common import log as logging
from cinder.volume.drivers.simplivity import virtual_controller as vc
from cinder.volume.drivers.vmware import vim
from cinder.volume.drivers.vmware import vmdk as vmware_vmdk

LOG = logging.getLogger(__name__)

"""
Setup instructions:

1. Edit /etc/cinder/cinder.conf:
  [DEFAULT]
  default_volume_type = simplivity
  enabled_backends = simplivity

  [simplivity]
  volume_driver = cinder.volume.drivers.simplivity.SvtVmdkDriver
  volume_backend_name = simplivity
  vmware_host_username = administrator
  vmware_host_password = password
  vmware_host_ip = 192.168.1.10
  vc_host = 192.168.1.15
  vc_username = svtcli
  vc_password = password

2. Restart cinder-volume.
"""
simplivity_opts = [
    cfg.StrOpt('vc_host',
               default=None,
               help='Hostname or ipv4 address of the virtual controller for '
                    'the given cluster'),
    cfg.StrOpt('vc_username',
               default='svtcli',
               help='Username to log into the virtual controller'),
    cfg.StrOpt('vc_password',
               default=None,
               help=('Password associated with the username to log into '
                     'the virtual controller')),
]

CONF = cfg.CONF
CONF.register_opts(simplivity_opts, 'simplivity')


class SvtVmdkDriver(vmware_vmdk.VMwareVcVmdkDriver):
    """Manage volumes on VMware vCenter server."""

    def __init__(self, *args, **kwargs):
        LOG.debug("svt: Initializing SimpliVity VMDK driver")

        # To get the user and password:
        #    user = CONF.simplivity.vc_username
        #    passwd = CONF.simplivity.vc_password

        super(SvtVmdkDriver, self).__init__(*args, **kwargs)

        # Establish connection to virtual controller
        self.vc_connection = self._get_vc_connection()
        self.vc_ops = vc.SvtOperations(self.vc_connection)

    def _get_vc_connection(self):
        """Returns an object representing a connection to the virtual
        controller.
        """
        return vc.SvtConnection(CONF.simplivity.vc_host,
                                CONF.simplivity.vc_username,
                                CONF.simplivity.vc_password,
                                vmware_username=CONF.vmware_host_username,
                                vmware_password=CONF.vmware_host_password)

    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""

        """
        The implementation returns the following info:
        {'driver_volume_type': 'vmdk'
         'data': {'volume': $volume_moref
                  'volume_id': $volume_id}}
        """
        return self._initialize_connection(volume, connector)

    def _initialize_connection(self, volume, connector):
        """Get information of volume's backing. If the volume does not have
        a backing yet, it will be created.

        :param volume: Volume object
        :param connector: Connector information
        :return: Return connection information
        """
        connection_info = {'driver_volume_type': 'vmdk'}
        backing = self.volumeops.get_backing(volume['name'])
        if 'instance' in connector:
            # The instance exists
            instance = vim.get_moref(connector['instance'], 'VirtualMachine')
            LOG.debug("svt: Instance %s exists for initialize connection "
                      "call." % instance)

            # Get host managing the instance
            host = self.volumeops.get_host(instance)
            if not backing:
                # Create a backing in case it does not exist under the
                # host managing the instance.
                LOG.info(_LI("There is no backing for the volume: %s. "
                             "Need to create one.") % volume['name'])

                """
                The following sequence of actions are performed:
                    1. If no backing exists, create a volume (disk-less)
                       backing
                    2. On volume-attach, create disk inside instance backing
                    3. On volume-detach, move disk inside instance to
                       volume backing
                    4. On volume-reattach, move disk inside volume backing
                       to instance backing
                """
                create_params = {'disk_less': True}
                backing = self._create_backing(volume, host,
                                               create_params=create_params)
            else:
                self._relocate_backing(volume, backing, host)
        else:
            # The instance does not exist
            LOG.debug("svt: Instance does not exists for initialize "
                      "connection call.")
            if not backing:
                # Create a backing in case it does not exist. It is a bad use
                # case to boot from an empty volume.
                LOG.warn(_LW("Trying to boot from an empty volume: %s.") %
                         volume['name'])
                # Create backing
                backing = self._create_backing_in_inventory(volume)

        # Set volume's moref value and name
        connection_info['data'] = {'volume': backing.value,
                                   'volume_id': volume['id']}

        LOG.info(_LI("Returning connection_info: %(info)s for volume: "
                     "%(volume)s with connector: %(connector)s.") %
                 {'info': connection_info,
                  'volume': volume['name'],
                  'connector': connector})

        return connection_info

    def _relocate_backing(self, volume, backing, host):
        pass
