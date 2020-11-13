#!/usr/bin/env python3

import os
import sys
import json
import argparse
import platform

from pathlib import Path
from random import randint
from subprocess import run, CalledProcessError


VBOX_MANAGE = os.getenv("VBOX_MANAGE", "VBoxManage")
APP_DIR = os.getenv("VBOXPY_APP_DIR", os.path.join(str(Path.home()), '.vboxpy'))
DEFAULTS_PATH = os.path.join(APP_DIR, 'defaults.json')
DEFAULT_BASE = os.path.join(str(Path.home()), 'VirtualBox VMs')


# === Text Colors ===
RESET = "\033[0m"  # default/white
BLACK = "\033[30m"  # black
RED = "\033[31m"  # red
GREEN = "\033[32m"  # green
ORANGE = "\033[33m"  # orange
BLUE = "\033[34m"  # blue
PURPLE = "\033[35m"  # purple
CYAN = "\033[36m"  # cyan
GRAY = "\033[37m"  # gray

# === Styles ===
BOLD = "\033[1m"
UNDERLINE = "\033[4m"

# === Macros ===
INFO = BOLD + CYAN + "[*] " + RESET
WARN = BOLD + RED + "[!] " + RESET
PROMPT = BOLD + PURPLE + "[?] " + RESET

def vbox_manage(args):
    ''' Wrapper around teh VBoxManage command '''
    proc = run([VBOX_MANAGE] + args, capture_output=True)
    try:
        proc.check_returncode()
        return proc
    except CalledProcessError as err:
        print(proc.stderr.decode('utf-8'))
        raise err        

def ip_route_show():
    proc = run(['ip', 'route', 'show'], capture_output=True)
    proc.check_returncode()
    return proc

def parse_vm_list_line(line):
    ''' Parses vm list output from VBoxManage '''
    # name
    lquote = line.find(b'"') + 1
    rquote = line[lquote:].find(b'"') + 1
    name = line[lquote:rquote]
    # id
    lbrace = line.find(b'{') + 1
    rbrace = line[lquote:].find(b'}') + 1
    id = line[lbrace:rbrace]
    return id.decode('utf-8'), name.decode('utf-8')

def parse_vm_info_line(line):
    '''
    Parses most vminfo output from VBoxManage, the command
    is inconsistent in how it display some information, so
    for example USB output may not be parsed correctly.
    '''
    if b':' not in line:
        return None, None
    key, value = line.split(b':', 1)
    return key.decode('utf-8'), value.strip()


class VirtualMachine(object):

    ''' Virtual Machine class for easy access to VM attributes '''

    def __init__(self, id, name):
        self.id = id
        self.name = name

    def __str__(self):
        return "<id: %s, name: %s>" % (self.id, self.name)

    def __eq__(self, other):
        return self.id == other.id

    def eject(self):
        ''' Eject disk from DVDDrive, this function currently makes assumptions about names '''
        storage_name = "%s_sata" % self.name
        vbox_manage(["storageattach", self.name, "--storagectl", storage_name, '--port', '0', '--type', 'dvddrive', '--medium', 'none'])
    
    def is_running(self):
        ps = vbox_manage(["list", "runningvms"])
        for line in ps.stdout.split(b'\n'):
            id, _ = parse_vm_list_line(line)
            if id == self.id:
                return True
        return False
    
    def start(self):
        vbox_manage(['startvm', self.name, '--type', 'headless'])

    def stop(self):
        vbox_manage(['controlvm', self.name, 'poweroff'])
    
    def take_snapshot(self, name, description=''):
        vbox_manage(['snapshot', self.name, 'take', name, '--description', description])

    def __getitem__(self, key):
        return self._info(key)

    def _info(self, key):
        ''' Parses showvminfo command for a given key and returns the raw value '''
        info = vbox_manage(["showvminfo", self.id])
        for line in info.stdout.split(b'\n'):
            info_key, info_value = parse_vm_info_line(line)
            if info_key is None:
                continue
            if info_key.lower() == key.lower():
                return info_value
        return None


### Command Helpers ###
def confirm_prompt(prompt):
    response = input(PROMPT+prompt+' [Y/n]: ')
    return str(response).lower() in ['y', 'yes']

def list_ostypes():
    ls = vbox_manage(["list", "ostypes"])
    ostypes = []
    for line in ls.stdout.split(b'\n'):
        if line.startswith(b"ID:"):
            ostypes.append(line[3:].strip().decode('utf-8'))
    return ostypes

def list_vms():
    ls = vbox_manage(["list", "vms"])
    vms = []
    for line in ls.stdout.split(b'\n'):
        if not line:
            continue
        id, name = parse_vm_list_line(line)
        vms.append(VirtualMachine(id, name))
    return vms

def vm_by_name(name):
    for vm in list_vms():
        if vm.name == name:
            return vm
    return None

