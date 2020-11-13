#!/usr/bin/env python3

import os
import sys
import json
import argparse
import platform

from pathlib import Path
from random import randint
from subprocess import run


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
    proc.check_returncode()
    return proc

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

    def unmount_iso(self):
        # VBoxManage storageattach ubuntu-server --storagectl ubuntu-server_sata --port 0 --type dvddrive --medium none
        vbox_manage(["storageattach", self.name, "--storagectl", ])
    
    def mount_iso(self):
        pass

    def is_running(self):
        ps = vbox_manage(["list", "runningvms"])
        for line in ps.stdout.split(b'\n'):
            id, _ = parse_vm_list_line(line)
            if id == self.id:
                return True
        return False

    def __getitem__(self, key):
        return self._info(key)

    def _info(self, key):
        ''' Parses showvminfo command for a given key and returns the raw value '''
        info = vbox_manage(["showvminfo", self.id])
        for line in info.stdout:
            info_key, info_value = parse_vm_info_line(line)
            if info_key is None:
                continue
            if info_key.lower() == key.lower():
                return info_value
        return None


### Command Helpers ###
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
    VBoxManage createvm --name $NAME --ostype Ubuntu_64 --register --basefolder ./vms/
    VBoxManage modifyvm $NAME --cpus $CPUS --memory $MEMORY --vram $VRAM --boot1 dvd --vrde on --vrdeport 5008 --vrdeaddress 127.0.0.1
    VBoxManage modifyvm $NAME --nic1 bridged --bridgeadapter1 enp5s0
    VBoxManage storagectl $NAME --name $STORAGE_NAME --add sata
    VBoxManage createhd --filename $VDI --size $STORAGE --format VDI --variant Standard
    VBoxManage storageattach $NAME --storagectl $STORAGE_NAME --port 1 --type hdd --medium $VDI
    VBoxManage storageattach $NAME --storagectl $STORAGE_NAME --port 0 --type dvddrive --medium $ISO
    '''
    vdi = os.path.join(args.base_folder, "%s.vdi" % args.name)
    storage_name = "%s_sata" % args.name
    vbox_manage(['createvm', '--name', args.name, '--os-type', args.os_type, '--register', '--basefolder', args.base_folder])
    vbox_manage(['modifyvm', args.name, '--cpus', args.cpus, '--memory', args.memory, '--vram', args.vram, '--boot1', 'dvd', '--vrde', 'on', '--vrdeport', args.vrde_port, '--vrdeaddress', args.vrde_host])
    vbox_manage(['modifyvm', args.name, '--nic1', 'bridged', '--bridgeadapter1', args.bridge_adapter])
    vbox_manage(['storagectrl', args.name, '--name', storage_name, '--add', 'sata'])
    vbox_manage(['createhd', '--filename', vdi, '--size', args.storage, '--format', 'VDI', '--variant', 'Standard'])
    vbox_manage(['storageattach', args.name, '--storagectl', storage_name, '--port', '1', '--type', 'hdd', '--medium', vdi])
    vbox_manage(['storageattach', args.name, '--storagectl', storage_name, '--port', '0', '--type', 'dvddrive', '--medium', args.iso])
    return vm_by_name(args.name)


### CLI Command Handlers ###
def ls(args):
    ''' List VMs '''
    vms = list_vms()
    max_name = max([len(vm.name) for vm in vms])
    row_format = "{:<%d}" % max_name
    for vm in vms:
        color = GREEN if vm.is_running() else RESET
        line = row_format.format(vm.name)
        if args.ids:
            line += " " + row_format.format(vm.id)
        if args.running and not vm.is_running():
            continue
        print(color+line+RESET)

def create(args):
    print(args)

def defaults(args):
    set_defaults(vars(args))
    defaults = get_defaults()
    max_key = max([len(key) for key in defaults])
    row_format = "{:<%d}" % max_key
    for key, value in defaults.items():
        line = "%s%s%s " % (BOLD, row_format.format(key), RESET)
        line += str(value)
        print(line)

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

    args = parser.parse_args()
    args.func(args)