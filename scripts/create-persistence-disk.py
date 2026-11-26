#!/usr/bin/env python3
"""Create a new VMware disk file with a GPT ext4 partition labeled writable."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='New .vmdk file; existing files are never overwritten')
    parser.add_argument('--size', default='16G', help='Virtual disk capacity, for example 16G or 32G')
    args = parser.parse_args()
    output = args.output.absolute()
    if output.exists() or output.is_symlink():
        parser.error('Output already exists: ' + str(output))
    if output.suffix.lower() != '.vmdk':
        parser.error('Output must be a .vmdk file')
    match = re.fullmatch(r'([1-9][0-9]*)([MG])(?:i?B)?', args.size, re.IGNORECASE)
    if not match:
        parser.error('Size must be an integer followed by M or G')
    capacity = int(match[1]) * (1024 ** (2 if match[2].upper() == 'M' else 3))
    if capacity < 1024 ** 3:
        parser.error('Use at least 1G')
    output.parent.mkdir(parents=True, exist_ok=True)
    offset = 1024 ** 2
    filesystem_bytes = capacity - 2 * offset
    with tempfile.TemporaryDirectory(prefix='.sfos-persistence-', dir=output.parent) as temporary:
        directory = Path(temporary)
        raw = directory / 'disk.raw'
        with raw.open('xb') as image:
            image.truncate(capacity)
        partition = ('label: gpt\n\nstart=2048, size=' + str(filesystem_bytes // 512)
                     + ', type=0FC63DAF-8483-4772-8E79-3D69D8477DE4, name="Sailfish persistence"\n')
        subprocess.run(['sfdisk', '--no-reread', '--no-tell-kernel', str(raw)],
                       input=partition, text=True, check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['mke2fs', '-q', '-F', '-t', 'ext4', '-b', '4096', '-L', 'writable',
                        '-E', f'offset={offset},lazy_itable_init=0,lazy_journal_init=0',
                        str(raw), str(filesystem_bytes // 4096)], check=True)
        if raw.stat().st_size != capacity:
            raise RuntimeError('Filesystem creation changed the disk size')
        subprocess.run(['sfdisk', '--verify', str(raw)], check=True, stdout=subprocess.DEVNULL)
        probe = subprocess.check_output(['blkid', '-p', '-O', str(offset), '-S', str(filesystem_bytes),
                                         '-o', 'export', str(raw)], text=True)
        if 'LABEL=writable\n' not in probe or 'TYPE=ext4\n' not in probe:
            raise RuntimeError('Persistence filesystem verification failed')
        vmdk = directory / 'volume.vmdk'
        subprocess.run(['qemu-img', 'convert', '-f', 'raw', '-O', 'vmdk',
                        '-o', 'subformat=monolithicSparse,adapter_type=lsilogic', str(raw), str(vmdk)], check=True)
        # The temporary directory shares the destination filesystem. link()
        # publishes the finished file atomically and refuses concurrent output.
        os.link(vmdk, output)
    print(f'Created {output}: {args.size} virtual capacity, GPT/ext4, label writable')
    print('Attach this disk to the powered-off VM, then boot the persistent Live entry.')


if __name__ == '__main__':
    main()