def vm_by_id(id):
    for vm in list_vms():
        if vm.id == id:
            return vm
    return None

def get_default_network_adapter():
    if platform.system() not in ['Linux']:
        return None
    ip = ip_route_show()
    for line in ip.stdout.split(b'\n'):
        if not line.startswith(b'default'):
            continue
        words = line.split(b' ')
        return words[words.index(b'dev')+1].decode('utf-8')

def get_default(key, default_value=None):
    if not os.path.exists(DEFAULTS_PATH):
        return default_value
    try:
        with open(DEFAULTS_PATH, 'r') as fp:
            defaults = json.loads(fp.read())
            return defaults.get(key, default_value)
    except:
        return default_value

def get_defaults():
    if not os.path.exists(DEFAULTS_PATH):
        return {}
    try:
        with open(DEFAULTS_PATH, 'r') as fp:
            return json.loads(fp.read())
    except:
        return {}

def set_defaults(args):
    defaults = {}
    if os.path.exists(DEFAULTS_PATH):
        try:
            with open(DEFAULTS_PATH, 'r') as fp:
                defaults = json.loads(fp.read())
        except:
            pass
    if 'func' in args:
        del args['func']
    defaults.update(args)
    if not os.path.exists(APP_DIR):
        os.mkdir(APP_DIR)
    with open(DEFAULTS_PATH, 'w') as fp:
        fp.write(json.dumps(defaults))

def create_vm(args):
    '''
    Create a virtual machine and mount the OS installation ISO
    '''
    vdi = os.path.join(args.base_folder, "%s.vdi" % args.name)
    storage_name = "%s_sata" % args.name
    vbox_manage(['createvm', '--name', args.name, '--ostype', args.os_type, '--register', '--basefolder', args.base_folder])
    vbox_manage(['modifyvm', args.name, '--cpus', str(args.cpus), '--memory', str(args.ram), '--vram', str(args.vram), '--boot1', 'dvd', '--vrde', 'on', '--vrdeport', str(args.vrde_port), '--vrdeaddress', args.vrde_host])
    vbox_manage(['modifyvm', args.name, '--nic1', 'bridged', '--bridgeadapter1', args.bridge_adapter])
    vbox_manage(['storagectl', args.name, '--name', storage_name, '--add', 'sata'])
    vbox_manage(['createhd', '--filename', vdi, '--size', str(args.storage), '--format', 'VDI', '--variant', 'Standard'])
    vbox_manage(['storageattach', args.name, '--storagectl', storage_name, '--port', '1', '--type', 'hdd', '--medium', vdi])
    vbox_manage(['storageattach', args.name, '--storagectl', storage_name, '--port', '0', '--type', 'dvddrive', '--medium', args.iso])
    return vm_by_name(args.name)


### CLI Command Handlers ###
def ls(args):
    ''' List virtual machines '''
    vms = list_vms()
    max_name = max([len(vm.name) for vm in vms])
    row_format = "{:<%d}" % max_name
    for vm in vms:
        color = GREEN if vm.is_running() else RESET
        line = row_format.format(vm.name)
        if args.ids:
            line += " " + row_format.format(vm.id)
        if args.vrde:
            line += " VRDE: " + vm['VRDE'].decode('utf-8')
        if args.running and not vm.is_running():
            continue
        print(color+line+RESET)

def create(args):
    ''' Create a new virtual machine '''
    if vm_by_name(args.name) is not None:
        print(WARN+"VM '%s' already exists" % args.name)
        return
    vm = create_vm(args)
    print(INFO+"Created VM '%s'" % vm.name)
    print(INFO+"VRDE: " + vm['VRDE'].decode('utf-8'))

def defaults(args):
    ''' Configure default settings '''
    set_defaults(vars(args))
    defaults = get_defaults()
    max_key = max([len(key) for key in defaults])
    row_format = "{:<%d}" % max_key
    for key, value in defaults.items():
        line = "%s%s%s " % (BOLD, row_format.format(key), RESET)
        line += str(value)
        print(line)

def rm(args):
    ''' Delete a VM '''
    vm = None
    if args.name:
        vm = vm_by_name(args.name)
    elif args.id:
        vm = vm_by_id(args.id)
    if vm is None:
        if args.name:
            print(WARN+"No virtual machine with name '%s'" % args.name)
        elif args.id:
            print(WARN+"No virtual machine with id '%s'" % args.id)
        return
    confirm = confirm_prompt('Delete %s (id: %s)' % (vm.name, vm.id))
    if not confirm:
        return
    vbox_manage(['unregistervm', vm.name, '--delete'])


