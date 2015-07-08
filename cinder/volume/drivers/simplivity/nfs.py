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

import errno
import os

from oslo_config import cfg

from cinder import exception
from cinder.i18n import _, _LW
from cinder.brick.remotefs import remotefs
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils
from cinder.openstack.common import units
from cinder import utils
from cinder.volume.drivers import nfs

LOG = logging.getLogger(__name__)

"""
Setup instructions:

1. Edit /etc/cinder/cinder.conf:
  [DEFAULT]
  default_volume_type = simplivity
  enabled_backends = simplivity

  [simplivity]
  volume_driver = cinder.volume.drivers.simplivity.SvtNfsDriver
  volume_backend_name = simplivity

2. Append virtual controller IP and hostname to /etc/hosts
  # echo  "<ip> omni.cube.io" >> /etc/hosts

3. Append datastore(s) to /etc/cinder/shares.conf
  # echo omni.cube.io:/mnt/svtfs/0/<guid> >> /etc/cinder/shares.conf

4. Restart cinder-volume.
"""

volume_opts = [
    cfg.StrOpt('svt_shares_config',
               default='/etc/cinder/shares.conf',
               help='File with the list of available nfs shares'),
    cfg.BoolOpt('svt_sparsed_volumes',
                default=True,
                help=('Create volumes as sparsed files which take no space.'
                      'If set to False volume is created as regular file.'
                      'In such case volume creation takes a lot of time.')),
    cfg.FloatOpt('svt_used_ratio',
                 default=0.90,
                 help=('Percent of ACTUAL usage of the underlying volume '
                       'before no new volumes can be allocated to the volume '
                       'destination.')),
    cfg.FloatOpt('svt_oversub_ratio',
                 default=1.0,
                 help=('This will compare the allocated to available space on '
                       'the volume destination.  If the ratio exceeds this '
                       'number, the destination will no longer be valid.')),
    cfg.StrOpt('svt_mount_point_base',
               default='/var/lib/cinder/mnt',
               help=('Base dir containing mount points for nfs shares.')),
    cfg.StrOpt('svt_mount_options',
               default='vers=3,noac',
               help=('Mount options passed to the nfs client. See section '
                     'of the nfs man page for details.')),
]

CONF = cfg.CONF
CONF.register_opts(volume_opts)
DEFAULT_VOLUME_DIR = "_volumes"


