#!/usr/bin/env python3
"""Check host files, Sailfish files and SSH settings across two clean Live boots."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iso', type=Path, required=True)
    parser.add_argument('--disk', type=Path, required=True, help='Dedicated test persistence .vmdk')
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    name = 'sfos-live-persistence-test'
    virsh = ['virsh', '-c', 'qemu:///system']
    marker = 'sfos-persistence-' + uuid.uuid4().hex
    files = ['/etc/' + marker, '/home/live/.' + marker,
             '/opt/sailfish/rootfs/etc/' + marker,
             '/opt/sailfish/rootfs/home/defaultuser/.' + marker]

    def control(*arguments, check=True):
        result = subprocess.run([*virsh, *map(str, arguments)], text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if check and result.returncode:
            raise RuntimeError(result.stdout)
        return result

    if control('dominfo', name, check=False).returncode == 0:
        raise RuntimeError('The persistence test VM already exists')
    if not args.disk.is_file() or args.disk.is_symlink():
        raise RuntimeError('Use a dedicated regular disk image file')

    def boot(phase):
        socket_path = directory / (phase + '.sock')
        if socket_path.exists():
            raise RuntimeError('Use a new test directory: ' + str(socket_path))
        server = socket.socket(socket.AF_UNIX)
        server.bind(str(socket_path))
        os.chmod(socket_path, 0o666)
        server.listen(1)
        server.settimeout(30)
        domain = ET.Element('domain', {'type': 'qemu'})
        ET.SubElement(domain, 'name').text = name
        ET.SubElement(domain, 'memory', {'unit': 'MiB'}).text = '4096'
        ET.SubElement(domain, 'vcpu').text = '4'
        features = ET.SubElement(domain, 'features')
        ET.SubElement(features, 'acpi')
        ET.SubElement(features, 'apic')
        ET.SubElement(domain, 'on_poweroff').text = 'destroy'
        operating_system = ET.SubElement(domain, 'os')
        ET.SubElement(operating_system, 'type', {'arch': 'x86_64', 'machine': 'q35'}).text = 'hvm'
        ET.SubElement(operating_system, 'boot', {'dev': 'cdrom'})
        devices = ET.SubElement(domain, 'devices')
        ET.SubElement(devices, 'emulator').text = '/usr/bin/qemu-system-x86_64'
        for source, device, target, fmt in [(args.iso, 'cdrom', 'sda', 'raw'),
                                             (args.disk, 'disk', 'sdb', 'vmdk')]:
            disk = ET.SubElement(devices, 'disk', {'type': 'file', 'device': device})
            ET.SubElement(disk, 'driver', {'name': 'qemu', 'type': fmt})
            ET.SubElement(disk, 'source', {'file': str(source.resolve())})
            ET.SubElement(disk, 'target', {'dev': target, 'bus': 'sata'})
            if device == 'cdrom':
                ET.SubElement(disk, 'readonly')
        interface = ET.SubElement(devices, 'interface', {'type': 'user'})
        ET.SubElement(interface, 'model', {'type': 'virtio'})
        serial = ET.SubElement(devices, 'serial', {'type': 'unix'})
        ET.SubElement(serial, 'source', {'mode': 'connect', 'path': str(socket_path)})
        ET.SubElement(serial, 'target', {'port': '0'})
        ET.SubElement(ET.SubElement(devices, 'video'), 'model', {'type': 'vga', 'primary': 'yes'})
        xml = directory / (phase + '.xml')
        ET.ElementTree(domain).write(xml, encoding='unicode')
        console = None
        serial_log = (directory / (phase + '-serial.log')).open('wb')
        command_log = (directory / (phase + '-commands.log')).open('w')
        buffer = ''
        sequence = 0

        def receive_until(pattern, timeout=60):
            nonlocal buffer
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                match = re.search(pattern, buffer)
                if match:
                    result = buffer[:match.end()]
                    buffer = buffer[match.end():]
                    return result
                try:
                    block = console.recv(65536)
                except socket.timeout:
                    continue
                if not block:
                    raise RuntimeError('VM console disconnected')
                serial_log.write(block)
                serial_log.flush()
                buffer += block.decode(errors='replace')
            raise TimeoutError('See ' + str(directory / (phase + '-serial.log')))

        def command(text):
            nonlocal sequence
            sequence += 1
            done = 'SFOS_PERSISTENCE_DONE_' + str(sequence)
            console.sendall((text + '; printf "\\n' + done + ':%s\\n" "$?"\n').encode())
            result = receive_until(done + r':\d+\r*\n')
            command_log.write('\nCOMMAND ' + text + '\n' + result + '\n')
            command_log.flush()
            if not re.search(done + r':0\r*\n', result):
                raise RuntimeError('Persistence command failed: ' + text + '\n' + result[-2000:])
            return result

        try:
            print(control('create', xml).stdout, flush=True)
            console, _ = server.accept()
            console.settimeout(1)
            receive_until(r'live@sailfish-live:.*\$', timeout=540)
            command('stty -echo')
            command('grep -w persistent /proc/cmdline')
            command('test "$(cat /run/sailfish-persistence/mode)" = persistent '
                    '&& test "$(cat /run/sailfish-persistence/filesystem)" = ext4 '
                    '&& cat /run/sailfish-persistence/mode /run/sailfish-persistence/device')
            for _ in range(90):
                result = command('sudo systemctl -M sailfish list-units --no-pager >/dev/null 2>&1 '
                                 '&& echo SFOS_CONTAINER_READY || true')
                if re.search(r'\nSFOS_CONTAINER_READY\r*\n', result):
                    break
                time.sleep(1)
            else:
                raise RuntimeError('Sailfish container did not start')
            if phase == 'first':
                for path in files:
                    command('test ! -e ' + shlex.quote(path) + ' && printf %s ' + shlex.quote(marker)
                            + ' | sudo tee ' + shlex.quote(path) + ' >/dev/null')
                command('sudo chown 100000:100000 ' + shlex.quote(files[-1]))
                command('sudo systemctl -M sailfish enable --now sshd.socket')
                print('First boot: host and Sailfish files written; SSH enabled', flush=True)
            else:
                for path in files:
                    command('test "$(sudo cat ' + shlex.quote(path) + ')" = ' + shlex.quote(marker))
                command('test "$(sudo stat -c %u:%g ' + shlex.quote(files[-1]) + ')" = 100000:100000')
                command('sudo systemctl -M sailfish is-enabled sshd.socket')
                command('sudo systemctl -M sailfish is-active sshd.socket')
                print('Second boot: all four files, Sailfish ownership and SSH setting survived', flush=True)
            command('sync')
            console.sendall(b'sudo systemctl poweroff\n')
            deadline = time.monotonic() + 180
            shutdown_output = b''
            while time.monotonic() < deadline:
                if control('dominfo', name, check=False).returncode:
                    return
                try:
                    block = console.recv(65536)
                    if block:
                        serial_log.write(block)
                        serial_log.flush()
                        shutdown_output = (shutdown_output + block)[-4096:]
                        if b'press ENTER:' in shutdown_output:
                            console.sendall(b'\n')
                            shutdown_output = b''
                except socket.timeout:
                    pass
                time.sleep(0.5)
            raise TimeoutError('Clean shutdown timed out')
        finally:
            if control('dominfo', name, check=False).returncode == 0:
                control('destroy', name, check=False)
            if console:
                console.close()
            server.close()
            serial_log.close()
            command_log.close()
            socket_path.unlink(missing_ok=True)

    boot('first')
    boot('second')
    (directory / 'result.json').write_text(json.dumps({
        'passed': True, 'boots': 2, 'filesystem': 'ext4', 'label': 'writable',
        'host_files': True, 'sailfish_files': True, 'sailfish_user_ownership': True,
        'ssh_setting': True,
    }, indent=2) + '\n')
    print('Live persistence checks passed', flush=True)


if __name__ == '__main__':
    main()