def start(args):
    ''' Start a VM '''
    vm = None
    if args.name:
        vm = vm_by_name(args.name)
    elif args.id:
        vm = vm_by_id(args.id)
    if vm is None:
        if args.name:
            print(WARN+"No virtual machine with name '%s'" % args.name)
        elif args.id:
            print(WARN+"No virtual machine with id '%s'" % args.id)
        return
    vm.start()
    print(INFO+"Started vm '%s'" % vm.name)

def stop(args):
    ''' Stop a VM '''
    vm = None
    if args.name:
        vm = vm_by_name(args.name)
    elif args.id:
        vm = vm_by_id(args.id)
    if vm is None:
        if args.name:
            print(WARN+"No virtual machine with name '%s'" % args.name)
        elif args.id:
            print(WARN+"No virtual machine with id '%s'" % args.id)
        return
    vm.stop()
    print(INFO+"Stopped vm '%s'" % vm.name)


def main(args):
    pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog=__file__)
    parser.set_defaults(func=main)
    
    subparsers = parser.add_subparsers(help='Sub-commands')

    # defaults
    parser_defaults = subparsers.add_parser('defaults', help='Configure default VM settings')
    parser_defaults.add_argument('--base-folder', 
        default=get_default('base_folder', DEFAULT_BASE),
        type=str,
        help='Set default base folder to store VMs')
    parser_defaults.add_argument('--os-type',
        default=get_default('os-type', 'Other_64'),
        choices=list_ostypes(),
        type=str,
        help='Default guest OS type')
    parser_defaults.add_argument('--cpus',
        default=get_default('cpus', 4),
        type=int,
        help='Default number of CPU cores')
    parser_defaults.add_argument('--ram',
        default=get_default('ram', 4096),
        type=int,
        help='Default RAM (MBs)')
    parser_defaults.add_argument('--vram',
        default=get_default('vram', 128),
        type=int,
        help='Default video memory (MBs)')
    parser_defaults.add_argument('--storage',
        default=get_default('storage', 60000),
        type=int,
        help='Default disk size (MBs)')
    parser_defaults.add_argument('--bridge-adapter',
        default=get_default('bridge_adapter', get_default_network_adapter()),
        type=str,
        help='Default bridged network adapter')
    parser_defaults.set_defaults(func=defaults)

    # list
    parser_ls = subparsers.add_parser('ls', help='List VMs')
    parser_ls.add_argument('--running', action='store_true', help='List only running VMs')
    parser_ls.add_argument('--vrde', action='store_true', help='Show VRDE info')
    parser_ls.add_argument('--ids', action='store_true', help='Show VM IDs')
    parser_ls.set_defaults(func=ls)

    # create
    parser_create = subparsers.add_parser('create', help='Create a VM')
    parser_create.add_argument('--name', required=True, type=str, help='VM name')
    parser_create.add_argument('--iso', required=True, type=str, help='Path to operating system ISO')
    parser_create.add_argument('--os-type',
        default=get_default('os-type', 'Other_64'),
        choices=list_ostypes(),
        type=str,
        help='Specify guest OS type')
    parser_create.add_argument('--base-folder',
        default=get_default('base_folder', DEFAULT_BASE),
        type=str,
        help='Base folder to store VMs')
    parser_create.add_argument('--cpus',
        default=get_default('cpus', 4),
        type=int,
        help='Number of CPU cores')
    parser_create.add_argument('--ram',
        default=get_default('ram', 4096),
        type=int,
        help='RAM (MBs)')
    parser_create.add_argument('--vram',
        default=get_default('vram', 128),
        type=int,
        help='Video memory (MBs)')
    parser_create.add_argument('--storage',
        default=get_default('storage', 60000),
        type=int,
        help='Disk size (MBs)')
    parser_create.add_argument('--vrde-port',
        default=randint(5000, 6000),
        type=int,
        help='VRDE listen port')
    parser_create.add_argument('--vrde-host',
        default='127.0.0.1',
        type=str,
        help='VRDE host interface')
    parser_create.add_argument('--bridge-adapter',
        default=get_default('bridge_adapter', get_default_network_adapter()),
        type=str,
        help='Bridged network adapter')
    parser_create.set_defaults(func=create)

    # rm
    parser_rm = subparsers.add_parser('rm', help='Delete a VM')
    parser_rm.add_argument('--name', type=str, help='VM name')
    parser_rm.add_argument('--id', type=str, help='VM id')
    parser_rm.set_defaults(func=rm)

    # start
    parser_start = subparsers.add_parser('start', help='Start a VM')
    parser_start.add_argument('--name', type=str, help='VM name')
    parser_start.add_argument('--id', type=str, help='VM id')
    parser_start.set_defaults(func=start)

    # stop
    parser_stop = subparsers.add_parser('stop', help='Stop a VM')
    parser_stop.add_argument('--name', type=str, help='VM name')
    parser_stop.add_argument('--id', type=str, help='VM id')
    parser_stop.set_defaults(func=stop)

    args = parser.parse_args()
    args.func(args)