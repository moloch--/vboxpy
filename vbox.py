#!/usr/bin/env python3

import os
import pprint
import argparse

from subprocess import run

VBoxManage = os.getenv("VBOX_MANAGE", "VBoxManage")


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
    proc = run([VBoxManage] + args, capture_output=True)
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

    ''' Helper class to wrap VM '''

    def __init__(self, id, name):
        self.id = id
        self.name = name

    def __str__(self):
        return "<id: %s, name: %s>" % (self.id, self.name)

    def __eq__(self, other):
        return self.id == other.id

    def unmount_dvd(self):
        # VBoxManage storageattach ubuntu-server --storagectl ubuntu-server_sata --port 0 --type dvddrive --medium none
        vbox_manage(["storageattach", self.name, "--storagectl", ])
    
    def is_running(self):
        ps = vbox_manage(["list", "runningvms"])
        for line in ps.stdout.split(b'\n'):
            id, _ = parse_vm_list_line(line)
            if id == self.id:
                return True
        return False

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


def list_vms(debug=False):
    ls = vbox_manage(["list", "vms"])
    vms = []
    for line in ls.stdout.split(b'\n'):
        if not line:
            continue
        id, name = parse_vm_list_line(line)
        vms.append(VirtualMachine(id, name))
    return vms


### Command Handlers ###

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


def main(args):
    pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog='PROG')
    parser.set_defaults(func=main)

    # list
    subparsers = parser.add_subparsers(help='ls help')
    parser_ls = subparsers.add_parser('ls', help='List VMs')
    parser_ls.add_argument('--running', action='store_true', help='List only running VMs')
    parser_ls.add_argument('--ids', action='store_true', help='Show VM IDs')
    parser_ls.set_defaults(func=ls)

    parser_create = subparsers.add_parser('create', help='Create a VM')
    parser_create.set_defaults(func=create)

    args = parser.parse_args()
    args.func(args)