# Base class is NfsDriver found in cinder/volume/drivers/nfs.py
class SvtNfsDriver(nfs.NfsDriver):

    # SimpliVity specific attributes
    driver_volume_type = 'svt'
    driver_prefix = 'svt'
    volume_backend_name = 'SimpliVity'
    VERSION = "1.0.0"

    def __init__(self, execute=processutils.execute, *args, **kwargs):
        # Create RemoteFsClient object (cinder/brick/remotefs/remotefs.py)
        # to do the actual mount command
        self._remotefsclient = None
        super(SvtNfsDriver, self).__init__(*args, **kwargs)

        # Get mount options which should be specified in
        # /etc/cinder/cinder.conf
        self.configuration.append_config_values(volume_opts)
        root_helper = utils.get_root_helper()
        base = getattr(self.configuration, 'svt_mount_point_base',
                       CONF.svt_mount_point_base)
        opts = getattr(self.configuration, 'svt_mount_options',
                       CONF.svt_mount_options)

        # This is an NFS mount (other one supported is glusterfs)
        self._remotefsclient = remotefs.RemoteFsClient(
            'nfs', root_helper, execute=execute,
            nfs_mount_point_base=base,
            nfs_mount_options=opts)

    def do_setup(self, context):
        """Any initialization the volume driver does while starting"""
        config = self.configuration.svt_shares_config
        if not config:
            msg = (_("There is no NFS config file configured (%s)") %
                   'svt_shares_config')
            LOG.error(msg)
            raise exception.NfsException(msg)

        if not os.path.exists(config):
            msg = (_("NFS config file at %(config)s does not exist") %
                   {'config': config})
            LOG.error(msg)
            raise exception.NfsException(msg)

        if not self.configuration.svt_oversub_ratio > 0:
            msg = (_("NFS config 'nfs_oversub_ratio' is invalid.  It must "
                     "be > 0: %s") %
                   self.configuration.svt_oversub_ratio)

            LOG.error(msg)
            raise exception.NfsException(msg)

        if (self.configuration.svt_used_ratio <= 0 or
                self.configuration.svt_used_ratio > 1):
            msg = _("NFS config 'svt_used_ratio' is invalid.  It must be > 0 "
                    "and <= 1.0: %s") % self.configuration.svt_used_ratio
            LOG.error(msg)
            raise exception.NfsException(msg)

        self.shares = {}  # address : options

        # Check if mount.nfs is installed
        try:
            self._execute('mount.nfs', check_exit_code=False, run_as_root=True)
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                raise exception.NfsException('mount.nfs is not installed')
            else:
                raise exc

    def delete_volume(self, volume):
        """Deletes a logical volume."""
        LOG.debug('svt: delete_volume')

        # Find metadata key svt_container to create container
        nfs_share = volume.get('provider_location')
        if not nfs_share:
            # If an error occurred during volume creation, the
            # provider_location may not exists.  Just log the warning instead
            # of raising an exception.
            LOG.warn(_LW('Unable to determine nfs share for volume'))
            return

        super(SvtNfsDriver, self).delete_volume(volume)

        share_mnt = self._get_mount_point_for_share(nfs_share)
        svt_container = self._svt_container(volume)
        if svt_container is not None:
            share_mnt = os.path.join(share_mnt, svt_container)

            # Delete svt_container if it is empty
            if os.path.exists(share_mnt) and not os.listdir(share_mnt):
                os.rmdir(share_mnt)

    def local_path(self, volume):
        """Get volume path (mounted locally fs path) for given volume."""
        nfs_share = volume.get('provider_location')
        if not nfs_share:
            raise exception.NfsException(
                'Unable to determine nfs share for volume')

        # Find metadata key svt_container to create container
        share_mnt = self._get_mount_point_for_share(nfs_share)
        svt_container = self._svt_container(volume)
        if svt_container is not None:
            share_mnt = os.path.join(share_mnt, svt_container)

            # mkdir must be allowed to run as root
            #   $ cat /etc/cinder/rootwrap.d/volume.filters
            #   mkdir: CommandFilter, mkdir, root
            self._execute('mkdir', '-p', share_mnt, run_as_root=True)
        else:
            raise exception.VolumeMetadataNotFound("Volume has no metadata: "
                                                   "svt_container")

        return os.path.join(share_mnt, volume['name'])

    def backup_volume(self, context, backup, backup_service):
        """Create a new backup from an existing volume."""
        LOG.debug('svt: backup_volume')
        raise NotImplementedError()

    def restore_backup(self, context, backup, volume, backup_service):
        """Restore an existing backup to a new or existing volume."""
        LOG.debug('svt: restore_backup')
        raise NotImplementedError()

    def detach_volume(self, context, volume):
        """Callback for volume detached."""
        LOG.debug('svt: detach_volume')

        nfs_share = volume.get('provider_location')
        if not nfs_share:
            raise exception.NfsException(
                'Unable to determine nfs share for volume')

        volume_id = volume['id']
        volume_name = volume['name']
        (host_address, share_path) = nfs_share.split(':')

        # Get volume metadata
        vol_metadata = self.db.volume_metadata_get(context, volume_id)
        svt_container = DEFAULT_VOLUME_DIR
        if 'svt_container' in vol_metadata.keys():
            svt_container = vol_metadata['svt_container']

        dest_container = DEFAULT_VOLUME_DIR

        svt_destroy_volume = False
        if ('svt_destroy_volume' in vol_metadata.keys()
                and vol_metadata['svt_destroy_volume'] == "True"):
            svt_destroy_volume = True
            dest_container = svt_container  # We do not want to move the volume

        src_path = os.path.join(share_path, svt_container, volume_name)
        tgt_path = os.path.join(share_path, dest_container, volume_name)
        LOG.debug('svt: src_path=%s. tgt_path=%s' % (src_path, tgt_path))

        # Check if the source file exists
        if not os.path.exists(src_path):
            # Do not do anything if it is not there
            msg = (_LW("%s does not exist.") % src_path)
            LOG.warn(msg)
            return

        # Create destination directory if one does not exist
        dest_path = os.path.join(share_path, dest_container)
        if not os.path.exists(dest_path):
            self._execute('mkdir', '-p', dest_path, run_as_root=True)

        if svt_container != dest_container and not svt_destroy_volume:
            LOG.debug('svt: Moving volume into %s' % dest_container)
            (out, err) = self._execute('cp', src_path, tgt_path,
                                       run_as_root=True)
            (out, err) = self._execute('rm', '-rf', src_path, run_as_root=True)

        # Update volume metadata to point to new container
        vol_metadata['svt_container'] = dest_container
        self.db.volume_metadata_update(context, volume_id, vol_metadata, False)

    def _do_create_volume(self, volume):
        """Create a volume on given remote share."""
        LOG.debug('svt: _do_create_volume')

        volume_path = self.local_path(volume)
        volume_size = volume['size']

        # Check if this an existing volume we need to restore
        volume_metadata = volume.get('volume_metadata')
        existing_volume = None
        for item in volume_metadata:
            if item['key'] == 'svt_existing_volume_name':
                existing_volume = item['value']
                break

        # Just rename volume if we are restoring a volume.  Otherwise, just
        # create a sparse volume
        if existing_volume is not None:
            (base_path, file_name) = os.path.split(volume_path)
            existing_volume_path = os.path.join(base_path, existing_volume)
            LOG.debug('svt: Renaming %s to %s'
                      % (existing_volume_path, volume_path))

            self._execute('mv', existing_volume_path, volume_path,
                          run_as_root=True)
        else:
            if getattr(self.configuration,
                       self.driver_prefix + '_sparsed_volumes'):
                self._create_sparsed_file(volume_path, volume_size)
            else:
                self._create_regular_file(volume_path, volume_size)

        self._set_rw_permissions_for_all(volume_path)

    def _svt_container(self, volume):
        """ Find metadata key svt_container."""
        metadata = volume.get('volume_metadata')
        svt_dir = DEFAULT_VOLUME_DIR  # Default container to "_volumes"
        for item in metadata:
            if item['key'] == 'svt_container':
                svt_dir = item['value']
                break

        return svt_dir

    def _is_share_eligible(self, nfs_share, volume_size_in_gib):
        """
        Verifies NFS share is eligible to host volume with given size.

        First validation step: ratio of actual space (used_space / total_space)
        is less than 'nfs_used_ratio'.

        Second validation step: apparent space allocated (differs from actual
        space used when using sparse files) and compares the apparent available
        space (total_available * nfs_oversub_ratio) to ensure enough space is
        available for the new volume.

        :param nfs_share: NFS share
        :param volume_size_in_gib: Size in GB
        """
        # The method is nearly identical to NfsDriver._is_share_eligible.
        # We had to change the following variables: svt_used_ratio &
        # svt_oversub_ratio. We may want to further refine the validation
        # here later.
        used_ratio = self.configuration.svt_used_ratio
        oversub_ratio = self.configuration.svt_oversub_ratio
        requested_volume_size = volume_size_in_gib * units.Gi

        total_size, total_available, total_allocated = \
            self._get_capacity_info(nfs_share)
        apparent_size = max(0, total_size * oversub_ratio)
        apparent_available = max(0, apparent_size - total_allocated)
        used = (total_size - total_available) / total_size

        if used > used_ratio:
            # NOTE(morganfainberg): We check the used_ratio first since
            # with oversubscription it is possible to not have the actual
            # available space but be within our oversubscription limit
            # therefore allowing this share to still be selected as a valid
            # target.
            LOG.debug('%s is above svt_used_ratio' % nfs_share)
            return False
        if apparent_available <= requested_volume_size:
            LOG.debug('%s is above svt_oversub_ratio' % nfs_share)
            return False
        if total_allocated / total_size >= oversub_ratio:
            LOG.debug('%s reserved space is above svt_oversub_ratio' %
                      nfs_share)
            return False
        return True

    def _get_capacity_info(self, nfs_share):
        """Calculate available space on the NFS share."""
        mount_point = self._get_mount_point_for_share(nfs_share)
        if not os.path.exists(mount_point):
            msg = (_("There's no NFS mount point for %s") % nfs_share)
            LOG.error(msg)
            raise exception.NfsException(msg)

        stat, stderr = self._execute('stat', '-f', '-c', '%S %b %a',
                                     mount_point, run_as_root=True)
        block_size, blocks_total, blocks_avail = map(float, stat.split())
        total_available = block_size * blocks_avail
        total_size = block_size * blocks_total

        try:
            total_allocated = self._get_total_allocated_capacity(mount_point)
            return total_size, total_available, total_allocated
        except processutils.ProcessExecutionError as e:
            # If a stale NFS file handles occurs, just re-mount and try again
            if "Stale NFS file handle" in e.stderr:
                umount, stderr = self._execute('umount', mount_point,
                                               run_as_root=True)
                self._ensure_share_mounted(nfs_share)
                total_allocated = self._get_total_allocated_capacity(
                    mount_point)
                return total_size, total_available, total_allocated
            else:
                msg = (_('Failed to find file space usage.\n'
                         'stdout: %(out)s\n'
                         'stderr: %(err)s') % {'out': e.stdout,
                                               'err': e.stderr})
                LOG.error(msg)
                raise exception.NfsException(msg)

    def _get_total_allocated_capacity(self, mount_point):
        """Calculate the total allocated capacity of a given mount point."""
        du, stderr = self._execute('du', '-sb', '--apparent-size',
                                   '--exclude', '*snapshot*', mount_point,
                                   run_as_root=True)
        return float(du.split()[0])
