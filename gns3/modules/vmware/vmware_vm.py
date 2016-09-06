# -*- coding: utf-8 -*-
#
# Copyright (C) 2015 GNS3 Technologies Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""
VMware VM implementation.
"""

import os
import sys
import tempfile

from gns3.qt import QtCore
from gns3.node import Node
from gns3.ports.ethernet_port import EthernetPort
from .settings import VMWARE_VM_SETTINGS

import logging
log = logging.getLogger(__name__)


class VMwareVM(Node):

    """
    VirtualBox VM.

    :param module: parent module for this node
    :param server: GNS3 server instance
    :param project: Project instance
    """

    URL_PREFIX = "vmware"
    allocate_vmnet_nio_signal = QtCore.Signal(int, int, str)

    def __init__(self, module, server, project):

        super().__init__(module, server, project)
        log.info("VMware VM instance is being created")
        self._linked_clone = False

        vmware_vm_settings = {"vmx_path": "",
                              "console": None,
                              "console_host": None,
                              "adapters": VMWARE_VM_SETTINGS["adapters"],
                              "adapter_type": VMWARE_VM_SETTINGS["adapter_type"],
                              "use_any_adapter": VMWARE_VM_SETTINGS["use_any_adapter"],
                              "headless": VMWARE_VM_SETTINGS["headless"],
                              "acpi_shutdown": VMWARE_VM_SETTINGS["acpi_shutdown"],
                              "enable_remote_console": VMWARE_VM_SETTINGS["enable_remote_console"],
                              "port_name_format": "Ethernet{0}",
                              "port_segment_size": 0,
                              "first_port_name": None}

        self.settings().update(vmware_vm_settings)

    def _addAdapters(self, adapters):
        """
        Adds adapters.

        :param adapters: number of adapters
        """

        interface_number = segment_number = 0
        for adapter_number in range(0, adapters):
            if self._settings["first_port_name"] and adapter_number == 0:
                port_name = self._settings["first_port_name"]
            else:
                port_name = self._settings["port_name_format"].format(
                    interface_number,
                    segment_number,
                    port0 = interface_number,
                    port1 = 1 + interface_number,
                    segment0 = segment_number,
                    segment1 = 1 + segment_number
                )
                interface_number += 1
                if self._settings["port_segment_size"] and interface_number % self._settings["port_segment_size"] == 0:
                    segment_number += 1
                    interface_number = 0
            new_port = EthernetPort(port_name)
            new_port.setAdapterNumber(adapter_number)
            new_port.setPortNumber(0)
            self._ports.append(new_port)
            log.debug("Adapter {} with port {} has been added".format(adapter_number, port_name))

    def create(self, vmx_path, name=None, node_id=None, port_name_format="Ethernet{0}", port_segment_size=0,
              first_port_name="", linked_clone=False, additional_settings={}, default_name_format=None):
        """
        Creates this VMware VM.

        :param vmx_path: path to the vmx file
        :param name: optional name
        :param node_id: Node identifier
        :param linked_clone: either the VM is a linked clone
        :param additional_settings: additional settings for this VM
        """

        self._linked_clone = linked_clone
        params = {"vmx_path": vmx_path,
                  "linked_clone": linked_clone,
                  "port_name_format": port_name_format,
                  "port_segment_size": port_segment_size,
                  "first_port_name": first_port_name}
        params.update(additional_settings)
        self._create(name, node_id, params, default_name_format)

    def _createCallback(self, result):
        """
        Callback for create.

        :param result: server response (dict)
        """

        # create the ports on the client side
        self._addAdapters(self._settings.get("adapters", 0))

    def update(self, new_settings):
        """
        Updates the settings for this VMware VM.

        :param new_settings: settings (dict)
        """

        params = {}
        for name, value in new_settings.items():
            if name in self._settings and self._settings[name] != value:
                params[name] = value
        if params:
            self._update(params)

    def info(self):
        """
        Returns information about this VMware VM instance.

        :returns: formatted string
        """

        if self.status() == Node.started:
            state = "started"
        else:
            state = "stopped"

        info = """VMware VM {name} is {state}
  Local node ID is {id}
  Server's node ID is {node_id}
  VMware VM's server runs on {host}, console is on port {console}
""".format(name=self.name(),
           id=self.id(),
           node_id=self._node_id,
           state=state,
           host=self.compute().id(),
           console=self._settings["console"])

        port_info = ""
        for port in self._ports:
            if port.isFree():
                port_info += "     {port_name} is empty\n".format(port_name=port.name())
            else:
                port_info += "     {port_name} {port_description}\n".format(port_name=port.name(),
                                                                            port_description=port.description())
        return info + port_info

    def allocateVMnetInterface(self, port_id):
        """
        Requests an UDP port allocation.

        :param port_id: port identifier
        """

        log.debug("{} is requesting a VMnet interface allocation".format(self.name()))
        self.httpPost("/vmware/nodes/{node_id}/interfaces/vmnet".format(node_id=self._node_id), self._allocateVMnetInterfaceCallback, context={"port_id": port_id})

    def _allocateVMnetInterfaceCallback(self, result, error=False, context={}, **kwargs):
        """
        Callback for allocateVMnetInterface

        :param result: server response (dict)
        :param error: indicates an error (boolean)
        """

        if error:
            log.error("error while allocating a VMnet interface for {}: {}".format(self.name(), result["message"]))
            self.server_error_signal.emit(self.id(), result["message"])
        else:
            port_id = context["port_id"]
            vmnet = result["vmnet"]
            log.debug("{} has allocated VMnet interface {}".format(self.name(), vmnet))
            self.allocate_vmnet_nio_signal.emit(self.id(), port_id, vmnet)

    def serialConsole(self):
        """
        Returns either the serial console must be used or not.

        :return: boolean
        """

        if self._settings["enable_remote_console"]:
            return False
        return True

    def serialPipe(self):
        """
        Returns the VM serial pipe path for serial console connections.

        :returns: path to the serial pipe
        """

        if sys.platform.startswith("win"):
            pipe_name = r"\\.\pipe\gns3_vmware\{}".format(self._node_id)
        else:
            pipe_name = os.path.join(tempfile.gettempdir(), "gns3_vmware", "{}".format(self._node_id))
            os.makedirs(os.path.dirname(pipe_name), exist_ok=True)
        return pipe_name

    def console(self):
        """
        Returns the console port for this VMware VM instance.

        :returns: port (integer)
        """

        return self._settings["console"]

    def configPage(self):
        """
        Returns the configuration page widget to be used by the node properties dialog.

        :returns: QWidget object
        """

        from .pages.vmware_vm_configuration_page import VMwareVMConfigurationPage
        return VMwareVMConfigurationPage

    @staticmethod
    def defaultSymbol():
        """
        Returns the default symbol path for this node.

        :returns: symbol path (or resource).
        """

        return ":/symbols/vmware_guest.svg"

    @staticmethod
    def symbolName():

        return "VMware VM"

    @staticmethod
    def categories():
        """
        Returns the node categories the node is part of (used by the device panel).

        :returns: list of node categories
        """

        return [Node.end_devices]

    def __str__(self):

        return "VMware VM"
