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

from cinder import exception
from cinder.i18n import _


class SvtOperationNotSupported(exception.CinderException):
    msg_fmt = _('Requested operation is not supported')


class SvtConnectionFailed(exception.CinderException):
    msg_fmt = _('Failed to establish connection with virtual controller')


class SvtVMAssociateFailed(exception.CinderException):
    msg_fmt = _('Failed to associate a container with a virtual machine')


class SvtZeroCopyFailed(exception.CinderException):
    msg_fmt = _('Failed to copy file')


class SvtMoveFailed(exception.CinderException):
    msg_fmt = _('Failed to move file')


class SvtBackupInfoNotFound(exception.CinderException):
    msg_fmt = _('Could not find backup info')


class SvtRestoreFailed(exception.CinderException):
    msg_fmt = _('Failed to restore volume from backup')


class SvtBackupFailed(exception.CinderException):
    msg_fmt = _('Failed to backup volume')


class SvtBackupDeleteFailed(exception.CinderException):
    msg_fmt = _('Failed to delete volume backup')
