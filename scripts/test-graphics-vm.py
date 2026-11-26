#!/usr/bin/env python3
"""Boot an ephemeral libvirt VM and inspect the complete Sailfish graphics path."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import shlex
import socket
import subprocess
import time
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--iso', type=Path, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--graphics', choices=['gpu', 'software', 'baseline'], default='gpu')
    parser.add_argument('--render-node', default='/dev/dri/renderD128')
    parser.add_argument('--skip-benchmark', action='store_true')
    parser.add_argument('--check-ssh', action='store_true')
    parser.add_argument('--ssh-only', action='store_true')
    args = parser.parse_args()
    if args.ssh_only:
        args.check_ssh = True
        args.skip_benchmark = True
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    name = 'sfos-graphics-' + args.graphics + '-test'
    virsh = ['virsh', '-c', 'qemu:///system']

    def control(*arguments, check=True):
        return subprocess.run([*virsh, *map(str, arguments)], text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=check).stdout

    if subprocess.run([*virsh, 'dominfo', name], stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL).returncode == 0:
        raise RuntimeError('A test domain with this name already exists: ' + name)
    console_path = directory / 'console.sock'
    console_path.unlink(missing_ok=True)
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(console_path))
    os.chmod(console_path, 0o666)
    listener.listen(1)
    listener.settimeout(30)
    domain = ET.Element('domain', {'type': 'qemu'})
    ET.SubElement(domain, 'name').text = name
    ET.SubElement(domain, 'memory', {'unit': 'MiB'}).text = '4096'
    ET.SubElement(domain, 'vcpu').text = '4'
    operating_system = ET.SubElement(domain, 'os')
    ET.SubElement(operating_system, 'type', {'arch': 'x86_64', 'machine': 'q35'}).text = 'hvm'
    ET.SubElement(operating_system, 'boot', {'dev': 'cdrom'})
    devices = ET.SubElement(domain, 'devices')
    ET.SubElement(devices, 'emulator').text = '/usr/bin/qemu-system-x86_64'
    disk = ET.SubElement(devices, 'disk', {'type': 'file', 'device': 'cdrom'})
    ET.SubElement(disk, 'driver', {'name': 'qemu', 'type': 'raw'})
    ET.SubElement(disk, 'source', {'file': str(args.iso.resolve())})
    ET.SubElement(disk, 'target', {'dev': 'sda', 'bus': 'sata'})
    ET.SubElement(disk, 'readonly')
    interface = ET.SubElement(devices, 'interface', {'type': 'user'})
    ET.SubElement(interface, 'model', {'type': 'virtio'})
    serial = ET.SubElement(devices, 'serial', {'type': 'unix'})
    ET.SubElement(serial, 'source', {'mode': 'connect', 'path': str(console_path)})
    ET.SubElement(serial, 'target', {'port': '0'})
    ET.SubElement(devices, 'controller', {'type': 'usb', 'model': 'qemu-xhci'})
    ET.SubElement(devices, 'input', {'type': 'tablet', 'bus': 'usb'})
    video = ET.SubElement(devices, 'video')
    if args.graphics in ['gpu', 'baseline']:
        graphics = ET.SubElement(devices, 'graphics', {'type': 'egl-headless'})
        ET.SubElement(graphics, 'gl', {'rendernode': args.render_node})
        model = ET.SubElement(video, 'model', {'type': 'virtio', 'heads': '1', 'primary': 'yes'})
        ET.SubElement(model, 'acceleration', {'accel3d': 'yes'})
    else:
        ET.SubElement(video, 'model', {'type': 'vga', 'heads': '1', 'primary': 'yes'})
    xml = directory / 'domain.xml'
    ET.ElementTree(domain).write(xml, encoding='unicode')
    started = False
    console = None
    serial_log = (directory / 'serial.log').open('wb')
    command_log = (directory / 'commands.log').open('w')
    buffer = ''
    sequence = 0

    def receive_until(pattern, timeout):
        nonlocal buffer
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = re.search(pattern, buffer)
            if found:
                text = buffer[:found.end()]
                buffer = buffer[found.end():]
                return text
            try:
                block = console.recv(65536)
            except socket.timeout:
                continue
            if not block:
                raise RuntimeError('VM console closed')
            serial_log.write(block)
            serial_log.flush()
            buffer += block.decode(errors='replace')
        raise TimeoutError('VM console timed out; see ' + str(directory / 'serial.log'))

    def command(text, timeout=45):
        nonlocal sequence
        sequence += 1
        marker = f'SFOS_TEST_DONE_{sequence}'
        separator = ' ' if text.rstrip().endswith('&') else '; '
        console.sendall((text + separator + f'printf "\\n{marker}:%s\\n" "$?"\n').encode())
        output = receive_until(marker + r':\d+\r*\n', timeout)
        command_log.write('\nCOMMAND ' + text + '\n' + output + '\n')
        command_log.flush()
        match = re.search(marker + r':(\d+)', output)
        if match.group(1) != '0':
            raise RuntimeError('VM command failed: ' + text + '\n' + output[-2000:])
        return output

    def monitor(value):
        result = json.loads(control('qemu-monitor-command', name, json.dumps(value)))
        if 'error' in result:
            raise RuntimeError(result['error'])
        return result

    guest = 'sudo nsenter -t "$(machinectl show sailfish -p Leader --value)" --mount --pid --net --root '
    user = guest + '/usr/sbin/runuser -u defaultuser -- env XDG_RUNTIME_DIR=/run/user/100000 ' \
        'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/100000/dbus/user_bus_socket ' \
        'WAYLAND_DISPLAY=/run/display/wayland-0 QT_QPA_PLATFORM=wayland LP_NUM_THREADS=2 '
    try:
        print(control('create', xml), flush=True)
        started = True
        console, _ = listener.accept()
        console.settimeout(1)
        print('Waiting for Ubuntu login and Sailfish session', flush=True)
        receive_until(r'live@sailfish-live:.*\$', 540)
        command('stty -echo')
        ready = False
        for attempt in range(90):
            output = command('sudo machinectl show sailfish -p Leader --value 2>/dev/null || true')
            if re.search(r'\n\d+\r*\n', output):
                if attempt % 10 == 0:
                    command('sudo journalctl -M sailfish -b --no-pager -n 40')
                output = command(guest + '/bin/sh -c "test -S /run/display/wayland-0 && echo SFOS_WAYLAND_READY" || true')
                if 'SFOS_WAYLAND_READY' in output:
                    ready = True
                    break
            time.sleep(2)
        if not ready:
            command('sudo journalctl -M sailfish -b --no-pager -n 100')
            command('sudo journalctl -u sailfish-live -b --no-pager -n 50')
            raise RuntimeError('Sailfish Wayland socket did not appear')
        command('sudo journalctl -u sailfish-live.service -b --no-pager -n 25')
        release = json.loads((Path(__file__).resolve().parents[1] / 'config/release.json').read_text())['version']
        command(guest + '/bin/sh -c ' + shlex.quote('. /etc/os-release; test "$VERSION_ID" = ' + release + '; cat /etc/os-release'))
        print(control('screenshot', name, directory / 'lockscreen.ppm'), flush=True)
        command(user + 'dbus-send --system --type=method_call --print-reply --dest=com.nokia.mce '
                '/com/nokia/mce/request com.nokia.mce.request.req_display_state_on')
        if args.graphics != 'baseline':
            output = command('cat /run/sailfish-graphics/mode /run/sailfish-graphics/reason')
            expected = 'gpu' if args.graphics == 'gpu' else 'software'
            if not re.search(r'\n' + expected + r'\r*\n', output):
                raise RuntimeError('Unexpected graphics mode: ' + output)
            output = command(user + 'LP_NUM_THREADS=2 WAYLAND_DISPLAY=/run/display/wayland-0 '
                             '/usr/local/bin/sailfish-graphics-probe --wayland', timeout=180)
            reports = [json.loads(line) for line in output.splitlines() if line.startswith('{')]
            report = reports[-1]
            (directory / 'application-egl.json').write_text(json.dumps(report, indent=2) + '\n')
            if args.graphics == 'gpu':
                if any(driver in report['gl_renderer'].lower() for driver in ['llvmpipe', 'softpipe']):
                    raise RuntimeError('Application still renders in software')
                if not any(item['name'] == 'wl_drm' and item['version'] >= 2 for item in report['wayland_globals']):
                    raise RuntimeError('Lipstick did not advertise wl_drm')
            if not all('/usr/lib/sailfish-live/mesa/' in path for path in report['graphics_libraries']):
                raise RuntimeError('Application mixed graphics library bundles')
            print('Application EGL:', report['gl_renderer'], flush=True)
            command(guest + '/sbin/ldconfig -p | grep -E "libEGL.so.1|libGLESv2.so.2|libgbm.so.1"')
        # Horizontal unlock gesture through the virtual USB tablet.
        for x, pressed in [(8192, None), (8192, True), (12288, None), (16384, None), (24576, None), (24576, False)]:
            events = [{'type': 'abs', 'data': {'axis': 'x', 'value': x}},
                      {'type': 'abs', 'data': {'axis': 'y', 'value': 16384}}]
            if pressed is not None:
                events.append({'type': 'btn', 'data': {'button': 'left', 'down': pressed}})
            monitor({'execute': 'input-send-event', 'arguments': {'events': events}})
            time.sleep(0.3)
        time.sleep(2)
        command(user + 'dbus-send --system --type=method_call --print-reply --dest=com.nokia.mce '
                '/com/nokia/mce/request com.nokia.mce.request.req_display_state_on')
        command(user + 'dbus-send --system --type=method_call --print-reply --dest=com.nokia.mce '
                '/com/nokia/mce/request com.nokia.mce.request.req_tklock_mode_change string:unlocked')
        print(control('screenshot', name, directory / 'unlocked.ppm'), flush=True)
        if not args.skip_benchmark and args.graphics != 'software':
            benchmark = Path(__file__).resolve().parents[1] / 'src/scroll-benchmark.qml'
            encoded = base64.b64encode(benchmark.read_bytes()).decode()
            command('printf %s ' + shlex.quote(encoded) + ' | ' + guest + '/bin/sh -c ' +
                    shlex.quote('base64 -d > /tmp/sfos-scroll-benchmark.qml'))
            output = command(user + 'WAYLAND_DISPLAY=/run/display/wayland-0 QT_QPA_PLATFORM=wayland '
                             'LP_NUM_THREADS=2 QSG_INFO=1 /usr/lib/qt5/bin/qmlscene /tmp/sfos-scroll-benchmark.qml', timeout=240)
            stats = re.search(r'SFOS_SCROLL_STATS (\{[^\r\n]+\})', output)
            if not stats:
                raise RuntimeError('No Qt Quick frame statistics')
            (directory / 'scroll-stats.json').write_text(json.dumps(json.loads(stats.group(1)), indent=2) + '\n')
            print('Qt Quick scroll:', stats.group(1), flush=True)
        if args.graphics != 'baseline' and not args.ssh_only:
            command(user + 'invoker --single-instance --type=silica-qt5 /usr/bin/jolla-settings '
                    '> /tmp/graphics-settings.log 2>&1 &', timeout=20)
            for attempt in range(30):
                output = command(guest + '/bin/sh -c ' + shlex.quote(
                    'for pid in $(pgrep -f "^/usr/bin/jolla-settings( |$)"); do grep -E "libEGL|libGLES|libgallium|libgbm" /proc/$pid/maps; done'))
                if '/usr/lib/sailfish-live/mesa/' in output:
                    break
                time.sleep(2)
            command('cat /tmp/graphics-settings.log || true')
            command(guest + '/bin/sh -c ' + shlex.quote('ps -ef | grep -E "booster|jolla-settings"'))
            command('sudo journalctl -M sailfish -b --no-pager -n 80')
            mappings = [line for line in output.splitlines()
                        if '/' in line and any(name in line for name in ['libEGL', 'libGLES', 'libgallium', 'libgbm'])]
            if not mappings or not all('/usr/lib/sailfish-live/mesa/' in line for line in mappings):
                raise RuntimeError('Normal settings launch did not map the new graphics bundle')
            output = command(guest + '/bin/sh -c ' + shlex.quote(
                'for pid in $(pgrep -f "^/usr/bin/jolla-settings( |$)"); do '
                'grep "^Groups:" /proc/$pid/status; '
                'for fd in /proc/$pid/fd/*; do readlink "$fd" || true; done; done'))
            if args.graphics == 'gpu' and '/dev/dri/renderD' not in output:
                raise RuntimeError('Normal settings launch did not open a GPU render node')
            if args.graphics == 'gpu':
                command(user + '/usr/bin/sailjail -p jolla-calculator.desktop /usr/bin/jolla-calculator '
                        '> /tmp/graphics-calculator.log 2>&1 &', timeout=20)
                for attempt in range(30):
                    output = command(guest + '/bin/sh -c ' + shlex.quote(
                        'for pid in $(pgrep -f "^/usr/bin/jolla-calculator( |$)"); do '
                        'grep "^Groups:" /proc/$pid/status; '
                        'grep -E "libEGL|libGLES|libgallium|libgbm" /proc/$pid/maps; '
                        'for fd in /proc/$pid/fd/*; do readlink "$fd" || true; done; done'))
                    if '/dev/dri/renderD' in output:
                        break
                    time.sleep(2)
                command('cat /tmp/graphics-calculator.log || true')
                command(guest + '/bin/sh -c ' + shlex.quote('ps -ef | grep -E "sailjail|calculator"'))
                if '/dev/dri/renderD' not in output or '/usr/lib/sailfish-live/mesa/' not in output:
                    raise RuntimeError('Sandboxed calculator did not open the native GPU bundle and render node')
                print('Sandboxed calculator GPU access verified', flush=True)
        print(control('screenshot', name, directory / 'screen.ppm'), flush=True)
        if args.check_ssh:
            password_manager = ('exec dbus-send --system --type=method_call --print-reply '
                                '--dest=org.nemo.passwordmanager /org/nemo/passwordmanager '
                                'org.nemo.passwordmanager.')
            def password_call(method):
                # Settings is setgid privileged; match its effective group.
                return user + 'sg privileged -c ' + shlex.quote(password_manager + method)
            command(password_call('isRemoteLoginEnabled'))
            command(password_call('setPassword string:sfos-ssh-test-only'))
            command(password_call('setRemoteLoginEnabled boolean:true'))
            for attempt in range(30):
                output = command(password_call('isRemoteLoginEnabled'))
                if 'boolean true' in output:
                    break
                time.sleep(1)
            if 'boolean true' not in output:
                raise RuntimeError('Developer settings could not enable SSH')
            command(guest + '/usr/bin/systemctl is-active sshd.socket')
            command(guest + '/usr/bin/systemctl status sshd.socket --no-pager -l')
            askpass = '#!/bin/sh\nprintf "%s\\n" "$SFOS_TEST_SSH_PASSWORD"\n'
            command(guest + '/bin/sh -c ' + shlex.quote(
                'printf %s ' + shlex.quote(askpass) + ' > /tmp/sfos-ssh-askpass; chmod 0755 /tmp/sfos-ssh-askpass'))
            output = command(user + 'SFOS_TEST_SSH_PASSWORD=sfos-ssh-test-only '
                'SSH_ASKPASS=/tmp/sfos-ssh-askpass SSH_ASKPASS_REQUIRE=force DISPLAY=sfos-test '
                '/bin/sh -c ' + shlex.quote(
                    'gateway=$(ip -4 route show default | awk \'{print $3; exit}\'); '
                    'setsid ssh -T -p 2222 -o PreferredAuthentications=password -o PubkeyAuthentication=no '
                    '-o StrictHostKeyChecking=no -o UserKnownHostsFile=/tmp/sfos-ssh-known-hosts '
                    '-o ConnectTimeout=60 defaultuser@"$gateway" echo SFOS_SSH_LOGIN_OK'), timeout=120)
            if 'SFOS_SSH_LOGIN_OK' not in output:
                raise RuntimeError('Password SSH login through the host forwarding socket failed')
            command(password_call('setRemoteLoginEnabled boolean:false'))
            for attempt in range(30):
                output = command(password_call('isRemoteLoginEnabled'))
                if 'boolean false' in output:
                    break
                time.sleep(1)
            if 'boolean false' not in output:
                raise RuntimeError('Developer settings could not disable SSH')
            print('Developer SSH enable, password login through port 2222, and disable verified', flush=True)
        (directory / 'result.json').write_text(json.dumps({'graphics': args.graphics, 'passed': True}, indent=2) + '\n')
        print('VM graphics checks passed:', args.graphics, flush=True)
    finally:
        if started:
            print(control('destroy', name, check=False), flush=True)
        if console:
            console.close()
        listener.close()
        serial_log.close()
        command_log.close()
        console_path.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
